"""Run configuration and publication after the shared CPU artifact audit."""

from datetime import datetime, timezone
from importlib.metadata import version
import os
from pathlib import Path
import subprocess
import platform
import time
from uuid import uuid4

from pydantic import ValidationError

from trainer.contracts import RunEnvironment, TrainRequest, TrainingManifest, TrainingSnapshot, TrainingSummary
from trainer.artifacts import inventory, sha256, validate_bundle
from trainer.events import fail
from trainer.model_cache import PROJECT_ROOT


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
    """Audit the real bundle, then atomically publish without replacing another marker."""
    root = request.output_dir
    try:
        if (root / "manifest.json").exists() or (root / "manifest.json").is_symlink():
            raise ValueError("Success marker already exists")
        manifest = TrainingManifest(**snapshot(request).model_dump(), tokenizer_revision=request.model_revision,
            chat_template_sha256=cached.manifest.chat_template_sha256, train_dataset=prepared.train.summary,
            validation_dataset=prepared.validation.summary if prepared.validation else None, environment=env,
            started_at=started_at, finished_at=datetime.now(timezone.utc),
            summary=TrainingSummary(**execution, elapsed_seconds=time.monotonic() - started_clock), artifacts=inventory(root))
        verified = validate_bundle(root, manifest)
        # Audit time belongs to the run duration; model/metric content is unchanged.
        manifest = manifest.model_copy(update={"finished_at": datetime.now(timezone.utc),
            "summary": manifest.summary.model_copy(update={"elapsed_seconds": time.monotonic() - started_clock})})
        publish_manifest(root, manifest)
        return verified.result
    except Exception as error:
        fail("ARTIFACT_WRITE_FAILED", "saving", "训练产物保存、引用或清单校验失败。", cause=error)


def publish_manifest(root, manifest):
    """A same-filesystem hard link is an atomic, exclusive commit on local WSL/Linux."""
    temporary = root / f".manifest.{uuid4().hex}.tmp"
    marker = root / "manifest.json"
    created = False
    preserve_temporary = False
    try:
        write_json(temporary, manifest)
        os.link(temporary, marker)  # fails if marker exists; never replaces foreign data
        created = True
        temporary.unlink()
    except BaseException:
        if created:
            try:
                marker.unlink()
            except OSError:
                # Retain both links: the read-only auditor rejects a multi-link
                # marker, so a failed cleanup cannot become a valid success.
                preserve_temporary = True
        raise
    finally:
        if not preserve_temporary:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass  # Never mask the primary write/publication failure.
