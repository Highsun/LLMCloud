"""Keep one worker process per GPU; start with scripts/start_worker.sh."""

import os
from pathlib import Path

from celery import Celery
from celery.concurrency.solo import TaskPool
from celery.concurrency import get_implementation
from celery.signals import worker_init, worker_shutdown
from dotenv import load_dotenv

from backend.app.core.config import PROJECT_ROOT, get_settings
from worker.instance_lock import acquire_worker_lock, release_worker_lock

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
    worker_pool="solo",
    worker_concurrency=1,
    task_acks_late=False,
    task_reject_on_worker_lost=False,
    result_expires=86400,
    task_routes={
        "worker.train": {"queue": settings.training_queue},
        "worker.infer": {"queue": settings.training_queue},
    },
)


@worker_init.connect(weak=False)
def guard_worker_instance(sender=None, **_):
    """SystemExit is deliberate: Celery signals swallow ordinary Exceptions."""
    try:
        # worker_init runs before Celery resolves the string alias into its class.
        pool = get_implementation(getattr(sender, "pool_cls", None))
        if (not isinstance(pool, type) or not issubclass(pool, TaskPool)
                or getattr(sender, "concurrency", None) != 1
                or getattr(sender, "prefetch_multiplier", None) != 1):
            raise ValueError("Worker 必须使用 solo、concurrency=1、prefetch_multiplier=1。")
        acquire_worker_lock(get_settings().log_dir)
    except Exception:
        # No raw Settings, broker credentials or file paths in the error.
        raise SystemExit("Worker 启动被拒绝：实例锁不可用或并发配置不符合单 GPU 约定。") from None
    if getattr(sender, "app", None) is celery_app:
        try:
            from backend.app.core.database import SessionLocal, init_db
            from backend.app.services.inference_repository import InferenceRepository

            settings.ensure_directories()
            init_db()
            InferenceRepository(SessionLocal).recover_inference()
        except Exception:
            release_worker_lock()
            raise SystemExit("Worker 启动被拒绝：无法初始化或恢复推理状态。") from None


@worker_shutdown.connect(weak=False)
def release_worker_instance(**_):
    release_worker_lock()
