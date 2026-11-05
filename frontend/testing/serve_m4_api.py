"""M4-06 disposable Linux API. Real SQL/files/HTTP; synthetic CPU events/bundles.

Controls exist only in this executable. No Redis, Worker, GPU or model download.
Reuse production repositories, MetricWriter and the existing CPU artifact fixture.
"""
import argparse
import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from uuid import UUID, uuid4
import zipfile

import uvicorn
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from typing import Literal

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from backend.app.core.config import Settings
from backend.app.main import create_app
from trainer.artifacts import sha256, verify_training_artifacts
from trainer.contracts import TrainRequest, TrainingFailure, TrainingProgress, TrainingSummary
from trainer.events import MetricWriter
from worker_support import synthetic_train
from serve_task_api import PublisherControl, Control as PublisherMode


class Control(BaseModel):
    mode: Literal["start", "append", "partial", "finish_partial", "replace", "corrupt",
                  "logs", "log_missing", "log_link", "complete", "fail", "bundle",
                  "oversize_bundle", "tamper", "hold", "release", "stall", "storage", "storage_ok"]
    count: int = Field(default=1, ge=1, le=600)
    total: int = Field(default=600, ge=1, le=600)
    both: bool = False


class SlowDownload:
    """Explicit ASGI body fault, after real preparation and headers; never a fake ZIP route."""
    def __init__(self, app, state):
        self.app, self.state = app, state

    async def __call__(self, scope, receive, send):
        stalled = False
        async def controlled_send(message):
            nonlocal stalled
            if (scope["type"] == "http" and scope["path"].endswith("/adapter")
                    and self.state["stall"] and message["type"] == "http.response.body"
                    and message.get("body") and not stalled):
                stalled = True
                # Deliver only a prefix: even the small fixture must remain incomplete.
                await send({**message, "body": message["body"][:4], "more_body": True})
                self.state["started"] += 1
                await asyncio.Event().wait()
            else:
                await send(message)
        try:
            await self.app(scope, receive, controlled_send)
        finally:
            if stalled:
                self.state["released"] += 1


