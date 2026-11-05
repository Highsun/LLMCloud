"""Isolated TCP/SQL/file append smoke; Publisher and execution are CPU fixtures."""

import asyncio
import json
from pathlib import Path
import socket
import sys
import tempfile
from uuid import uuid4

import httpx
import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.config import Settings  # noqa: E402
from backend.app.core.task_contract import PublishOutcome  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.models.observability_schemas import LogsPage, MetricsPage  # noqa: E402
from trainer.contracts import TrainingSummary  # noqa: E402
from trainer.events import MetricWriter  # noqa: E402


class PublisherDouble:
    def publish(self, *_args):
        return PublishOutcome.ACCEPTED


async def check(root):
    settings = Settings(_env_file=None, data_dir=root / "data", log_dir=root / "logs", database_url="", api_prefix="/api/v1")
    app = create_app(settings, task_publisher=PublisherDouble())
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="on"))
        running = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            for _ in range(500):
                if server.started or running.done(): break
                await asyncio.sleep(0.01)
            if not server.started:
                raise RuntimeError("Temporary API failed to start")
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{listener.getsockname()[1]}",
                    timeout=10, trust_env=False) as client:
                uploaded = await client.post("/api/v1/datasets", files={"file": (
                    "cpu-fixture.jsonl", b'{"instruction":"fixture","output":"fixture"}\n')})
                assert uploaded.status_code == 201, uploaded.text
                created = await client.post("/api/v1/tasks", json={"dataset_id": uploaded.json()["id"]})
                assert created.status_code == 202, created.text
                task_id, token = created.json()["id"], uuid4()
                base = f"/api/v1/tasks/{task_id}"
                assert (await client.get(base + "/metrics")).json()["source_state"] == "not_created"
                repo = app.state.task_repository
                assert repo.claim(task_id, token, "controlled-cpu-smoke") is not None
                output = settings.data_dir / "outputs" / task_id
                output.mkdir()
                with (output / "metrics.jsonl").open("w", encoding="utf-8") as stream:
                    writer = MetricWriter(stream, lambda event: repo.record_progress(task_id, token, event))
                    writer.emit(kind="train", step=1, total_steps=2, loss=1.0, learning_rate=0.0002, epoch=0.5)
                    first_response = await client.get(base + "/metrics?limit=1")
                    assert first_response.status_code == 200, first_response.text
                    first = MetricsPage.model_validate(first_response.json())
                    assert len(first.items) == 1 and first.items[0].step == 1 and not first.has_more
                    # The next real flush appends, preserving the source identity.
                    writer.emit(kind="train", step=2, total_steps=2, loss=0.0, learning_rate=0.0, epoch=1.0)
                assert repo.complete(task_id, token, f"outputs/{task_id}", "a" * 64,
                    TrainingSummary(completed_steps=2, total_steps=2, elapsed_seconds=1.0,
                        peak_memory_allocated_bytes=0, trainable_parameters=4, total_parameters=104, final_loss=0.0))
                # This is metadata completion in an isolated test, no GPU/bundle evidence.
                params = {"cursor": first.next_cursor, "source_id": first.source_id}
                final = MetricsPage.model_validate((await client.get(base + "/metrics", params=params)).json())
                assert final.source_id == first.source_id and final.task_status == "COMPLETED"
                assert len(final.items) == 1 and final.items[0].loss == 0.0
                drained = (await client.get(base + "/metrics", params={
                    "cursor": final.next_cursor, "source_id": final.source_id})).json()
                assert not drained["items"] and not drained["has_more"]
                log = settings.log_dir / "tasks" / f"{task_id}.log"
                log.parent.mkdir()
                log.write_text(json.dumps({"recorded_at": "2026-11-04T01:00:00Z", "stage": "saving",
                                           "secret": "must-not-leak"}) + "\n", encoding="utf-8")
                logs = LogsPage.model_validate((await client.get(base + "/logs")).json())
                assert logs.filtered_lines == 1 and len(logs.lines) == 1 and "must-not-leak" not in logs.lines[0]
                invalid = await client.get(base + "/metrics?limit=1&limit=2")
                assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "VALIDATION_ERROR"
                old = await client.get(base + "/metrics", params={"source_id": "f" * 64})
                assert old.status_code == 409 and old.json()["error"]["code"] == "METRICS_CURSOR_INVALID"
                paths = (await client.get("/openapi.json")).json()["paths"]
                assert "/api/v1/tasks/{task_id}/metrics" in paths and "/api/v1/tasks/{task_id}/logs" in paths
                assert "/api/v1/tasks/{task_id}/adapter" in paths
                assert all(name not in sys.modules for name in ("torch", "numpy", "transformers", "peft"))
                return {"status": "ok", "transport": "TCP/HTTP", "sql": "isolated SQLite",
                    "events": "controlled CPU MetricWriter", "publisher": "test double", "gpu": False,
                    "append": True, "terminal_drain": True, "log_projection": True,
                    "duplicate_query": 422, "stale_source": 409, "download_verified": False}
        finally:
            server.should_exit = True
            await running


def main():
    with tempfile.TemporaryDirectory(prefix="llmcloud-observability-") as directory:
        print(json.dumps(asyncio.run(check(Path(directory))), ensure_ascii=False))


if __name__ == "__main__":
    main()
