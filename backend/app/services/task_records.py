"""SQL-independent record checks shared by task persistence and explicit migration."""

from datetime import datetime
import hashlib
import json

from pydantic import TypeAdapter, UUID4

from backend.app.core.task_contract import TaskStatus
from backend.app.core.task_protocols import TaskExecutionSpec
from backend.app.models.task_schemas import TaskCreate, TaskDetail
from trainer.contracts import Sha256, TrainingSummary


def identifier(value) -> str:
    result = str(TypeAdapter(UUID4).validate_python(value))
    if isinstance(value, str) and value != result:
        raise ValueError("Expected canonical UUIDv4")
    return result


def request_sha256(request: TaskCreate) -> str:
    request = TaskCreate.model_validate(request.model_dump())
    raw = json.dumps(request.model_dump(mode="json"), sort_keys=True, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def execution_spec(row) -> TaskExecutionSpec:
    return TaskExecutionSpec(task_id=row["id"], dataset_id=row["dataset_id"],
        dataset_key=row["dataset_key"], dataset_sha256=row["dataset_sha256"],
        dataset_size_bytes=row["dataset_size_bytes"], dataset_row_count=row["dataset_row_count"],
        base_model=row["base_model"], model_revision=row["model_revision"],
        config=row["training_config"], runtime=row["runtime_options"])


def task_detail(row) -> TaskDetail:
    spec = execution_spec(row)
    identifier(row["id"])
    identifier(row["dataset_id"])
    identifier(row["celery_task_id"])
    claim, worker = row["claim_token"], row["worker_id"]
    if (claim is None) != (worker is None):
        raise ValueError("Incomplete claim")
    if claim is not None:
        identifier(claim)
        if not isinstance(worker, str) or not worker.strip() or len(worker) > 255 or not worker.isprintable():
            raise ValueError("Invalid worker identity")
    key, digest = row["idempotency_key"], row["request_sha256"]
    if (key is None) != (digest is None):
        raise ValueError("Incomplete request identity")
    if key is not None:
        identifier(key)
        TypeAdapter(Sha256).validate_python(digest)
        if digest != request_sha256(TaskCreate(dataset_id=spec.dataset_id, base_model=spec.base_model, config=spec.config)):
            raise ValueError("Request hash differs from snapshot")
    known = row["total_steps"] != 0
    if not known and (row["current_step"] != 0 or row["progress"] != 0):
        raise ValueError("Unknown steps contain fabricated progress")
    times = {}
    for name in ("created_at", "started_at", "finished_at"):
        value = row[name]
        times[name] = datetime.fromisoformat(value) if isinstance(value, str) else value
    detail = TaskDetail(id=row["id"], dataset_id=spec.dataset_id, base_model=spec.base_model,
        model_revision=spec.model_revision, config=spec.config, status=row["status"],
        current_step=row["current_step"], total_steps=row["total_steps"] if known else None,
        progress=row["progress"] if known else None, error_code=row["error_code"],
        error_message=row["error_message"], **times)
    if detail.status == TaskStatus.RUNNING and claim is None:
        raise ValueError("Running task has no owner")
    if detail.status in (TaskStatus.PENDING, TaskStatus.QUEUED) and claim is not None:
        raise ValueError("Unclaimed task has an owner")
    if detail.status == TaskStatus.COMPLETED:
        if row["output_path"] != f"outputs/{detail.id}":
            raise ValueError("Unexpected output key")
        TypeAdapter(Sha256).validate_python(row["manifest_sha256"])
        summary = TrainingSummary.model_validate(row["training_summary"])
        if summary.total_steps != detail.total_steps:
            raise ValueError("Completion summary differs from progress")
        if spec.runtime.max_steps is not None and summary.total_steps != spec.runtime.max_steps:
            raise ValueError("Completion summary differs from runtime")
    elif any(row[name] is not None for name in ("output_path", "manifest_sha256", "training_summary")):
        raise ValueError("Unfinished task has published outputs")
    return detail
