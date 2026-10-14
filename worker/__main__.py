from backend.app.core.config import get_settings
from worker.celery_app import celery_app

if __name__ == "__main__":
    celery_app.worker_main([
        "worker", "--loglevel=info", "--pool=solo", "--concurrency=1",
        f"--queues={get_settings().training_queue},celery",
    ])
