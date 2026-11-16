"""Opt-in isolated real Redis/SQLite/GPU inference fault acceptance.

Copies existing terminal datasets/Adapters without changing their identity.
The 90-second case injects a 95-second pause after a real first CUDA token;
production timeouts and token limits are not shortened or overridden.
"""
import argparse
import asyncio
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import redis
from backend.app.core.config import Settings
from backend.app.core.task_contract import PublishOutcome
from backend.app.core.worker_lock import WorkerInstanceLock
from scripts.check_m3_acceptance import Acceptance, write
from trainer.artifacts import sha256, verify_training_artifacts
from trainer.model_cache import resolve_model_paths, verify_model_cache


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def source_fingerprint(source):
    require(source.is_dir() and not source.is_symlink(), "Source directory is unsafe")
    result = {}
    for name in ("llmcloud.db", "datasets", "outputs"):
        target = source / name
        require(target.exists() and not target.is_symlink(), "Required source is missing/linked")
        for path in ([target] if target.is_file() else target.rglob("*")):
            require(not path.is_symlink(), "Source contains links")
            if path.is_file():
                require(path.stat().st_nlink == 1, "Source hard link rejected")
                result[str(path.relative_to(source))] = sha256(path)
    return result


class FaultAcceptance(Acceptance):
    def __init__(self, root, paths, source):
        shared = Settings(_env_file=None, data_dir=root / "data", log_dir=root / "logs", auth_enabled=False)
        super().__init__(root, shared, paths)
        self.settings.auth_enabled = False  # auth regression uses separate fresh databases.
        self.settings.training_queue = "m5fault-" + root.name
        self.source = source
        self.report.update(scope="M5 real inference fault acceptance, controlled first-token stall",
            baseline_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            baseline_dirty=bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)),
            source_data=str(source), auth_enabled=False)

    def save(self):
        write(self.root / "report.json", self.report)

    def seed(self):
        self.fingerprint = source_fingerprint(self.source)
        self.settings.data_dir.mkdir()
        with closing(sqlite3.connect((self.source / "llmcloud.db").as_uri() + "?mode=ro", uri=True)) as original:
            require(original.execute("SELECT COUNT(*) FROM training_tasks WHERE status NOT IN ('COMPLETED','FAILED')").fetchone()[0] == 0,
                "Source training tasks must all be terminal")
            with closing(sqlite3.connect(self.settings.data_dir / "llmcloud.db")) as destination:
                original.backup(destination)
        for name in ("datasets", "outputs"):
            shutil.copytree(self.source / name, self.settings.data_dir / name)
        with closing(sqlite3.connect(self.settings.data_dir / "llmcloud.db")) as connection:
            rows = connection.execute("SELECT id FROM training_tasks WHERE status='COMPLETED' ORDER BY created_at").fetchall()
        require(rows, "Need a completed audited real Adapter")
        self.task_id = rows[0][0]
        output = self.settings.data_dir / "outputs" / self.task_id
        verified = verify_training_artifacts(output, outputs_root=output.parent, expected_task_id=self.task_id)
        self.report["historical_adapter"] = {"task_id": self.task_id,
            "manifest_sha256": sha256(output / "manifest.json"),
            "training_commit": verified.manifest.environment.code_commit}
        self.body = {"task_id": self.task_id, "prompt": "请用三句话解释云计算，逐条举例说明。",
            "mode": "compare", "max_new_tokens": 128}

    def environment(self, **kwargs):
        return {**super().environment(**kwargs), "AUTH_ENABLED": "false", "PYTHONDONTWRITEBYTECODE": "1"}

    async def start(self, socket_dir):
        self.seed()
        socket_path = socket_dir / "redis.sock"
        self.settings.redis_url = f"redis+socket://{socket_path}?virtual_host=0"
        self.settings.celery_result_backend = f"redis+socket://{socket_path}?virtual_host=1"
        self.redis_process = subprocess.Popen(["redis-server", "--port", "0", "--unixsocket", str(socket_path),
            "--unixsocketperm", "700", "--save", "", "--appendonly", "no"],
            stdout=self.log("redis.log"), stderr=subprocess.STDOUT)
        self.broker = redis.Redis(unix_socket_path=str(socket_path), socket_timeout=1)
        for _ in range(200):
            try:
                if self.broker.ping(): break
            except redis.RedisError: pass
            await asyncio.sleep(.05)
        else: raise RuntimeError("Private Redis readiness failed")
        await self.start_api()
        self.client.timeout = 115

    async def worker_ready(self, *, pause=False, missing_cache=False):
        require(self.worker is None, "An owned worker already exists")
        self.marker = self.root / ("token-" + uuid4().hex + ".json")
        command = [sys.executable, "scripts/m5_fault_worker.py", "--marker", str(self.marker)] if pause else [sys.executable, "-m", "worker"]
        self.worker_log = self.root / ("worker-" + uuid4().hex + ".log")
        self.worker = subprocess.Popen(command, cwd=ROOT, env=self.environment(missing_cache=missing_cache),
            stdout=self.log(self.worker_log.name), stderr=subprocess.STDOUT)
        for _ in range(600):
            require(self.worker.poll() is None, "Worker exited; inspect " + self.worker_log.name)
            if " ready." in self.worker_log.read_text(errors="replace"): return
            await asyncio.sleep(.1)
        raise TimeoutError("Worker not ready")

    async def marker_ready(self):
        for _ in range(600):
            require(self.worker.poll() is None, "Fault Worker exited before first token")
            if self.marker.is_file():
                value = json.loads(self.marker.read_text())
                require(value["cuda"] is True, "First token was not generated on CUDA")
                return value
            await asyncio.sleep(.1)
        raise TimeoutError("Real generation did not start")

    async def idle(self):
        for _ in range(400):
            with closing(sqlite3.connect(self.settings.data_dir / "llmcloud.db")) as connection:
                active = connection.execute("SELECT COUNT(*) FROM inference_jobs WHERE state IN ('WAITING','RUNNING')").fetchone()[0]
            if not active: return
            await asyncio.sleep(.1)
        raise TimeoutError("Worker did not release the GPU reservation")

    def error(self, response, status, code):
        require(response.status_code == status and response.json()["error"]["code"] == code,
            f"Expected {status}/{code}, got {response.status_code}: {response.text[:300]}")
        require(response.headers.get("cache-control") == "no-store", "Sensitive response is cacheable")
        return {"http_status": status, "code": code, "request_id": response.headers["x-request-id"]}

    async def success(self):
        started = time.monotonic()
        response = await self.client.post("/api/v1/inference", json=self.body)
        require(response.status_code == 200, response.text[:300])
        body = response.json()
        require(body["task_id"] == self.task_id and body["base"] and body["adapter"], "Compare result is invalid")
        return {"http_status": 200, "request_id": response.headers["x-request-id"],
            "elapsed_seconds": time.monotonic() - started,
            "base_tokens": body["base"]["generated_tokens"], "adapter_tokens": body["adapter"]["generated_tokens"]}

    async def faults(self):
        # A genuine first CUDA token is followed by one controlled 95s pause.
        await self.worker_ready(pause=True)
        started = time.monotonic()
        request = asyncio.create_task(self.client.post("/api/v1/inference", json=self.body))
        token = await self.marker_ready()
        response = await request
        elapsed = time.monotonic() - started
        timeout = self.error(response, 504, "INFERENCE_TIMEOUT")
        require(89.5 <= elapsed < 100, "90-second production budget differs")
        busy = await self.client.post("/api/v1/inference", json=self.body)
        self.error(busy, 409, "GPU_BUSY")
        await self.idle()
        retry = await self.success()
        self.record("real_90s_timeout", {**timeout, "elapsed_seconds": elapsed, "first_token": token,
            "gpu_busy_during_cleanup": True, "retry": retry, "controlled_generation_stall": True})
        await self.stop_worker()

        # Kill only this isolated worker after a confirmed first CUDA token.
        await self.worker_ready(pause=True)
        request = asyncio.create_task(self.client.post("/api/v1/inference", json=self.body))
        token = await self.marker_ready()
        await self.stop_worker(kill=True)
        await self.worker_ready()
        result = self.error(await request, 500, "INFERENCE_FAILED")
        self.record("worker_killed_and_recovered", {**result, "first_token": token, "retry": await self.success()})
        await self.stop_worker()

        await self.worker_ready(missing_cache=True)
        result = self.error(await self.client.post("/api/v1/inference", json=self.body), 503, "MODEL_NOT_CACHED")
        await self.idle()
        await self.stop_worker()
        await self.worker_ready()
        self.record("missing_cache", {**result, "cache_source_unchanged": True, "retry": await self.success()})
        await self.stop_worker()

        original = self.app.state.inference_publisher
        repository = self.app.state.inference_repository
        class Unconfirmed:
            def publish_inference(_, job):
                original.publish_inference(job)
                return PublishOutcome.UNKNOWN
        self.app.state.inference_publisher = Unconfirmed()
        result = self.error(await self.client.post("/api/v1/inference", json=self.body), 503, "INFERENCE_UNAVAILABLE")
        # The real queued message arrives after the request was atomically stopped.
        await self.worker_ready()
        self.app.state.inference_publisher = original
        self.record("publish_unknown_before_claim_late_delivery", {**result, "retry": await self.success()})

        class ClaimedUnconfirmed:
            def publish_inference(_, job):
                original.publish_inference(job)
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    state = repository.get_inference(job)
                    if state and state[0] in ("RUNNING", "FINISHED"): break
                    time.sleep(.02)
                original.publish_inference(job)  # A real duplicate broker delivery.
                return PublishOutcome.UNKNOWN
        self.app.state.inference_publisher = ClaimedUnconfirmed()
        self.record("publish_unknown_after_claim_duplicate_delivery", {"retry": await self.success(),
            "controlled_publish_ack_loss": True, "real_redis_duplicate": True})
        self.app.state.inference_publisher = original
        await self.idle()
        self.record("healthy_after_faults", await self.success())
        self.report["source_unchanged"] = source_fingerprint(self.source) == self.fingerprint
        require(self.report["source_unchanged"], "Original source changed")
        self.report.update(status="passed_for_tested_scope", gpu_execution_verified=True)
        self.save()


async def run(args):
    root = args.output.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=False)
    paths = resolve_model_paths(cache_dir=args.cache_dir, hf_home=args.cache_dir.parent)
    verify_model_cache(paths.cache_dir, Settings(_env_file=None).default_model_revision)
    acceptance = FaultAcceptance(root, paths, args.source.expanduser().resolve())
    # Unix socket names must fit sockaddr_un (108 bytes on Linux). The WSL
    # filesystem including /tmp resides in the user's E-backed Ubuntu disk.
    with tempfile.TemporaryDirectory(prefix="m5-redis-", dir="/tmp") as socket_dir:
        try:
            await acceptance.start(Path(socket_dir))
            await acceptance.faults()
        except BaseException as error:
            acceptance.report.update(status="failed", failure_type=type(error).__name__, failure=str(error)[:1000])
            raise
        finally:
            await acceptance.cleanup()
            with WorkerInstanceLock(acceptance.settings.log_dir):
                acceptance.report["worker_lock_reacquired"] = True
            acceptance.report["owned_services_stopped"] = True
            acceptance.save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-gpu", action="store_true", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
