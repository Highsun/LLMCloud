"""Disposable browser API: real HTTP/SQL, explicitly controlled Publisher, no GPU/Redis.

Only this test process exposes controls. Production create_app is unchanged.
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
from threading import Lock
from uuid import UUID, uuid4

import uvicorn
from fastapi import HTTPException
from pydantic import BaseModel
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.app.core.config import Settings
from backend.app.core.task_contract import PublishOutcome
from backend.app.main import create_app
from trainer.contracts import TrainingFailure, TrainingProgress


class PublisherControl:
    def __init__(self):
        self.mode = "accepted"
        self.calls = []
        self.lock = Lock()

    def publish(self, task_id, celery_task_id):
        with self.lock:
            self.calls.append(str(task_id))
            mode, self.mode = self.mode, "accepted"
        return {"accepted": PublishOutcome.ACCEPTED, "unknown": PublishOutcome.UNKNOWN,
                "not_sent": PublishOutcome.NOT_SENT}[mode]


class Control(BaseModel):
    mode: Literal["accepted", "unknown", "not_sent"]


class ExecutionControl(BaseModel):
    # Real repository transitions with synthetic events, never claimed as GPU evidence.
    mode: Literal["loading", "progress", "failed"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18000)
    parser.add_argument("--faults", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="llmcloud-m3-browser-") as directory:
        root = Path(directory)
        publisher = PublisherControl()
        app = create_app(Settings(_env_file=None, data_dir=root / "data", log_dir=root / "logs", database_url=""), task_publisher=publisher)
        if args.faults:
            from scripts.browser_test_support import install_test_controls
            install_test_controls(app)
        tokens = {}

        @app.post("/__test__/publisher", include_in_schema=False)
        def control(data: Control):
            with publisher.lock:
                publisher.mode = data.mode
            return {"publisher_double": True}

        @app.get("/__test__/publisher", include_in_schema=False)
        def calls():
            return {"calls": publisher.calls, "worker_started": False, "gpu_verified": False}

        @app.post("/__test__/tasks/{task_id}", include_in_schema=False)
        def execution(task_id: UUID, data: ExecutionControl):
            repo = app.state.task_repository
            if task_id not in tokens:
                token = uuid4()
                if repo.claim(task_id, token, "browser-test-double") is None:
                    raise HTTPException(409)
                tokens[task_id] = token
            token = tokens[task_id]
            if data.mode == "progress":
                repo.record_progress(task_id, token, TrainingProgress(kind="train", step=2, total_steps=2, loss=0.5, learning_rate=0.0002, epoch=1, recorded_at=datetime.now(timezone.utc)))
            elif data.mode == "failed":
                repo.fail(task_id, token, TrainingFailure(code="TRAINING_FAILED", stage="training", message="受控浏览器失败测试", task_id=task_id))
            return {"synthetic_execution": True}

        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
