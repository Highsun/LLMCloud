"""Generate M3-01 JSON Schema/fixtures. Does not generate a runtime OpenAPI."""

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pydantic.json_schema import models_json_schema  # noqa: E402

from backend.app.core.task_contract import (  # noqa: E402
    DEFAULT_MODEL_REVISION, MAX_TASK_BODY_BYTES, TASK_CONTRACT_VERSION,
    ExecutionOutcome, PublishOutcome, TaskStatus,
)
from backend.app.core.task_protocols import TaskExecutionSpec  # noqa: E402
from backend.app.models.error_schemas import ErrorResponse  # noqa: E402
from backend.app.models.task_schemas import (  # noqa: E402
    TaskCreate, TaskDetail, TaskListQuery, TaskPage, TaskSubmissionErrorResponse,
    TaskSubmissionHeaders, TaskSummary,
)
from trainer.lora_config import TrainingConfig  # noqa: E402

MODELS = (TaskCreate, TaskListQuery, TaskSubmissionHeaders, TaskSummary,
          TaskDetail, TaskPage, ErrorResponse, TaskSubmissionErrorResponse, TaskExecutionSpec)


def build_examples() -> dict:
    # All IDs, dates, hashes, steps and errors below are isolated test fixtures.
    dataset_id = "03a853e2-1bf1-45da-92fb-5a1548499fc4"
    rows = {}
    for index, status in enumerate(TaskStatus, start=1):
        terminal = status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
        claimed = status not in (TaskStatus.PENDING, TaskStatus.QUEUED)
        known = status == TaskStatus.COMPLETED
        rows[status] = TaskDetail(
            id=f"11111111-1111-4111-8111-{index:012d}", dataset_id=dataset_id,
            base_model="Qwen/Qwen2.5-0.5B-Instruct", model_revision=DEFAULT_MODEL_REVISION,
            status=status, current_step=2 if known else 0,
            total_steps=2 if known else None, progress=1.0 if known else None,
            error_code="MODEL_NOT_CACHED" if status == TaskStatus.FAILED else None,
            error_message="指定 revision 的模型缓存不完整，请先准备模型。" if status == TaskStatus.FAILED else None,
            created_at="2026-10-24T01:00:00Z",
            started_at="2026-10-24T01:00:01Z" if claimed else None,
            finished_at="2026-10-24T01:00:04Z" if terminal else None,
            config=TrainingConfig(),
        )
    summaries = [TaskSummary.model_validate({
        name: getattr(detail, name) for name in TaskSummary.model_fields
    }) for detail in rows.values()]
    running = rows[TaskStatus.RUNNING]
    trained = TaskDetail.model_validate({**running.model_dump(), "current_step": 1,
                                        "total_steps": 2, "progress": 0.5})
    saving = TaskDetail.model_validate({**running.model_dump(), "current_step": 2,
                                       "total_steps": 2, "progress": 1.0})
    failed_training = TaskDetail.model_validate({**trained.model_dump(), "status": "FAILED",
        "finished_at": "2026-10-24T01:00:04Z", "error_code": "TRAINING_FAILED",
        "error_message": "训练执行失败，请查看任务诊断。"})
    submission_error = TaskSubmissionErrorResponse.model_validate({"error": {
        "code": "DISPATCH_UNCERTAIN", "message": "任务派发结果待确认，请查询该任务。",
        "details": [], "details_truncated": False,
        "request_id": "f63b14e1-7748-4e24-9db8-6d24810dd6df", "task_id": str(running.id),
    }})
    database_error = ErrorResponse.model_validate({"error": {
        "code": "DATABASE_UNAVAILABLE", "message": "任务存储暂时不可用。",
        "details": [], "details_truncated": False,
        "request_id": "f63b14e1-7748-4e24-9db8-6d24810dd6df",
    }})
    spec = TaskExecutionSpec(
        task_id=running.id, dataset_id=dataset_id, dataset_key=f"datasets/{dataset_id}/train.jsonl",
        dataset_sha256="a" * 64, dataset_size_bytes=200, dataset_row_count=3,
        base_model=running.base_model, model_revision=running.model_revision, config=running.config,
    )
    values = {
        "create-request.json": TaskCreate(dataset_id=dataset_id),
        "submission-headers.json": TaskSubmissionHeaders(idempotency_key="22222222-2222-4222-8222-222222222222"),
        "list-query.json": TaskListQuery(status="RUNNING"),
        "list-response.json": TaskPage(items=summaries, total=5, page=1, page_size=20, total_pages=1),
        "empty-page.json": TaskPage(items=[], total=0, page=1, page_size=20, total_pages=0),
        "beyond-last-page.json": TaskPage(items=[], total=5, page=2, page_size=20, total_pages=1),
        "detail-running-progress.json": trained,
        "detail-running-saving.json": saving,
        "detail-failed-training.json": failed_training,
        "submission-error.json": submission_error,
        "database-error.json": database_error,
        "execution-spec.json": spec,
    }
    values.update({f"detail-{status.value.lower()}.json": detail for status, detail in rows.items()})
    return {name: model.model_dump(mode="json", by_alias=True) for name, model in values.items()}


def generate_outputs() -> dict[Path, str]:
    _, schema = models_json_schema([(model, "validation") for model in MODELS])
    schema.update({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "LLMCloud task contracts (types only)",
        "x-contract-version": TASK_CONTRACT_VERSION,
        "x-implementation-status": "types_only",
        "x-generated-by": "scripts/export_task_contract.py",
        "x-max-task-body-bytes": MAX_TASK_BODY_BYTES,
        "x-publish-outcomes": [outcome.value for outcome in PublishOutcome],
        "x-execution-outcomes": [outcome.value for outcome in ExecutionOutcome],
    })
    values = {PROJECT_ROOT / "docs/contracts/tasks.schema.json": schema}
    values.update({PROJECT_ROOT / "docs/examples/tasks" / name: value
                   for name, value in build_examples().items()})
    return {path: json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
            for path, value in values.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check drift without writing")
    args = parser.parse_args()
    stale = []
    for path, expected in generate_outputs().items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != expected:
                stale.append(str(path.relative_to(PROJECT_ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8")
    if stale:
        print("Stale task contract files: " + ", ".join(stale), file=sys.stderr)
        return 1
    print("PASS: task contract is current" if args.check else "Generated task types and mock fixtures; no task routes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
