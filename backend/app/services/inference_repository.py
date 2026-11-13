"""SQLite admission, ownership and expiry for one serial GPU worker."""

from time import time

from pydantic import ValidationError
from sqlalchemy import delete, select, update

from backend.app.core.task_contract import TaskStatus
from backend.app.models.entities import InferenceJob, TrainingTask
from backend.app.models.inference_schemas import (
    INFERENCE_RETENTION_SECONDS, InferenceErrorCode, InferenceRequest,
)
from backend.app.services.task_repository import SqlTaskRepository

WAITING = "WAITING"
RUNNING = "RUNNING"
FINISHED = "FINISHED"


def _finish_job(job, *, error=None, result=None):
    job.state = FINISHED
    job.request = None
    job.result = result
    job.error_code = error
    job.delete_at = time() + INFERENCE_RETENTION_SECONDS


def yield_waiting_inference(session):
    """Called inside the same write transaction that claims a training task."""
    now = time()
    _expire_waiting(session, now)
    session.execute(update(InferenceJob).where(InferenceJob.state == WAITING).values(
        state=FINISHED, request=None, error_code=InferenceErrorCode.GPU_BUSY,
        delete_at=now + INFERENCE_RETENTION_SECONDS))


def _expire_waiting(session, now):
    session.execute(update(InferenceJob).where(
        InferenceJob.state == WAITING, InferenceJob.claim_by <= now,
    ).values(state=FINISHED, request=None, error_code=InferenceErrorCode.INFERENCE_UNAVAILABLE,
             delete_at=now + INFERENCE_RETENTION_SECONDS))


def _training_waiting_or_running(session):
    return session.scalar(select(TrainingTask.id).where(
        TrainingTask.status.in_((TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING))
    ).limit(1)) is not None


class InferenceRepository(SqlTaskRepository):
    def reserve(self, job_id, body, claim_by, finish_by):
        """Return a public error code when admission is denied."""
        with self._session(write=True) as session:
            task = self._row(session, body.task_id)
            if task is None:
                return "TASK_NOT_FOUND"
            if task["status"] != TaskStatus.COMPLETED:
                return "ARTIFACT_NOT_READY"
            now = time()
            self._prune(session, now)
            if now >= claim_by:
                return InferenceErrorCode.INFERENCE_UNAVAILABLE
            if (_training_waiting_or_running(session) or session.scalar(select(InferenceJob.id).where(
                InferenceJob.state.in_((WAITING, RUNNING))
            ).limit(1)) is not None):
                return InferenceErrorCode.GPU_BUSY
            session.add(InferenceJob(id=job_id, task_id=str(body.task_id), state=WAITING,
                request=body.model_dump(mode="json"), claim_by=claim_by, finish_by=finish_by))
            return None

    def claim_inference(self, job_id):
        with self._session(write=True) as session:
            job = session.get(InferenceJob, job_id)
            if job is None or job.state != WAITING:
                return None
            if time() >= job.claim_by:
                _finish_job(job, error=InferenceErrorCode.INFERENCE_UNAVAILABLE)
                return None
            if _training_waiting_or_running(session):
                _finish_job(job, error=InferenceErrorCode.GPU_BUSY)
                return None
            try:
                body = InferenceRequest.model_validate(job.request)
            except ValidationError:
                _finish_job(job, error=InferenceErrorCode.INFERENCE_FAILED)
                return None
            if str(body.task_id) != job.task_id:
                _finish_job(job, error=InferenceErrorCode.INFERENCE_FAILED)
                return None
            job.state = RUNNING
            job.request = None
            return body, job.finish_by

    def get_inference(self, job_id):
        with self._session() as session:
            job = session.get(InferenceJob, job_id)
            return (job.state, job.error_code, job.result) if job is not None else None

    def stop_waiting(self, job_id):
        """Atomically end a reservation; a claimed job stays occupied."""
        with self._session(write=True) as session:
            job = session.get(InferenceJob, job_id)
            if job is not None and job.state == WAITING:
                _finish_job(job, error=InferenceErrorCode.INFERENCE_UNAVAILABLE)
                return True
            return False

    def cancel_inference(self, job_id):
        with self._session(write=True) as session:
            job = session.get(InferenceJob, job_id)
            if job is not None and job.state == WAITING:
                _finish_job(job, error=InferenceErrorCode.INFERENCE_UNAVAILABLE)
            elif job is not None and job.state == RUNNING:
                job.cancelled = True
            elif job is not None:
                session.delete(job)

    def inference_cancelled(self, job_id):
        with self._session() as session:
            job = session.get(InferenceJob, job_id)
            return job is None or job.state != RUNNING or job.cancelled

    def complete_inference(self, job_id, *, error=None, result=None):
        with self._session(write=True) as session:
            job = session.get(InferenceJob, job_id)
            if job is not None and job.state == RUNNING:
                if job.cancelled:
                    session.delete(job)
                    return
                if time() >= job.finish_by:
                    error, result = InferenceErrorCode.INFERENCE_TIMEOUT, None
                _finish_job(job, error=error, result=result)

    @staticmethod
    def _prune(session, now):
        _expire_waiting(session, now)
        session.execute(delete(InferenceJob).where(
            InferenceJob.state == FINISHED, InferenceJob.delete_at <= now))

    def prune_inference(self):
        with self._session(write=True) as session:
            self._prune(session, time())

    def recover_inference(self):
        """The caller owns the process lock, so no previous job can still run."""
        with self._session(write=True) as session:
            self._prune(session, time())
            for job in session.scalars(select(InferenceJob).where(InferenceJob.state == RUNNING)):
                _finish_job(job, error=InferenceErrorCode.INFERENCE_FAILED)
