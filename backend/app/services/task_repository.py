"""Short SQL transactions for task state; never imports Celery or opens artifacts."""

from contextlib import contextmanager
from dataclasses import dataclass
import logging
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import func, select

from backend.app.core.task_contract import TaskStatus
from backend.app.core.observability_protocols import (
    CompletedArtifactSpec, CompletedArtifactNotFound, CompletedArtifactNotReady,
)
from backend.app.core.task_protocols import TaskStoreError
from backend.app.models.entities import Dataset, TrainingTask, utcnow
from backend.app.models.task_schemas import TaskCreate, TaskDetail, TaskListQuery, TaskPage, TaskSummary
from backend.app.services.task_records import execution_spec, identifier, request_sha256, task_detail
from trainer.contracts import Revision, RuntimeOptions, Sha256, TrainingFailure, TrainingProgress, TrainingSummary

logger = logging.getLogger(__name__)
TABLE = TrainingTask.__table__


class TaskDatasetNotFound(Exception):
    pass


class IdempotencyConflict(Exception):
    pass


@dataclass(frozen=True)
class TaskCreation:
    task: TaskDetail
    created: bool
    celery_task_id: UUID


class SqlTaskRepository:
    def __init__(self, sessions):
        self.sessions = sessions

    @contextmanager
    def _session(self, *, write=False):
        try:
            with self.sessions() as session:
                with session.begin():
                    if session.get_bind().dialect.name == "sqlite":
                        # SQLite's legacy driver does not BEGIN on SELECT. Explicit
                        # transactions give count/page consistency and serialize writers.
                        session.connection().exec_driver_sql("BEGIN IMMEDIATE" if write else "BEGIN")
                    yield session
        except (TaskDatasetNotFound, IdempotencyConflict):
            raise
        except Exception as error:
            logger.error("task_store_failed reason=%s", type(error).__name__)
            raise TaskStoreError() from None

    def _row(self, session, task_id):
        row = session.execute(select(TABLE).where(TABLE.c.id == identifier(task_id))).mappings().one_or_none()
        if row is not None:
            task_detail(row)  # Corruption is an error, never a normal skip.
        return row

    def _update(self, session, row, values, *conditions):
        task_detail({**row, **values})
        return session.execute(TABLE.update().where(TABLE.c.id == row["id"], *conditions).values(**values)).rowcount == 1

    def create(self, request: TaskCreate, *, model_revision: str, runtime: RuntimeOptions,
               idempotency_key=None) -> TaskCreation:
        with self._session(write=True) as session:
            request = TaskCreate.model_validate(request.model_dump())
            key = None if idempotency_key is None else identifier(idempotency_key)
            digest = request_sha256(request)
            if key is not None:
                prior = session.execute(select(TABLE).where(TABLE.c.idempotency_key == key)).mappings().one_or_none()
                if prior is not None:
                    detail = task_detail(prior)
                    if prior["request_sha256"] != digest:
                        raise IdempotencyConflict("去重键已用于不同的任务请求。")
                    return TaskCreation(detail, False, UUID(prior["celery_task_id"]))
            dataset = session.get(Dataset, str(request.dataset_id))
            if dataset is None:
                raise TaskDatasetNotFound("数据集不存在。")
            runtime = RuntimeOptions.model_validate(runtime.model_dump())
            revision = TypeAdapter(Revision).validate_python(model_revision)
            row = dict(id=str(uuid4()), dataset_id=str(request.dataset_id), base_model=request.base_model,
                status=TaskStatus.PENDING, training_config=request.config.model_dump(mode="json"),
                model_revision=revision, dataset_key=dataset.storage_path, dataset_sha256=dataset.sha256,
                dataset_size_bytes=dataset.size_bytes, dataset_row_count=dataset.row_count,
                runtime_options=runtime.model_dump(mode="json"), claim_token=None, worker_id=None,
                error_code=None, error_message=None, idempotency_key=key, request_sha256=digest if key else None,
                celery_task_id=str(uuid4()), current_step=0, total_steps=0, progress=0.0,
                output_path=None, manifest_sha256=None, training_summary=None,
                created_at=utcnow(), started_at=None, finished_at=None)
            detail = task_detail(row)
            session.execute(TABLE.insert().values(**row))
            return TaskCreation(detail, True, UUID(row["celery_task_id"]))

    def get_status(self, task_id):
        with self._session() as session:
            row = self._row(session, task_id)
            return None if row is None else TaskStatus(row["status"])

    def get_detail(self, task_id):
        with self._session() as session:
            row = self._row(session, task_id)
            return None if row is None else task_detail(row)

    def get_completed_artifact(self, task_id):
        with self._session() as session:
            row = self._row(session, task_id)
            if row is not None and row["status"] == TaskStatus.COMPLETED:
                return CompletedArtifactSpec(spec=execution_spec(row), output_key=row["output_path"],
                    manifest_sha256=row["manifest_sha256"], training_summary=row["training_summary"])
        # Business outcomes must escape outside _session's storage-error wrapper.
        if row is None:
            raise CompletedArtifactNotFound()
        raise CompletedArtifactNotReady()

    def list(self, query: TaskListQuery | None = None) -> TaskPage:
        with self._session() as session:
            query = TaskListQuery.model_validate((query or TaskListQuery()).model_dump())
            conditions = [] if query.status is None else [TABLE.c.status == query.status]
            total = session.scalar(select(func.count()).select_from(TABLE).where(*conditions))
            offset = (query.page - 1) * query.page_size
            # Beyond-last pages are valid even when their number exceeds SQLite's integer range.
            rows = [] if offset >= total else session.execute(select(TABLE).where(*conditions)
                .order_by(TABLE.c.created_at.desc(), TABLE.c.id.desc())
                .offset(offset).limit(query.page_size)).mappings()
            items = [TaskSummary.model_validate(task_detail(row).model_dump(exclude={"config"})) for row in rows]
            return TaskPage(items=items, total=total, page=query.page, page_size=query.page_size,
                            total_pages=(total + query.page_size - 1) // query.page_size)

    def mark_queued(self, task_id):
        with self._session(write=True) as session:
            row = self._row(session, task_id)
            if row is None or row["status"] != TaskStatus.PENDING:
                return False
            return self._update(session, row, dict(status=TaskStatus.QUEUED, error_code=None, error_message=None),
                                TABLE.c.status == TaskStatus.PENDING)

    def mark_dispatch_failed(self, task_id):
        with self._session(write=True) as session:
            row = self._row(session, task_id)
            if row is None or row["status"] != TaskStatus.PENDING:
                return False
            return self._update(session, row, dict(status=TaskStatus.FAILED, error_code="DISPATCH_FAILED",
                error_message="任务未能派发，请查询该任务。", finished_at=utcnow()), TABLE.c.status == TaskStatus.PENDING)

    def mark_dispatch_uncertain(self, task_id):
        with self._session(write=True) as session:
            row = self._row(session, task_id)
            if row is None or row["status"] not in (TaskStatus.PENDING, TaskStatus.QUEUED):
                return False
            return self._update(session, row, dict(error_code="DISPATCH_UNCERTAIN",
                error_message="任务派发结果待确认，请查询该任务。"),
                TABLE.c.status.in_([TaskStatus.PENDING, TaskStatus.QUEUED]))

    def claim(self, task_id, claim_token, worker_id):
        with self._session(write=True) as session:
            token = identifier(claim_token)
            if not isinstance(worker_id, str) or not worker_id.strip() or len(worker_id) > 255 or not worker_id.isprintable():
                raise ValueError("Invalid worker identity")
            row = self._row(session, task_id)
            if row is None or row["status"] not in (TaskStatus.PENDING, TaskStatus.QUEUED):
                return None
            updated = self._update(session, row, dict(status=TaskStatus.RUNNING, claim_token=token,
                worker_id=worker_id, started_at=utcnow(), error_code=None, error_message=None),
                TABLE.c.status.in_([TaskStatus.PENDING, TaskStatus.QUEUED]))
            return execution_spec(row) if updated else None

    def _owned(self, session, task_id, token):
        row = self._row(session, task_id)
        return row if row is not None and row["status"] == TaskStatus.RUNNING and row["claim_token"] == token else None

    @staticmethod
    def _owner_conditions(token):
        return TABLE.c.status == TaskStatus.RUNNING, TABLE.c.claim_token == token

    def record_progress(self, task_id, claim_token, event):
        with self._session(write=True) as session:
            token = identifier(claim_token)
            event = TrainingProgress.model_validate(event.model_dump())
            row = self._owned(session, task_id, token)
            if row is None:
                return False
            if row["total_steps"] not in (0, event.total_steps):
                raise ValueError("Total steps changed")
            limit = execution_spec(row).runtime.max_steps
            if limit is not None and limit != event.total_steps:
                raise ValueError("Total steps differ from runtime")
            if event.kind == "eval" or event.step <= row["current_step"]:
                return True
            return self._update(session, row, dict(current_step=event.step, total_steps=event.total_steps,
                progress=event.step / event.total_steps), *self._owner_conditions(token))

    def complete(self, task_id, claim_token, output_key, manifest_sha256, summary):
        with self._session(write=True) as session:
            token = identifier(claim_token)
            if output_key != f"outputs/{identifier(task_id)}":
                raise ValueError("Unexpected output key")
            digest = TypeAdapter(Sha256).validate_python(manifest_sha256)
            summary = TrainingSummary.model_validate(summary.model_dump())
            row = self._owned(session, task_id, token)
            if row is None:
                return False
            if row["total_steps"] not in (0, summary.total_steps) or row["current_step"] > summary.completed_steps:
                raise ValueError("Completion differs from progress")
            return self._update(session, row, dict(status=TaskStatus.COMPLETED, progress=1.0,
                current_step=summary.completed_steps, total_steps=summary.total_steps, output_path=output_key,
                manifest_sha256=digest, training_summary=summary.model_dump(mode="json"),
                error_code=None, error_message=None, finished_at=utcnow()), *self._owner_conditions(token))

    def fail(self, task_id, claim_token, failure):
        with self._session(write=True) as session:
            token = identifier(claim_token)
            failure = TrainingFailure.model_validate(failure.model_dump())
            if failure.task_id is not None and identifier(failure.task_id) != identifier(task_id):
                raise ValueError("Failure belongs to another task")
            row = self._owned(session, task_id, token)
            if row is None:
                return False
            return self._update(session, row, dict(status=TaskStatus.FAILED, error_code=failure.code,
                error_message=failure.message, finished_at=utcnow()), *self._owner_conditions(token))
