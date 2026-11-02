"""CPU-only task orchestration. SQL, transport and GPU execution are injected."""

import logging
import os
from pathlib import Path
import socket
from uuid import UUID, uuid4

from backend.app.core.task_contract import ExecutionOutcome, TaskStatus
from backend.app.core.task_protocols import TaskExecutionSpec, TaskRepository, ExecutionSettings, TrainFunction
from backend.app.services.dataset_paths import resolve_dataset_path
from trainer.artifacts import sha256, verify_training_artifacts
from trainer.contracts import TrainRequest, TrainResult, TrainingError, TrainingFailure, TrainingProgress
from trainer.dataset import scan_dataset
from trainer.lora_config import TrainingConfig
from trainer.model_cache import resolve_model_paths, verify_model_cache

logger = logging.getLogger(__name__)


class _OwnershipLost(Exception):
    pass


def parse_task_id(value) -> UUID:
    parsed = UUID(str(value))
    if parsed.version != 4 or str(parsed) != str(value):
        raise ValueError("task_id must be a canonical UUIDv4")
    return parsed


def _diagnose(stage, task_id, error):
    # Exception text/tracebacks may contain paths, credentials or training records.
    logger.warning("worker_execution stage=%s task_id=%s error_type=%s",
                   stage, task_id, type(error).__name__)


def _error(task_id, code, stage, message):
    return TrainingError(TrainingFailure(task_id=task_id, code=code, stage=stage, message=message))


def _request(spec, settings):
    data = Path(settings.data_dir).resolve()
    logs = Path(settings.log_dir).resolve()
    try:
        dataset = resolve_dataset_path(data, spec.dataset_key)
        stats = scan_dataset(dataset)
        if (stats.sha256, stats.size_bytes, stats.row_count) != (
                spec.dataset_sha256, spec.dataset_size_bytes, spec.dataset_row_count):
            raise ValueError("Dataset snapshot mismatch")
    except Exception as error:
        raise _error(spec.task_id, "INVALID_DATASET", "preflight", "训练数据不可用，或与任务快照不一致。") from error

    output = data / "outputs" / str(spec.task_id)
    log = logs / "tasks" / f"{spec.task_id}.log"
    try:
        for root, path in ((data, output), (logs, log)):
            for candidate in (path.parent, path):
                if candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
                    raise ValueError("Output/log links are forbidden")
            if not path.resolve().is_relative_to(root):
                raise ValueError("Output/log escapes configured root")
            if path.exists():
                raise ValueError("Task output/log already exists")
        paths = resolve_model_paths(data_dir=data)
        request = TrainRequest(task_id=spec.task_id, dataset_path=dataset.resolve(strict=True),
            output_dir=output, log_path=log, cache_dir=paths.cache_dir,
            base_model=spec.base_model, model_revision=spec.model_revision,
            config=TrainingConfig.model_validate(spec.config.model_dump()), runtime=spec.runtime)
    except Exception as error:
        raise _error(spec.task_id, "INVALID_REQUEST", "preflight", "任务输出、日志或配置路径无效，或已有同名文件。") from error
    # No download, no torch/HF import. The Trainer reuses this same verified cache.
    verify_model_cache(request.cache_dir, request.model_revision)
    return request


def _audit(spec, request, result):
    try:
        if not isinstance(result, TrainResult):
            raise ValueError("Trainer must return TrainResult")
        result = TrainResult.model_validate(result.model_dump())
        if result.manifest_path != request.output_dir / "manifest.json":
            raise ValueError("Unexpected output root")
        digest = sha256(result.manifest_path)
        verified = verify_training_artifacts(request.output_dir,
            outputs_root=request.output_dir.parent, expected_task_id=spec.task_id,
            expected_revision=spec.model_revision)
        manifest = verified.manifest
        if (verified.result != result or manifest.base_model != spec.base_model or
                manifest.config != spec.config or manifest.runtime != spec.runtime or
                manifest.validation_dataset is not None or
                (manifest.train_dataset.sha256, manifest.train_dataset.size_bytes, manifest.train_dataset.row_count) !=
                (spec.dataset_sha256, spec.dataset_size_bytes, spec.dataset_row_count) or
                sha256(result.manifest_path) != digest):
            raise ValueError("Artifact snapshot differs from claimed task")
        return digest, manifest.summary
    except TrainingError:
        raise
    except Exception as error:
        raise _error(spec.task_id, "INVALID_ARTIFACT", "saving", "训练产物与领取的任务快照不一致。") from error


