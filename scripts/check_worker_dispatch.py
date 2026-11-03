"""Real HTTP/Redis/production Worker CPU smoke; missing isolated cache prevents GPU execution."""

import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
from uuid import uuid4

import httpx
import redis
import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.config import Settings  # noqa: E402
from backend.app.core.worker_lock import WorkerInstanceLock, WorkerLockBusy  # noqa: E402
from backend.app.main import create_app  # noqa: E402


def stop(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def reconcile(settings):
    result = subprocess.run([sys.executable, "scripts/reconcile_tasks.py", "--apply", "--services-stopped",
        "--data-dir", str(settings.data_dir), "--log-dir", str(settings.log_dir),
        "--database-url", settings.resolved_database_url], cwd=PROJECT_ROOT,
        capture_output=True, text=True, timeout=15)
    return result.returncode, json.loads(result.stdout)


async def check(root):
    executable = shutil.which("redis-server")
    if not executable:
        raise RuntimeError("This smoke requires redis-server")
    socket_path = root / "redis.sock"
    broker_process = subprocess.Popen([executable, "--port", "0", "--unixsocket", str(socket_path),
        "--unixsocketperm", "700", "--save", "", "--appendonly", "no", "--daemonize", "no"],
        cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    broker = redis.Redis(unix_socket_path=str(socket_path), socket_timeout=0.5)
    worker = None
    settings = Settings(_env_file=None, data_dir=root / "data", log_dir=root / "logs", database_url="",
        redis_url=f"redis+socket://{socket_path}?virtual_host=0", training_queue="m304-cpu-smoke",
        celery_result_backend="cache+memory://", api_prefix="/api/v1", task_publish_timeout_seconds=0.5)
    try:
        for _ in range(200):
            if broker_process.poll() is not None:
                raise RuntimeError("Private Redis exited")
            try:
                if broker.ping():
                    break
            except redis.RedisError:
                await asyncio.sleep(0.02)
        else:
            raise RuntimeError("Redis readiness timeout")
        app = create_app(settings)
        with socket.socket() as listener, (root / "worker-output.log").open("w") as output:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="on"))
            api = asyncio.create_task(server.serve(sockets=[listener]))
            try:
                for _ in range(500):
                    if server.started or api.done():
                        break
                    await asyncio.sleep(0.02)
                if not server.started:
                    raise RuntimeError("API readiness timeout")
                async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=10, trust_env=False) as client:
                    uploaded = await client.post("/api/v1/datasets", files={"file": (
                        "train.jsonl", (PROJECT_ROOT / "docs/examples/train.jsonl").read_bytes())})
                    assert uploaded.status_code == 201, uploaded.text
                    body, headers = {"dataset_id": uploaded.json()["id"]}, {"Idempotency-Key": str(uuid4())}
                    created = await client.post("/api/v1/tasks", json=body, headers=headers)
                    assert created.status_code == 202 and created.json()["status"] == "QUEUED", created.text
                    task_id = created.json()["id"]
                    envelope = broker.lindex(settings.training_queue, 0)
                    assert envelope is not None
                    environment = {**os.environ, "DATA_DIR": str(settings.data_dir), "LOG_DIR": str(settings.log_dir),
                        "DATABASE_URL": settings.resolved_database_url, "REDIS_URL": settings.redis_url,
                        "CELERY_BROKER_URL": settings.redis_url, "CELERY_BROKER_READ_URL": settings.redis_url,
                        "CELERY_BROKER_WRITE_URL": settings.redis_url,
                        "CELERY_RESULT_BACKEND": settings.celery_result_backend, "TRAINING_QUEUE": settings.training_queue,
                        "HF_HOME": str(root / "empty-hf"), "HF_HUB_CACHE": str(root / "empty-hf/hub"),
                        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "CUDA_VISIBLE_DEVICES": "",
                        "PYTHONUNBUFFERED": "1"}
                    worker = subprocess.Popen([sys.executable, "-m", "worker"], cwd=PROJECT_ROOT,
                        env=environment, stdout=output, stderr=subprocess.STDOUT)
                    for _ in range(400):
                        if worker.poll() is not None:
                            raise RuntimeError("Production Worker exited before consuming")
                        failed = (await client.get(f"/api/v1/tasks/{task_id}")).json()
                        if failed["status"] == "FAILED":
                            break
                        await asyncio.sleep(0.05)
                    else:
                        raise RuntimeError("Worker consumption timeout")
                    assert failed["error_code"] == "MODEL_NOT_CACHED", failed
                    assert failed["started_at"] and failed["finished_at"]
                    assert failed["current_step"] == 0 and failed["total_steps"] is None and failed["progress"] is None
                    assert not (settings.data_dir / "outputs" / task_id).exists()
                    assert not (settings.log_dir / "tasks" / f"{task_id}.log").exists()
                    try:
                        with WorkerInstanceLock(settings.log_dir):
                            raise AssertionError("Live production Worker did not hold its shared lock")
                    except WorkerLockBusy:
                        pass
                    # Intentionally test a false shutdown declaration against a LIVE
                    # isolated Worker: the lock must refuse before any DB modification.
                    code, blocked = await asyncio.to_thread(reconcile, settings)
                    assert code == 2 and blocked["code"] == "instance_lock_busy", blocked
                    replay = await client.post("/api/v1/tasks", json=body, headers=headers)
                    assert replay.status_code == 200 and replay.json() == failed
                    # Controlled duplicate delivery of the original real Redis envelope.
                    broker.lpush(settings.training_queue, envelope)
                    for _ in range(200):
                        if "'outcome': 'skipped'" in (root / "worker-output.log").read_text():
                            break
                        await asyncio.sleep(0.05)
                    else:
                        raise RuntimeError("Duplicate delivery was not confirmed skipped")
                    assert broker.llen(settings.training_queue) == 0
                    assert (await client.get(f"/api/v1/tasks/{task_id}")).json() == failed
            finally:
                await asyncio.to_thread(stop, worker)
                server.should_exit = True
                await api
        # Both actual services are now stopped; the same CLI can acquire the lock.
        code, current = await asyncio.to_thread(reconcile, settings)
        assert code == 0 and current["state"] == "current" and current["instance_lock_acquired"], current
        assert not (root / "empty-hf").exists()
        return {"status": "ok", "transport": "TCP HTTP + private Redis + production Worker + SQLite",
            "http_create": 202, "idempotent_replay": 200, "failure_code": "MODEL_NOT_CACHED",
            "duplicate_delivery": "skipped", "live_worker_blocks_reconciliation": True,
            "stopped_services_release_lock": True, "result_backend": "isolated memory",
            "gpu_execution_verified": False}
    finally:
        await asyncio.to_thread(stop, worker)
        broker.close()
        await asyncio.to_thread(stop, broker_process)


def main():
    with tempfile.TemporaryDirectory(prefix="llmcloud-worker-dispatch-") as directory:
        print(json.dumps(asyncio.run(check(Path(directory))), ensure_ascii=False))


if __name__ == "__main__":
    main()
