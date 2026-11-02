from backend.app.core.config import get_settings
from worker.celery_app import celery_app
from worker.instance_lock import acquire_worker_lock, release_worker_lock


def main():
    try:
        acquire_worker_lock(get_settings().log_dir)
    except Exception:
        raise SystemExit("Worker 启动被拒绝：无法取得独占实例锁。") from None
    try:
        return celery_app.worker_main([
            "worker", "--loglevel=info", "--pool=solo", "--concurrency=1",
            f"--queues={get_settings().training_queue},celery",
        ])
    finally:
        release_worker_lock()

if __name__ == "__main__":
    main()
