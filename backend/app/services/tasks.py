"""Task HTTP use cases; database commits precede a single Publisher attempt."""

from dataclasses import dataclass
import logging

from backend.app.core.task_contract import PublishOutcome, TaskStatus
from backend.app.core.task_protocols import TaskStoreError
from backend.app.core.request_context import RequestLogger
from backend.app.models.error_schemas import ApiErrorCode
from backend.app.models.task_schemas import TaskDetail
from backend.app.services.errors import DatasetServiceError
from backend.app.services.task_repository import IdempotencyConflict, TaskDatasetNotFound
from trainer.contracts import RuntimeOptions

logger = RequestLogger(logging.getLogger(__name__), {})


class TaskServiceError(DatasetServiceError):
    """Extends the existing transport-neutral error fields for persisted tasks."""

    def __init__(self, code, message, status_code, *, task_id=None):
        super().__init__(code, message, status_code)
        self.task_id = task_id


@dataclass(frozen=True)
class TaskSubmission:
    task: TaskDetail
    replayed: bool


def database_error():
    return TaskServiceError(ApiErrorCode.DATABASE_UNAVAILABLE, "任务存储暂时不可用，请稍后查询。", 503)


class TaskService:
    def __init__(self, settings, repository, publisher):
        self.settings, self.repository, self.publisher = settings, repository, publisher

    def _uncertain(self, task_id):
        try:
            self.repository.mark_dispatch_uncertain(task_id)
        except TaskStoreError:
            logger.error("task_dispatch_diagnostic_failed task_id=%s", task_id)
        return TaskServiceError(ApiErrorCode.DISPATCH_UNCERTAIN,
            "任务派发结果待确认，请查询该任务。", 503, task_id=task_id)

    def create(self, request, idempotency_key=None):
        try:
            created = self.repository.create(request,
                model_revision=self.settings.default_model_revision,
                runtime=RuntimeOptions(precision=self.settings.training_precision,
                    max_steps=self.settings.training_max_steps, local_files_only=True),
                idempotency_key=idempotency_key)
        except TaskDatasetNotFound:
            raise TaskServiceError(ApiErrorCode.DATASET_NOT_FOUND, "数据集不存在。", 404) from None
        except IdempotencyConflict:
            raise TaskServiceError(ApiErrorCode.IDEMPOTENCY_CONFLICT, "去重键已用于不同的任务请求。", 409) from None
        except TaskStoreError:
            raise database_error() from None
        if not created.created:
            return TaskSubmission(created.task, True)
        task_id = created.task.id
        try:
            outcome = PublishOutcome(self.publisher.publish(task_id, created.celery_task_id))
        except Exception as error:
            # A Publisher failure after its entry cannot prove that no message was sent.
            logger.error("task_publish_unexpected task_id=%s reason=%s", task_id, type(error).__name__)
            outcome = PublishOutcome.UNKNOWN
        if outcome == PublishOutcome.UNKNOWN:
            raise self._uncertain(task_id)
        try:
            if outcome == PublishOutcome.NOT_SENT:
                changed = self.repository.mark_dispatch_failed(task_id)
                task = self.repository.get_detail(task_id)
                if changed and task is not None and task.status == TaskStatus.FAILED and task.error_code == "DISPATCH_FAILED":
                    raise TaskServiceError(ApiErrorCode.DISPATCH_FAILED,
                        "任务未能派发，请查询该任务。", 503, task_id=task_id)
                raise self._uncertain(task_id)
            self.repository.mark_queued(task_id)
            task = self.repository.get_detail(task_id)
            if task is None:
                raise self._uncertain(task_id)
            return TaskSubmission(task, False)
        except TaskStoreError:
            raise self._uncertain(task_id) from None

    def list(self, query):
        try:
            return self.repository.list(query)
        except TaskStoreError:
            raise database_error() from None

    def get(self, task_id):
        try:
            task = self.repository.get_detail(task_id)
        except TaskStoreError:
            raise database_error() from None
        if task is None:
            raise TaskServiceError(ApiErrorCode.TASK_NOT_FOUND, "训练任务不存在。", 404)
        return task
