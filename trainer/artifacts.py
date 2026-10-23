"""Read-only CPU artifact audit shared by publication, CLI and future reload."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import stat
import struct

from trainer.contracts import ArtifactFile, TrainResult, TrainingError, TrainingManifest, TrainingProgress, TrainingSnapshot
from trainer.events import fail

ADAPTER_FILES = {"adapter_config.json", "adapter_model.safetensors", "README.md"}
TOKENIZER_FILES = {"tokenizer_config.json", "tokenizer.json", "chat_template.jinja", "special_tokens_map.json",
                   "added_tokens.json", "vocab.json", "merges.txt"}
REQUIRED = {"adapter/adapter_config.json", "adapter/adapter_model.safetensors", "tokenizer/tokenizer_config.json",
            "tokenizer/tokenizer.json", "tokenizer/chat_template.jinja", "training_config.json", "metrics.jsonl"}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("Non-finite JSON number")


def read_json(path, limit=512 * 1024):
    with path.open("rb") as source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("JSON file too large")
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=_reject_constant)


def _regular(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size <= 0:
        raise ValueError("Expected a nonempty private regular file")
    return info


def _root(output_dir, outputs_root=None):
    supplied = Path(output_dir).absolute()
    if supplied.is_symlink() or not supplied.is_dir():
        raise ValueError("Task directory is missing or linked")
    root = supplied.resolve(strict=True)
    if outputs_root is not None and root.parent != Path(outputs_root).resolve(strict=True):
        raise ValueError("Task is outside configured outputs root")
    return root


def inventory(root):
    """Only deliverables; checkpoints/diagnostics never enter a downloadable inventory."""
    allowed_root = {"adapter", "tokenizer", "checkpoints", "training_config.json", "metrics.jsonl", "manifest.json"}
    for entry in root.iterdir():
        if entry.name not in allowed_root:
            raise ValueError("Unexpected file in task directory")
        if entry.name == "checkpoints" and (entry.is_symlink() or not entry.is_dir()):
            raise ValueError("Checkpoints must be an unlinked directory")
    files = [root / "training_config.json", root / "metrics.jsonl"]
    for directory, allowed in (("adapter", ADAPTER_FILES), ("tokenizer", TOKENIZER_FILES)):
        parent = root / directory
        if parent.is_symlink() or not parent.is_dir():
            raise ValueError("Artifact directory missing or linked")
        for path in sorted(parent.iterdir()):
            if path.name not in allowed:
                raise ValueError("Unexpected deliverable file")
            files.append(path)
    records = []
    for path in files:
        info = _regular(path)
        records.append(ArtifactFile(path=path.relative_to(root).as_posix(), size_bytes=info.st_size, sha256=sha256(path)))
    if not REQUIRED.issubset({item.path for item in records}):
        raise ValueError("Required deliverable missing")
    return records


def _check_adapter(root, manifest):
    config = read_json(root / "adapter/adapter_config.json")
    expected = {"base_model_name_or_path": manifest.base_model, "revision": manifest.model_revision,
                "peft_type": "LORA", "task_type": "CAUSAL_LM", "r": manifest.config.lora_r,
                "lora_alpha": manifest.config.lora_alpha, "lora_dropout": manifest.config.lora_dropout,
                "bias": "none", "inference_mode": True}
    if not isinstance(config, dict) or any(config.get(key) != value for key, value in expected.items()):
        raise ValueError("Adapter configuration differs from training snapshot")
    targets = config.get("target_modules")
    if not isinstance(targets, list) or set(targets) != set(manifest.config.target_modules):
        raise ValueError("Adapter targets differ")
    for key in ("modules_to_save", "rank_pattern", "alpha_pattern", "use_dora", "use_rslora", "use_qalora", "lora_bias"):
        if config.get(key):
            raise ValueError("Unexpected PEFT extension")
    path = root / "adapter/adapter_model.safetensors"
    if path.stat().st_size > 512 * 1024 * 1024:
        raise ValueError("Adapter exceeds CPU audit limit")
    # The Rust parser validates offsets/shapes without importing torch or numpy.
    from safetensors import deserialize
    tensors = deserialize(path.read_bytes())
    pairs, parameters = {}, 0
    for name, tensor in tensors:
        match = re.fullmatch(r"base_model\.model\.(.+)\.(lora_(?:embedding_)?)([AB])(\.weight)?", name)
        if match is None or (match[2] == "lora_") != bool(match[4]):
            raise ValueError("Unexpected tensor; only ordinary LoRA is deliverable")
        module, family, side = match[1], match[2], match[3]
        if not any(module == target or module.endswith("." + target) for target in targets):
            raise ValueError("Tensor outside configured target modules")
        shape, dtype, data = tensor["shape"], tensor["dtype"], tensor["data"]
        if len(shape) != 2 or min(shape) <= 0 or shape[0 if side == "A" else 1] != manifest.config.lora_r:
            raise ValueError("LoRA tensor rank/shape mismatch")
        if dtype not in {"F32", "F16", "BF16"}:
            raise ValueError("Unexpected Adapter dtype")
        bits, exponent = ("<I", 0x7f800000) if dtype == "F32" else ("<H", 0x7f80 if dtype == "BF16" else 0x7c00)
        if any(value & exponent == exponent for (value,) in struct.iter_unpack(bits, data)):
            raise ValueError("Non-finite Adapter tensor")
        pair = pairs.setdefault((module, family), {})
        if side in pair:
            raise ValueError("Duplicate LoRA tensor")
        pair[side] = shape
        parameters += shape[0] * shape[1]
    if not pairs or any(set(pair) != {"A", "B"} for pair in pairs.values()):
        raise ValueError("Incomplete LoRA tensor pairs")
    if parameters != manifest.summary.trainable_parameters:
        raise ValueError("Trainable parameter count differs from saved Adapter")
    if not all(any(module == target or module.endswith("." + target) for module, _ in pairs) for target in targets):
        raise ValueError("Configured target has no Adapter tensors")
    return len(tensors)


def _token_string(value):
    return value.get("content") if isinstance(value, dict) else value


def _check_tokenizer(root, manifest):
    parent = root / "tokenizer"
    config = read_json(parent / "tokenizer_config.json")
    tokenizer = read_json(parent / "tokenizer.json", 32 * 1024 * 1024)
    if config.get("tokenizer_class") not in {"Qwen2Tokenizer", "Qwen2TokenizerFast"}:
        raise ValueError("Unexpected tokenizer class")
    if config.get("name_or_path") not in (None, manifest.base_model):
        raise ValueError("Tokenizer contains private or mismatched base reference")
    model = tokenizer.get("model", {})
    vocab = model.get("vocab")
    if model.get("type") != "BPE" or not isinstance(vocab, dict) or not vocab or not isinstance(model.get("merges"), list):
        raise ValueError("Tokenizer lacks valid BPE vocabulary/merges")
    if any(type(index) is not int or index < 0 for index in vocab.values()) or len(set(vocab.values())) != len(vocab):
        raise ValueError("Invalid vocabulary IDs")
    added = tokenizer.get("added_tokens", [])
    if not isinstance(added, list) or any(not isinstance(item, dict) or not isinstance(item.get("content"), str)
            or not item["content"] or type(item.get("id")) is not int or item["id"] < 0 for item in added):
        raise ValueError("Invalid added token definitions")
    mapping = {item["content"]: item["id"] for item in added}
    if len(mapping) != len(added) or len(set(mapping.values())) != len(mapping):
        raise ValueError("Duplicate added token")
    for field in ("eos_token", "pad_token"):
        token = _token_string(config.get(field))
        if not isinstance(token, str) or token not in mapping:
            raise ValueError("Missing EOS/padding token")
        decoder = config.get("added_tokens_decoder", {}).get(str(mapping[token]))
        if _token_string(decoder) != token:
            raise ValueError("Special token ID/configuration mismatch")
    if any(_token_string(config.get("added_tokens_decoder", {}).get(str(index))) != token for token, index in mapping.items()):
        raise ValueError("Added token decoder differs from tokenizer.json")
    template = parent / "chat_template.jinja"
    if sha256(template) != manifest.chat_template_sha256:
        raise ValueError("Tokenizer template differs from manifest")
    if "chat_template" in config and config["chat_template"] != template.read_text(encoding="utf-8"):
        raise ValueError("Embedded and saved templates disagree")
    if (parent / "vocab.json").exists() and read_json(parent / "vocab.json", 32 * 1024 * 1024) != vocab:
        raise ValueError("Legacy vocabulary differs from tokenizer.json")
    if (parent / "added_tokens.json").exists() and read_json(parent / "added_tokens.json") != mapping:
        raise ValueError("Added token files disagree")
    if (parent / "merges.txt").exists():
        merges = parent / "merges.txt"
        if merges.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("Legacy merges exceed audit limit")
        lines = merges.read_text(encoding="utf-8").split("\n")
        if lines and lines[0].startswith("#version:"):
            lines = lines[1:]
        if [line for line in lines if line] != [" ".join(pair) if isinstance(pair, list) else pair for pair in model["merges"]]:
            raise ValueError("Legacy merges differ from tokenizer.json")
    if (parent / "special_tokens_map.json").exists():
        special = read_json(parent / "special_tokens_map.json")
        if any(_token_string(special.get(key)) != _token_string(config.get(key)) for key in ("eos_token", "pad_token")):
            raise ValueError("Special token files disagree")


def _check_metrics(root, manifest):
    last, last_step, epoch, recorded_at, count = {}, 0, 0.0, manifest.started_at, 0
    next_train = min(manifest.config.logging_steps, manifest.summary.total_steps)
    with (root / "metrics.jsonl").open("rb") as stream:
        while line := stream.readline(16 * 1024 + 1):
            if len(line) > 16 * 1024 or not line.endswith(b"\n") or not line.strip():
                raise ValueError("Oversized, empty or incomplete metric line")
            value = json.loads(line, object_pairs_hook=_unique, parse_constant=_reject_constant)
            event = TrainingProgress.model_validate(value)
            previous = last.get(event.kind)
            if (event.total_steps != manifest.summary.total_steps or event.step < last_step
                    or (previous is not None and event.step <= previous.step)
                    or event.epoch < epoch or not recorded_at <= event.recorded_at <= manifest.finished_at
                    or (event.kind == "eval" and ("train" not in last or last["train"].step != event.step))):
                raise ValueError("Metric sequence disagrees with completed run")
            if event.kind == "eval" and manifest.validation_dataset is None:
                raise ValueError("Eval event without validation data")
            if event.kind == "train":
                if event.step != next_train:
                    raise ValueError("Train logging window is missing or unexpected")
                if manifest.validation_dataset is not None and "train" in last:
                    if "eval" not in last or last["eval"].step != last["train"].step:
                        raise ValueError("Missing interval evaluation")
                next_train = min(event.step + manifest.config.logging_steps, manifest.summary.total_steps)
            last[event.kind], last_step, epoch, recorded_at = event, event.step, event.epoch, event.recorded_at
            count += 1
    train = last.get("train")
    if train is None or train.step != manifest.summary.completed_steps or train.loss != manifest.summary.final_loss:
        raise ValueError("Missing final train event or wrong summary Loss")
    evaluation = last.get("eval")
    if manifest.validation_dataset is not None and evaluation is None:
        raise ValueError("Missing configured final evaluation")
    if (evaluation is None) != (manifest.summary.eval_loss is None):
        raise ValueError("Eval summary does not match events")
    if evaluation is not None and (evaluation.step != train.step or evaluation.loss != manifest.summary.eval_loss):
        raise ValueError("Final eval event differs from summary")
    return count


@dataclass(frozen=True)
class VerifiedArtifacts:
    result: TrainResult
    manifest: TrainingManifest
    metric_count: int
    tensor_count: int

    def summary(self):
        return {"status": "artifacts_verified", "contract_version": self.manifest.contract_version,
                "task_id": str(self.manifest.task_id), "base_model": self.manifest.base_model,
                "model_revision": self.manifest.model_revision, "file_count": len(self.manifest.artifacts),
                "metric_count": self.metric_count, "tensor_count": self.tensor_count,
                "review_status": self.manifest.train_dataset.review_status,
                "completed_steps": self.manifest.summary.completed_steps, "reload_verified": False}


def validate_bundle(root, manifest):
    """Shared validation before publication and on subsequent read-only audits."""
    if root.name != str(manifest.task_id) or (root / "failure.json").exists() or (root / "failure.json").is_symlink():
        raise ValueError("Task identity mismatch or failure marker present")
    actual = {item.path: item for item in inventory(root)}
    if actual != {item.path: item for item in manifest.artifacts}:
        raise ValueError("Artifact inventory, sizes or hashes differ")
    config = TrainingSnapshot.model_validate(read_json(root / "training_config.json"))
    snapshot = TrainingSnapshot.model_validate({key: getattr(manifest, key) for key in TrainingSnapshot.model_fields})
    if config != snapshot:
        raise ValueError("Snapshot differs from manifest")
    tensor_count = _check_adapter(root, manifest)
    _check_tokenizer(root, manifest)
    metric_count = _check_metrics(root, manifest)
    return VerifiedArtifacts(TrainResult(adapter_dir=root / "adapter", tokenizer_dir=root / "tokenizer",
        metrics_path=root / "metrics.jsonl", config_path=root / "training_config.json", manifest_path=root / "manifest.json"),
        manifest, metric_count, tensor_count)


def verify_training_artifacts(output_dir, *, outputs_root=None, expected_task_id=None, expected_revision=None):
    try:
        root = _root(output_dir, outputs_root)
        _regular(root / "manifest.json")
        manifest = TrainingManifest.model_validate(read_json(root / "manifest.json"))
        if expected_task_id is not None and str(manifest.task_id) != str(expected_task_id):
            raise ValueError("Unexpected task ID")
        if expected_revision is not None and manifest.model_revision != expected_revision:
            raise ValueError("Unexpected model revision")
        return validate_bundle(root, manifest)
    except TrainingError:
        raise
    except Exception as error:
        fail("INVALID_ARTIFACT", "reloading", f"训练产物不完整或不一致（{type(error).__name__}）。", cause=error)