def make_app(root):
    settings = Settings(_env_file=None, data_dir=root / "data", log_dir=root / "logs", database_url="")
    publisher = PublisherControl()
    app = create_app(settings, task_publisher=publisher)
    state = {"stall": False, "started": 0, "released": 0}
    app.add_middleware(SlowDownload, state=state)
    tokens, steps, pending, held = {}, {}, {}, {}

    @app.post("/__test__/publisher", include_in_schema=False)
    def publishing(data: PublisherMode):
        with publisher.lock:
            publisher.mode = data.mode
        return {"publisher_double": True}

    @app.get("/__test__/state", include_in_schema=False)
    def inspect():
        downloads = settings.data_dir / "downloads"
        return {**state, "temporary_entries": len(list(downloads.iterdir())) if downloads.exists() else 0,
                "gpu": False, "publisher": "double", "events_and_bundles": "synthetic CPU",
                "training_imports": [name for name in ("torch", "numpy", "transformers", "peft") if name in sys.modules]}

    @app.post("/__test__/tasks/{task_id}", include_in_schema=False)
    def control(task_id: UUID, data: Control):
        repo = app.state.task_repository
        output = settings.data_dir / "outputs" / str(task_id)
        metric = output / "metrics.jsonl"
        log = settings.log_dir / "tasks" / f"{task_id}.log"
        if task_id not in tokens:
            token = uuid4()
            spec = repo.claim(task_id, token, "m4-06-controlled-cpu")
            if spec is None:
                raise HTTPException(409, "Test task must be queued")
            tokens[task_id] = (token, spec)
            steps[task_id] = 0
        token, spec = tokens[task_id]
        output.parent.mkdir(parents=True, exist_ok=True)
        log.parent.mkdir(parents=True, exist_ok=True)
        if data.mode in ("bundle", "oversize_bundle"):
            request = TrainRequest(task_id=task_id, dataset_path=settings.data_dir / spec.dataset_key,
                output_dir=output, log_path=log, cache_dir=root / "empty-cache", base_model=spec.base_model,
                config=spec.config, model_revision=spec.model_revision, runtime=spec.runtime)
            synthetic_train(request, lambda event: repo.record_progress(task_id, token, event))
            audit = verify_training_artifacts(output)
            if data.mode == "oversize_bundle":
                # Metadata budget fault only; do not allocate a 256 MiB test file.
                manifest = json.loads((output / "manifest.json").read_text())
                manifest["artifacts"][0]["size_bytes"] = 256 * 1024 * 1024 + 1
                (output / "manifest.json").write_text(json.dumps(manifest))
            assert repo.complete(task_id, token, f"outputs/{task_id}", sha256(output / "manifest.json"), audit.manifest.summary)
            log.write_text(json.dumps({"recorded_at": "2026-11-05T01:00:00Z", "stage": "training_and_save_finished", "completed_steps": 2}) + "\n")
        elif data.mode == "append":
            output.mkdir(exist_ok=True)
            with metric.open("a", encoding="utf-8") as stream:
                writer = MetricWriter(stream, lambda event: repo.record_progress(task_id, token, event))
                for _ in range(data.count):
                    steps[task_id] += 1
                    step = steps[task_id]
                    for kind in (("train", "eval") if data.both else ("train",)):
                        writer.emit(kind=kind, step=step, total_steps=data.total,
                            loss=0.0 if kind == "train" and step == data.total else (0.75 if kind == "train" else 1.25),
                            learning_rate=0.0, epoch=step / data.total)
        elif data.mode == "partial":
            event = TrainingProgress(step=steps[task_id] + 1, total_steps=data.total,
                loss=0.25, learning_rate=0.0, epoch=1, recorded_at="2026-11-05T01:00:01Z")
            with metric.open("ab") as stream:
                stream.write(event.model_dump_json().encode())
            pending[task_id] = event
        elif data.mode == "finish_partial":
            with metric.open("ab") as stream:
                stream.write(b"\n")
            event = pending.pop(task_id)
            assert repo.record_progress(task_id, token, event)
            steps[task_id] = event.step
        elif data.mode == "replace":
            other = metric.with_suffix(".replacement")
            other.write_bytes(metric.read_bytes())
            other.replace(metric)
        elif data.mode == "corrupt":
            with metric.open("ab") as stream:
                stream.write(b"{invalid-json}\n")
        elif data.mode == "logs":
            log.write_text("".join(json.dumps({"recorded_at": "2026-11-05T01:00:00Z", "stage": "saving",
                "untrusted": "<img src=x onerror=alert(1)> private-path"}) + "\n" for _ in range(105))
                + '{"stage":"saving"', encoding="utf-8")
        elif data.mode == "log_missing":
            log.unlink(missing_ok=True)
        elif data.mode == "log_link":
            log.unlink(missing_ok=True)
            outside = root / "private-log"
            outside.write_text("private-path")
            log.symlink_to(outside)
        elif data.mode == "complete":
            assert repo.complete(task_id, token, f"outputs/{task_id}", "a" * 64,
                TrainingSummary(completed_steps=data.total, total_steps=data.total, elapsed_seconds=1,
                    peak_memory_allocated_bytes=0, trainable_parameters=4, total_parameters=104, final_loss=0.0))
            log.write_text(json.dumps({"recorded_at": "2026-11-05T01:00:02Z", "stage": "training_and_save_finished",
                                      "completed_steps": data.total}) + "\n")
        elif data.mode == "fail":
            assert repo.fail(task_id, token, TrainingFailure(task_id=task_id, code="TRAINING_FAILED",
                stage="training", message="M4-06 受控 CPU 故障"))
        elif data.mode == "tamper":
            weights = output / "adapter/adapter_model.safetensors"
            weights.write_bytes(b"x" * weights.stat().st_size)
        elif data.mode == "hold":
            held[task_id] = app.state.task_download_service.prepare(task_id)
        elif data.mode == "release":
            held.pop(task_id).close()
        elif data.mode == "stall":
            state["stall"] = not state["stall"]
        elif data.mode == "storage":
            (settings.data_dir / "downloads").chmod(0o777)
        elif data.mode == "storage_ok":
            (settings.data_dir / "downloads").chmod(0o700)
        return {"controlled_cpu_fixture": True, "step": steps[task_id]}

    @app.post("/__test__/audit/{task_id}", include_in_schema=False)
    async def audit_download(task_id: UUID, request: Request):
        raw = await request.body()
        if len(raw) > 1024 * 1024:
            raise HTTPException(413)
        with tempfile.TemporaryDirectory(dir=root, prefix="download-audit-") as directory:
            with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
                names = bundle.namelist()
                assert len(names) <= 32 and len(names) == len(set(names))
                assert all(name.startswith(f"{task_id}/") and ".." not in Path(name).parts and "\\" not in name for name in names)
                assert sum(item.file_size for item in bundle.infolist()) <= 1024 * 1024
                assert bundle.testzip() is None
                bundle.extractall(directory)
            verified = verify_training_artifacts(Path(directory) / str(task_id), expected_task_id=task_id)
            source = settings.data_dir / "outputs" / str(task_id)
            assert sha256(Path(directory) / str(task_id) / "manifest.json") == sha256(source / "manifest.json")
            return {"sha256": hashlib.sha256(raw).hexdigest(), "metric_count": verified.metric_count,
                    "crc": "passed", "shared_audit": "passed", "bundle": "synthetic CPU, not trained"}

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18006)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    if not all(hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW")):
        parser.error("M4 real file API checks require Linux/WSL; safety rules must not be patched out")
    with tempfile.TemporaryDirectory(prefix="llmcloud-m4-06-") as directory:
        uvicorn.run(make_app(Path(directory)), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
