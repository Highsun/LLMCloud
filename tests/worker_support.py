"""Isolated CPU substitutes. Synthetic bundles are not model/GPU evidence."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import test_training_artifacts as artifact_support
from backend.app.core.task_contract import TaskStatus
from backend.app.core.task_protocols import TaskExecutionSpec
from trainer.artifacts import inventory, verify_training_artifacts
from trainer.contracts import DatasetSummary, RuntimeOptions, TrainingProgress, TrainingSnapshot
from trainer.lora_config import TrainingConfig

RAW = b'{"instruction":"x","output":"y"}\n'


def make_spec(data):
    dataset_id = uuid4()
    key = f"datasets/{dataset_id}/train.jsonl"
    path = data / key
    path.parent.mkdir(parents=True)
    path.write_bytes(RAW)
    return TaskExecutionSpec(task_id=uuid4(), dataset_id=dataset_id, dataset_key=key,
        dataset_sha256=hashlib.sha256(RAW).hexdigest(), dataset_size_bytes=len(RAW),
        dataset_row_count=1, base_model="Qwen/Qwen2.5-0.5B-Instruct", model_revision="b" * 40,
        config=TrainingConfig(lora_r=1, target_modules=["q_proj"]), runtime=RuntimeOptions(max_steps=2))


class MemoryRepository:
    """Small Protocol substitute with state/token protection, no SQL or file I/O."""
    def __init__(self, spec):
        self.spec = spec
        self.state = TaskStatus.QUEUED
        self.token = None
        self.claims = []
        self.events = []
        self.completions = []
        self.failures = []
        self.reads = 0

    def claim(self, task_id, claim_token, worker_id):
        self.claims.append((task_id, claim_token, worker_id))
        if self.state not in (TaskStatus.PENDING, TaskStatus.QUEUED):
            return None
        self.state, self.token = TaskStatus.RUNNING, claim_token
        return self.spec

    def record_progress(self, task_id, claim_token, event):
        if self.state != TaskStatus.RUNNING or self.token != claim_token:
            return False
        self.events.append(event)
        return True

    def complete(self, task_id, claim_token, output_key, manifest_sha256, summary):
        if self.state != TaskStatus.RUNNING or self.token != claim_token:
            return False
        self.completions.append((output_key, manifest_sha256, summary))
        self.state = TaskStatus.COMPLETED
        return True

    def fail(self, task_id, claim_token, failure):
        if self.state != TaskStatus.RUNNING or self.token != claim_token:
            return False
        self.failures.append(failure)
        self.state = TaskStatus.FAILED
        return True

    def get_status(self, task_id):
        self.reads += 1
        return self.state


def synthetic_train(request, on_progress=None):
    """Reuse the existing CPU audit fixture, created only after execution starts."""
    assert not request.output_dir.exists(), "Worker must not pre-create Trainer-owned output"
    assert not request.log_path.exists(), "Worker must not pre-create Trainer-owned log"
    support = artifact_support.TrainingArtifactTests()
    support.parent = request.output_dir.parent.parent
    with patch.object(artifact_support, "uuid4", return_value=request.task_id):
        root, manifest = support.bundle()
    # Existing M2 fixture was authored on Linux; keep its declared template bytes
    # identical on Windows without editing the teammate's fixture or audit rules.
    (root / "tokenizer/chat_template.jinja").write_bytes(b"synthetic test template\n")
    support.dump(root / "training_config.json", TrainingSnapshot(
        **{name: getattr(request, name) for name in TrainingSnapshot.model_fields}).model_dump(mode="json"))
    adapter = json.loads((root / "adapter/adapter_config.json").read_text())
    adapter.update(revision=request.model_revision, base_model_name_or_path=request.base_model,
        r=request.config.lora_r, lora_alpha=request.config.lora_alpha,
        lora_dropout=request.config.lora_dropout, target_modules=request.config.target_modules)
    support.dump(root / "adapter/adapter_config.json", adapter)
    raw = request.dataset_path.read_bytes()
    manifest = manifest.model_copy(update={"config": request.config, "base_model": request.base_model,
        "model_revision": request.model_revision, "tokenizer_revision": request.model_revision,
        "runtime": request.runtime, "artifacts": inventory(root), "train_dataset": DatasetSummary(sha256=hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw), row_count=len([line for line in raw.splitlines() if line.strip()]))})
    support.dump(root / "manifest.json", manifest.model_dump(mode="json"))
    verified = verify_training_artifacts(root)
    if on_progress:
        # The fixture has already persisted metrics, just like the real writer before callback.
        for line in verified.result.metrics_path.read_text().splitlines():
            on_progress(TrainingProgress.model_validate_json(line))
    return verified.result
