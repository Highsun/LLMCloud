"""Real TCP/HTTP + private Redis dispatch smoke. Starts no Worker or GPU."""

import asyncio
import base64
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
from uuid import uuid4

import httpx
import redis
import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.config import Settings  # noqa: E402
from backend.app.core.task_contract import MAX_TASK_BODY_BYTES  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.models.error_schemas import ErrorResponse  # noqa: E402
from backend.app.models.task_schemas import TaskDetail, TaskPage, TaskSubmissionErrorResponse  # noqa: E402


async def check(root):
    executable = shutil.which("redis-server")
    if not executable:
        raise RuntimeError("This real dispatch check requires redis-server")
    socket_path = root / "redis.sock"
    process = subprocess.Popen([executable, "--port", "0", "--unixsocket", str(socket_path),
        "--unixsocketperm", "700", "--save", "", "--appendonly", "no", "--daemonize", "no"],
        cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    broker = redis.Redis(unix_socket_path=str(socket_path), socket_timeout=0.3)
    try:
        for _ in range(200):
            if process.poll() is not None:
                raise RuntimeError("Private Redis failed to start")
            try:
                if broker.ping(): break
            except redis.RedisError:
                await asyncio.sleep(0.01)
        else:
            raise RuntimeError("Private Redis readiness timeout")
        settings = Settings(_env_file=None, data_dir=root / "data", log_dir=root / "logs", database_url="",
            redis_url=f"redis+socket://{socket_path}?virtual_host=0", training_queue="m3-isolated-check",
            task_publish_timeout_seconds=0.3, api_prefix="/api/v1")
        app = create_app(settings)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="on"))
            task = asyncio.create_task(server.serve(sockets=[listener]))
            try:
                for _ in range(500):
                    if server.started or task.done(): break
                    await asyncio.sleep(0.01)
                if not server.started:
                    raise RuntimeError("Temporary API failed to start")
                async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=10, trust_env=False) as client:
                    uploaded = await client.post("/api/v1/datasets", files={
                        "file": ("train.jsonl", (PROJECT_ROOT / "docs/examples/train.jsonl").read_bytes())})
                    assert uploaded.status_code == 201, uploaded.text
                    body = {"dataset_id": uploaded.json()["id"]}
                    headers = {"Idempotency-Key": str(uuid4())}
                    started = time.perf_counter()
                    created = await client.post("/api/v1/tasks", json=body, headers=headers)
                    elapsed = time.perf_counter() - started
                    assert created.status_code == 202, created.text
                    detail = TaskDetail.model_validate(created.json())
                    assert detail.status == "QUEUED" and detail.total_steps is None and detail.progress is None
                    envelope = json.loads(broker.lindex(settings.training_queue, 0))
                    assert envelope["headers"]["task"] == "worker.train"
                    assert envelope["headers"]["id"] == envelope["properties"]["correlation_id"]
                    assert envelope["headers"]["id"] != str(detail.id)
                    args, kwargs, _embedded = json.loads(base64.b64decode(envelope["body"]))
                    assert args == [str(detail.id)] and kwargs == {}
                    assert broker.llen(settings.training_queue) == 1
                    replay = await client.post("/api/v1/tasks", json=body, headers=headers)
                    assert replay.status_code == 200 and replay.json()["id"] == str(detail.id)
                    assert broker.llen(settings.training_queue) == 1
                    page = TaskPage.model_validate((await client.get("/api/v1/tasks?status=QUEUED&page=1&page_size=20")).json())
                    assert page.total == 1 and page.items[0].id == detail.id
                    assert (await client.get(created.headers["location"])).json() == created.json()

                    # Explicit injection AFTER the real Redis LPUSH succeeds.
                    # This models an acknowledgement lost at the Publisher boundary.
                    original = redis.Redis.lpush
                    injected = [False]
                    def lose_ack(connection, name, *values):
                        result = original(connection, name, *values)
                        if name == settings.training_queue and not injected[0]:
                            injected[0] = True
                            raise redis.TimeoutError("controlled lost publish acknowledgement")
                        return result
                    uncertain_headers = {"Idempotency-Key": str(uuid4())}
                    with patch.object(redis.Redis, "lpush", lose_ack):
                        unknown = await client.post("/api/v1/tasks", json=body, headers=uncertain_headers)
                    assert unknown.status_code == 503, unknown.text
                    uncertain = TaskSubmissionErrorResponse.model_validate(unknown.json()).error
                    assert uncertain.code == "DISPATCH_UNCERTAIN" and injected[0]
                    assert broker.llen(settings.training_queue) == 2
                    recovered = await client.post("/api/v1/tasks", json=body, headers=uncertain_headers)
                    assert recovered.status_code == 200 and recovered.json()["id"] == str(uncertain.task_id)
                    assert recovered.json()["status"] == "PENDING" and broker.llen(settings.training_queue) == 2

                    process.terminate()
                    process.wait(timeout=5)
                    down = await client.post("/api/v1/tasks", json=body)
                    assert down.status_code == 503, down.text
                    failure = TaskSubmissionErrorResponse.model_validate(down.json()).error
                    assert failure.code == "DISPATCH_FAILED"
                    failed = (await client.get(down.headers["location"])).json()
                    assert failed["id"] == str(failure.task_id) and failed["status"] == "FAILED"
                    assert (await client.get(created.headers["location"])).json()["status"] == "QUEUED"

                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                try:
                    writer.write(("POST /api/v1/tasks HTTP/1.1\r\nHost: localhost\r\n"
                        f"Content-Length: {MAX_TASK_BODY_BYTES + 1}\r\n"
                        "Content-Type: application/json\r\nConnection: close\r\n\r\n").encode())
                    await writer.drain()
                    raw = await asyncio.wait_for(reader.read(), timeout=5)
                    head, payload = raw.split(b"\r\n\r\n", 1)
                    assert head.startswith(b"HTTP/1.1 413")
                    assert ErrorResponse.model_validate_json(payload).error.code == "REQUEST_TOO_LARGE"
                finally:
                    writer.close()
                    await writer.wait_closed()
                assert list((settings.data_dir / "outputs").iterdir()) == []
                return {"status": "ok", "transport": "TCP/HTTP + private Redis", "create": 202,
                    "replay": 200, "original_publish_count": 1, "lost_ack_injected": True,
                    "unknown_with_task_id": 503, "broker_down_with_task_id": 503, "early_body_limit": 413,
                    "submission_seconds": round(elapsed, 4), "worker_started": False, "gpu_execution_verified": False}
            finally:
                server.should_exit = True
                await task
    finally:
        broker.close()
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def main():
    with tempfile.TemporaryDirectory(prefix="llmcloud-task-http-") as directory:
        print(json.dumps(asyncio.run(check(Path(directory))), ensure_ascii=False))


if __name__ == "__main__":
    main()
