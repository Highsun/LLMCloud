from worker.celery_app import celery_app
from worker.execution import execute_training, parse_task_id
from worker.instance_lock import acquire_worker_lock


@celery_app.task(name="worker.ping")
def ping() -> dict[str, str]:
    """Broker/worker connectivity diagnostic; does not touch the GPU."""
    return {"status": "ok", "service": "llmcloud-worker"}


@celery_app.task(name="worker.train", acks_late=False, reject_on_worker_lost=False, max_retries=0)
def run_training(task_id: str) -> dict[str, str]:
    """Only a task ID crosses the queue; no ORM object or file path is accepted."""
    parsed = parse_task_id(task_id)
    from backend.app.core.config import get_settings
    from backend.app.core.database import SessionLocal
    from backend.app.services.task_repository import SqlTaskRepository
    from trainer.train import train

    settings = get_settings()
    # Also protects trusted direct/eager invocation; regular Worker startup holds it already.
    acquire_worker_lock(settings.log_dir)
    outcome = execute_training(parsed, SqlTaskRepository(SessionLocal), settings, train)
    return {"task_id": str(parsed), "outcome": outcome.value}


@celery_app.task(name="worker.infer", acks_late=False, reject_on_worker_lost=False,
                 max_retries=0, ignore_result=True)
def run_inference(inference_id: str) -> None:
    job_id = str(parse_task_id(inference_id))
    from backend.app.core.config import get_settings
    from backend.app.core.database import SessionLocal
    from backend.app.services.inference_repository import InferenceRepository
    from worker.inference import execute_inference

    settings = get_settings()
    acquire_worker_lock(settings.log_dir)
    execute_inference(job_id, InferenceRepository(SessionLocal), settings)
