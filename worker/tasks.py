from worker.celery_app import celery_app


@celery_app.task(name="worker.ping")
def ping() -> dict[str, str]:
    """Broker/worker connectivity diagnostic; does not touch the GPU."""
    return {"status": "ok", "service": "llmcloud-worker"}


@celery_app.task(name="worker.train")
def run_training(task_id: str) -> dict[str, str]:
    """M3 will load the SQL task, claim it once and invoke trainer.train."""
    raise NotImplementedError(
        f"任务 {task_id}：异步训练尚未实现；初始化阶段请仅使用 worker.ping 检查连通性。"
    )