def _record_failure(repository, task_id, token, failure):
    try:
        return (ExecutionOutcome.FAILED if repository.fail(task_id, token, failure)
                else ExecutionOutcome.OWNERSHIP_LOST)
    except Exception as error:
        _diagnose("fail_unconfirmed", task_id, error)
        return ExecutionOutcome.RECONCILIATION_REQUIRED


def execute_training(task_id: UUID, repository: TaskRepository,
                     settings: ExecutionSettings, train_fn: TrainFunction) -> ExecutionOutcome:
    """Execute once under the process instance lock held by the production entrypoint."""
    task_id = parse_task_id(task_id)
    token = uuid4()
    worker_id = f"{socket.gethostname()[:160]}:{os.getpid()}:{uuid4()}"
    try:
        claimed = repository.claim(task_id, token, worker_id)
    except Exception as error:
        _diagnose("claim_unconfirmed", task_id, error)
        return ExecutionOutcome.RECONCILIATION_REQUIRED
    if claimed is None:
        return ExecutionOutcome.SKIPPED

    ownership_lost = False

    def on_progress(event):
        nonlocal ownership_lost
        # Keep the lost flag even if Trainer wraps the callback exception.
        if ownership_lost:
            raise _OwnershipLost()
        try:
            event = TrainingProgress.model_validate(event.model_dump())
            owned = repository.record_progress(task_id, token, event)
        except Exception as error:
            raise _error(task_id, "PROGRESS_CALLBACK_FAILED", "callback", "无法确认训练进度写入。") from error
        if not owned:
            ownership_lost = True
            raise _OwnershipLost()

    try:
        # Revalidate detached mutable config; never trust a mutated DTO instance.
        try:
            spec = TaskExecutionSpec.model_validate(claimed.model_dump())
        except (ValueError, TypeError, AttributeError) as error:
            raise _error(task_id, "INVALID_REQUEST", "preflight", "领取的任务快照无效。") from error
        if spec.task_id != task_id:
            raise _error(task_id, "INVALID_REQUEST", "preflight", "领取的任务快照与任务编号不一致。")
        request = _request(spec, settings)
        result = train_fn(request, on_progress=on_progress)
        if ownership_lost:
            return ExecutionOutcome.OWNERSHIP_LOST
        digest, summary = _audit(spec, request, result)
    except Exception as error:
        if ownership_lost:
            return ExecutionOutcome.OWNERSHIP_LOST
        _diagnose("execution_failed", task_id, error)
        failure = (error.failure.model_copy(update={"task_id": task_id}) if isinstance(error, TrainingError)
                   else TrainingFailure(task_id=task_id, code="TRAINING_FAILED", stage="training",
                                        message="任务执行失败，请根据任务编号检查 Worker 诊断。"))
        return _record_failure(repository, task_id, token, failure)

    # Valid artifacts now exist. Never route a completion error through fail().
    try:
        completed = repository.complete(task_id, token, f"outputs/{task_id}", digest, summary)
        return ExecutionOutcome.COMPLETED if completed else ExecutionOutcome.OWNERSHIP_LOST
    except Exception as error:
        _diagnose("completion_unconfirmed", task_id, error)
        try:
            if repository.get_status(task_id) == TaskStatus.COMPLETED:
                return ExecutionOutcome.COMPLETED
        except Exception as read_error:
            _diagnose("completion_read_failed", task_id, read_error)
        return ExecutionOutcome.RECONCILIATION_REQUIRED
