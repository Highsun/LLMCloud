"""Initial run storage used by M2-04; independent artifact auditing follows in M2-05."""

from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import platform
import time

from pydantic import ValidationError

from trainer.contracts import ArtifactFile, RunEnvironment, TrainRequest, TrainResult, TrainingManifest, TrainingSnapshot, TrainingSummary
from trainer.events import fail
from trainer.model_cache import PROJECT_ROOT


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_request(request):
    """Revalidate nested mutable config and resolve aliases before any output writes."""
    try:
        if not isinstance(request, TrainRequest):
            raise ValueError("Expected TrainRequest")
        values = request.model_dump()
        for key in ("dataset_path", "validation_dataset_path", "dataset_manifest_path"):
            if values[key] is not None:
                values[key] = values[key].resolve(strict=True)
                if not values[key].is_file():
                    raise ValueError("Expected regular input")
        for key in ("output_dir", "cache_dir", "log_path"):
            supplied = values[key]
            if key != "cache_dir" and (supplied.exists() or supplied.is_symlink()):
                raise ValueError("Output or log already exists")
            values[key] = supplied.resolve()
        resolved = TrainRequest.model_validate(values)
        # Writing beneath any input ancestor file is rejected by mkdir; cache must
        # also never be an ancestor of the task log.
        if resolved.log_path.is_relative_to(resolved.cache_dir):
            raise ValueError("Log is inside model cache")
        return resolved
    except (OSError, RuntimeError, TypeError, ValueError, ValidationError) as error:
        fail("INVALID_REQUEST", "preflight", "训练请求、输入路径无效，或任务输出/日志已存在。", cause=error)


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        stream.write(value.model_dump_json(indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def snapshot(request):
    return TrainingSnapshot(**{key: getattr(request, key) for key in TrainingSnapshot.model_fields})


def environment(torch):
    def git(*args):
        return subprocess.run(["git", *args], cwd=PROJECT_ROOT, check=True, capture_output=True,
                              text=True, timeout=10).stdout.strip()
    return RunEnvironment(
        code_commit=git("rev-parse", "HEAD"), working_tree_dirty=bool(git("status", "--porcelain")),
        uv_lock_sha256=sha256(PROJECT_ROOT / "uv.lock"), python_version=platform.python_version(),
        cuda_runtime=torch.version.cuda, gpu_name=torch.cuda.get_device_name(0),
        packages={name: version(name) for name in ("torch", "transformers", "datasets", "peft", "trl", "accelerate")},
    )


def finish(request, prepared, cached, execution, env, started_at, started_clock):
    """Check saved references and inventory before publishing the only success marker."""
    root = request.output_dir
    try:
        adapter = json.loads((root / "adapter/adapter_config.json").read_text(encoding="utf-8"))
        if (adapter.get("base_model_name_or_path") != request.base_model
                or adapter.get("revision") != request.model_revision
                or adapter.get("peft_type") != "LORA"
                or adapter.get("r") != request.config.lora_r
                or set(adapter.get("target_modules", [])) != set(request.config.target_modules)):
            raise ValueError("Saved adapter configuration mismatch")
        if TrainingSnapshot.model_validate_json((root / "training_config.json").read_bytes()) != snapshot(request):
            raise ValueError("Saved snapshot differs from execution request")
        json.loads((root / "tokenizer/tokenizer_config.json").read_text(encoding="utf-8"))
        required = ("adapter/adapter_model.safetensors", "adapter/adapter_config.json",
                    "tokenizer/tokenizer_config.json", "tokenizer/tokenizer.json", "tokenizer/chat_template.jinja",
                    "metrics.jsonl", "training_config.json")
        for key in required:
            if not (root / key).is_file() or (root / key).stat().st_size == 0:
                raise ValueError("Missing deliverable")
        if sha256(root / "tokenizer/chat_template.jinja") != cached.manifest.chat_template_sha256:
            raise ValueError("Saved tokenizer template changed")
        files = [root / "metrics.jsonl", root / "training_config.json"]
        files += sorted(path for directory in (root / "adapter", root / "tokenizer")
                        for path in directory.rglob("*") if path.is_file())
        artifacts = []
        for path in files:
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError("Unexpected artifact link")
            artifacts.append(ArtifactFile(path=path.relative_to(root).as_posix(), size_bytes=path.stat().st_size,
                                          sha256=sha256(path)))
        manifest = TrainingManifest(**snapshot(request).model_dump(), tokenizer_revision=request.model_revision,
            chat_template_sha256=cached.manifest.chat_template_sha256, train_dataset=prepared.train.summary,
            validation_dataset=prepared.validation.summary if prepared.validation else None, environment=env,
            started_at=started_at, finished_at=datetime.now(timezone.utc),
            summary=TrainingSummary(**execution, elapsed_seconds=time.monotonic() - started_clock), artifacts=artifacts)
        result = TrainResult(adapter_dir=root / "adapter", tokenizer_dir=root / "tokenizer",
                             metrics_path=root / "metrics.jsonl", config_path=root / "training_config.json",
                             manifest_path=root / "manifest.json")
        temporary = root / ".manifest.tmp"
        write_json(temporary, manifest)
        temporary.replace(result.manifest_path)
        return result
    except (OSError, ValueError, TypeError) as error:
        fail("ARTIFACT_WRITE_FAILED", "saving", "训练产物保存、引用或清单校验失败。", cause=error)
