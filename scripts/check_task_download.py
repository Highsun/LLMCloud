"""Real TCP download of an explicitly synthetic CPU fixture, never GPU evidence."""

import asyncio
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
from uuid import uuid4
from unittest.mock import patch
import zipfile

import httpx
import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
# This is a repository acceptance command. Reuse the existing CPU bundle fixture
# rather than implementing a second fake Trainer or maintaining copied weights.
sys.path.insert(0, str(PROJECT_ROOT / "tests"))

from worker_support import synthetic_train  # noqa: E402
from backend.app.core.config import Settings  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.api.task_download import AdapterResponse  # noqa: E402
from trainer.artifacts import sha256, verify_training_artifacts  # noqa: E402
from trainer.contracts import TrainRequest  # noqa: E402


class PublisherDouble:
    def publish(self, *_args): return "accepted"


async def check(root):
    settings = Settings(_env_file=None, data_dir=root / "data", log_dir=root / "logs", database_url="", training_max_steps=2)
    app = create_app(settings, task_publisher=PublisherDouble())
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="on"))
        running = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            for _ in range(500):
                if server.started or running.done(): break
                await asyncio.sleep(0.01)
            if not server.started: raise RuntimeError("Temporary API failed to start")
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{listener.getsockname()[1]}", timeout=10, trust_env=False) as client:
                dataset = await client.post("/api/v1/datasets", files={"file": ("fixture.jsonl", b'{"instruction":"x","output":"y"}\n')})
                assert dataset.status_code == 201, dataset.text
                created = await client.post("/api/v1/tasks", json={"dataset_id": dataset.json()["id"],
                    "config": {"lora_r": 1, "target_modules": ["q_proj"]}})
                assert created.status_code == 202, created.text
                task_id, token = created.json()["id"], uuid4()
                path = f"/api/v1/tasks/{task_id}/adapter"
                not_ready = await client.get(path)
                assert not_ready.status_code == 409 and not_ready.json()["error"]["code"] == "ARTIFACT_NOT_READY"
                repo = app.state.task_repository
                spec = repo.claim(task_id, token, "controlled-cpu-download")
                output = settings.data_dir / "outputs" / task_id
                request = TrainRequest(task_id=spec.task_id, dataset_path=settings.data_dir / spec.dataset_key,
                    output_dir=output, log_path=settings.log_dir / "tasks" / f"{task_id}.log",
                    cache_dir=settings.data_dir / "models" / "empty-cache", base_model=spec.base_model,
                    config=spec.config, model_revision=spec.model_revision, runtime=spec.runtime)
                synthetic_train(request, lambda event: repo.record_progress(task_id, token, event))
                audit = verify_training_artifacts(output)
                assert repo.complete(task_id, token, f"outputs/{task_id}", sha256(output / "manifest.json"), audit.manifest.summary)
                response = await client.get(path, headers={"Origin": "http://localhost:5173"})
                assert response.status_code == 200, response.text
                assert response.headers["content-type"] == "application/zip"
                assert int(response.headers["content-length"]) == len(response.content)
                assert response.headers["content-disposition"] == f'attachment; filename="llmcloud-adapter-{task_id}.zip"'
                with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
                    assert bundle.testzip() is None
                    assert all(name.startswith(task_id + "/") for name in bundle.namelist())
                    extracted = root / "downloaded" / "outputs"
                    bundle.extractall(extracted)
                assert verify_training_artifacts(extracted / task_id).manifest == audit.manifest
                for _ in range(100):
                    if not list((settings.data_dir / "downloads").iterdir()): break
                    await asyncio.sleep(0.01)
                assert not list((settings.data_dir / "downloads").iterdir())
                # Explicitly stall AFTER a real TCP body chunk so the client can
                # disconnect before normal EOF. The response's actual receive
                # watcher and finally block must cancel the stall and clean up.
                original_call, released = AdapterResponse.__call__, asyncio.Event()
                async def stalled(response, scope, receive, send):
                    async def slow_send(message):
                        await send(message)
                        if message["type"] == "http.response.body" and message.get("more_body"):
                            await asyncio.Event().wait()
                    try:
                        await original_call(response, scope, receive, slow_send)
                    finally:
                        released.set()
                with patch.object(AdapterResponse, "__call__", stalled):
                    async with client.stream("GET", path) as partial:
                        assert partial.status_code == 200
                        async for chunk in partial.aiter_raw():
                            assert chunk
                            break
                    await asyncio.wait_for(released.wait(), timeout=3)
                assert not list((settings.data_dir / "downloads").iterdir())
                held = app.state.task_download_service.prepare(spec.task_id)
                try:
                    busy = await client.get(path)
                    assert busy.status_code == 429 and busy.headers["retry-after"] == "2"
                finally:
                    held.close()
                weights = output / "adapter/adapter_model.safetensors"
                weights.write_bytes(b"x" * weights.stat().st_size)
                invalid = await client.get(path)
                assert invalid.status_code == 500 and invalid.json()["error"]["code"] == "INVALID_ARTIFACT"
                assert (await client.get(f"/api/v1/tasks/{task_id}")).json()["status"] == "COMPLETED"
                assert not list((settings.data_dir / "downloads").iterdir())
                assert all(name not in sys.modules for name in ("torch", "numpy", "transformers", "peft"))
                return {"status": "ok", "transport": "TCP/HTTP", "bundle": "synthetic CPU fixture",
                    "publisher": "test double", "gpu": False, "download": 200, "not_ready": 409,
                    "busy": 429, "tampered": 500, "independent_audit": True, "temporary_cleanup": True,
                    "tcp_disconnect_cleanup": True, "response_stall_injected": True}
        finally:
            server.should_exit = True
            await running


def main():
    with tempfile.TemporaryDirectory(prefix="llmcloud-download-") as directory:
        print(json.dumps(asyncio.run(check(Path(directory))), ensure_ascii=False))


if __name__ == "__main__":
    main()
