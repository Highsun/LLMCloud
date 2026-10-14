"""Keep one worker process per GPU; start with scripts/start_worker.sh."""

import os
from pathlib import Path

from celery import Celery
from dotenv import load_dotenv

from backend.app.core.config import PROJECT_ROOT, get_settings

# Settings reads application fields; export CUDA/HF fields for downstream libraries.
load_dotenv(PROJECT_ROOT / ".env", override=False)
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
hf_home = Path(os.environ.get("HF_HOME", "data/models/huggingface")).expanduser()
os.environ["HF_HOME"] = str(hf_home if hf_home.is_absolute() else PROJECT_ROOT / hf_home)

settings = get_settings()
celery_app = Celery(
    "llmcloud",
    broker=settings.redis_url,
    backend=settings.celery_result_backend,
    include=["worker.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    result_expires=86400,
    task_routes={"worker.train": {"queue": settings.training_queue}},
)
