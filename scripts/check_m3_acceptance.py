"""Opt-in real M3-07 GPU/Redis/SQL/browser acceptance; evidence stays in ignored data/."""

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

import httpx
import redis
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.core.config import Settings  # noqa: E402
from backend.app.core.worker_lock import WorkerInstanceLock  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from trainer.artifacts import sha256, verify_training_artifacts  # noqa: E402
from trainer.model_cache import resolve_model_paths, verify_model_cache  # noqa: E402


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def stop(process, *, kill=False):
    if process is None or process.poll() is not None:
        return
    process.kill() if kill else process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class Acceptance:
    def __init__(self, root, shared, paths):
        self.root, self.shared, self.paths = root, shared, paths
        self.settings = Settings(_env_file=None, data_dir=root / "data", log_dir=shared.log_dir,
            database_url="", training_queue="m307-acceptance", api_prefix="/api/v1",
            default_model_revision=shared.default_model_revision, training_precision="bf16", training_max_steps=2)
        self.worker = self.vite = self.redis_process = self.api = self.server = None
        self.open_files = []
        self.report = {"version": "1.0.0", "status": "running", "started_at": datetime.now(timezone.utc).isoformat(),
            "model_revision": shared.default_model_revision, "engineering_draft": True,
            "gpu_execution_verified": False, "cases": {}, "artifacts": {}}
        self.client = None

    def record(self, name, value):
        self.report["cases"][name] = value
        write(self.root / "report.json", self.report)
        print(json.dumps({"case": name, "status": "passed"}, ensure_ascii=False), flush=True)

    def log(self, name):
        stream = (self.root / name).open("a", encoding="utf-8")
        self.open_files.append(stream)
        return stream

    def environment(self, *, missing_cache=False):
        home = self.root / "empty-cache" if missing_cache else self.paths.hf_home
        cache = home / "hub" if missing_cache else self.paths.cache_dir
        return {**os.environ, "DATA_DIR": str(self.settings.data_dir), "LOG_DIR": str(self.settings.log_dir),
            "DATABASE_URL": self.settings.resolved_database_url, "TRAINING_QUEUE": self.settings.training_queue,
            "REDIS_URL": self.settings.redis_url, "CELERY_BROKER_URL": self.settings.redis_url,
            "CELERY_BROKER_READ_URL": self.settings.redis_url, "CELERY_BROKER_WRITE_URL": self.settings.redis_url,
            "CELERY_RESULT_BACKEND": self.settings.celery_result_backend,
            "HF_HOME": str(home), "HF_HUB_CACHE": str(cache), "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1", "TOKENIZERS_PARALLELISM": "false",
            "CUDA_VISIBLE_DEVICES": "0", "PYTHONUNBUFFERED": "1"}

    async def start_api(self):
        self.app = create_app(self.settings)
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", getattr(self, "api_port", 0)))
        self.api_port = self.listener.getsockname()[1]
        self.api_url = f"http://127.0.0.1:{self.listener.getsockname()[1]}"
        self.server = uvicorn.Server(uvicorn.Config(self.app, log_level="warning", lifespan="on"))
        self.api = asyncio.create_task(self.server.serve(sockets=[self.listener]))
        for _ in range(500):
            if self.server.started:
                self.client = httpx.AsyncClient(base_url=self.api_url, timeout=15, trust_env=False)
                return
            if self.api.done():
                break
            await asyncio.sleep(0.02)
        raise RuntimeError("API readiness failed")

    async def stop_api(self):
        if self.client is not None:
            await self.client.aclose()
            self.client = None
        if self.api is not None:
            self.server.should_exit = True
            await self.api
            self.api = None
            self.listener.close()

    async def start_frontend(self):
        vite_port = port()
        self.front_url = f"http://127.0.0.1:{vite_port}"
        self.vite = subprocess.Popen(["npm", "run", "dev", "--", "--port", str(vite_port)], cwd=ROOT / "frontend",
            env={**os.environ, "VITE_BACKEND_URL": self.api_url, "VITE_API_BASE_URL": "/api/v1", "VITE_OPENAPI_URL": "/openapi.json"},
            stdout=self.log("vite.log"), stderr=subprocess.STDOUT, start_new_session=True)
        async with httpx.AsyncClient(trust_env=False) as probe:
            for _ in range(200):
                try:
                    if (await probe.get(self.front_url)).status_code == 200: return
                except httpx.HTTPError: pass
                await asyncio.sleep(0.05)
        raise RuntimeError("Vite readiness failed")

    async def cleanup(self):
        await self.stop_worker()
        await self.stop_api()
        if self.vite is not None:
            import signal
            try:
                os.killpg(self.vite.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            await asyncio.to_thread(stop, self.vite)
        if hasattr(self, "broker"): self.broker.close()
        await asyncio.to_thread(stop, self.redis_process)
        for stream in self.open_files: stream.close()

    async def start_worker(self, *, fault=None, task_id=None, missing_cache=False):
        assert self.worker is None
        command = [sys.executable, "-m", "worker"] if fault is None else [sys.executable,
            "scripts/m3_acceptance_worker.py", "--task-id", task_id, "--fault", fault]
        self.worker_log = self.root / f"worker-{fault or 'normal'}-{uuid4().hex[:8]}.log"
        self.worker = subprocess.Popen(command, cwd=ROOT, env=self.environment(missing_cache=missing_cache),
            stdout=self.log(self.worker_log.name), stderr=subprocess.STDOUT)

    async def stop_worker(self, *, kill=False):
        await asyncio.to_thread(stop, self.worker, kill=kill)
        self.worker = None

    async def detail(self, task_id):
        response = await self.client.get(f"/api/v1/tasks/{task_id}")
        assert response.status_code == 200, response.text
        return response.json()

    async def wait(self, task_id, predicate, *, timeout=240):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            last = await self.detail(task_id)
            if predicate(last):
                return last
            if last["status"] in ("COMPLETED", "FAILED"):
                raise AssertionError(f"Unexpected terminal state: {last}")
            if self.worker is not None and self.worker.poll() is not None:
                raise RuntimeError(f"Worker exited; see {self.worker_log.name}")
            await asyncio.sleep(0.03)
        raise TimeoutError(f"Task did not reach expected state: {last}")

    async def submit(self, dataset_id, *, key=None):
        body = {"dataset_id": dataset_id, "config": {"gradient_accumulation_steps": 1,
            "max_seq_length": 256, "logging_steps": 1}}
        headers = {"Idempotency-Key": key or str(uuid4())}
        response = await self.client.post("/api/v1/tasks", json=body, headers=headers)
        assert response.status_code == 202, response.text
        return response.json(), body, headers

    def audit(self, task_id):
        directory = self.settings.data_dir / "outputs" / task_id
        verified = verify_training_artifacts(directory, outputs_root=directory.parent,
            expected_task_id=task_id, expected_revision=self.settings.default_model_revision)
        manifest = verified.manifest
        assert manifest.environment.cuda_runtime and manifest.summary.peak_memory_allocated_bytes > 0
        assert manifest.summary.completed_steps == manifest.summary.total_steps == 2
        assert manifest.train_dataset.sha256 == sha256(self.settings.data_dir / "datasets" / self.dataset_id / "train.jsonl")
        value = {**verified.summary(), "summary": manifest.summary.model_dump(mode="json"),
            "environment": manifest.environment.model_dump(mode="json"), "manifest_sha256": sha256(directory / "manifest.json")}
        self.report["artifacts"][task_id] = value
        write(self.root / "report.json", self.report)
        return value

    def browser_env(self):
        environment = {**os.environ}
        if Path("/tmp/llmcloud-playwright-browsers").is_dir():
            environment.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/tmp/llmcloud-playwright-browsers")
        libraries = "/tmp/llmcloud-browser-libs/root/usr/lib/x86_64-linux-gnu"
        if Path(libraries).is_dir():
            environment["LD_LIBRARY_PATH"] = libraries + ":" + environment.get("LD_LIBRARY_PATH", "")
        fonts = Path("/tmp/llmcloud-browser-fonts/fonts.conf")
        if fonts.is_file():
            environment.setdefault("FONTCONFIG_FILE", str(fonts))
        return environment

    async def browser(self, name, *, task_id=None, status=None, code=None):
        target = self.root / name
        command = ["node", "scripts/check_m3_browser.mjs", "--url", self.front_url, "--output", str(target)]
        if task_id:
            command += ["--task", task_id, "--status", status]
        if code:
            command += ["--code", code]
        process = subprocess.Popen(command, cwd=ROOT, env=self.browser_env(), stdout=self.log(name + ".log"), stderr=subprocess.STDOUT)
        try:
            await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=300)
            assert process.returncode == 0, f"Browser failed; see {name}.log"
            return json.loads((target / "result.json").read_text())
        finally:
            await asyncio.to_thread(stop, process)

    async def reconcile(self, *, apply=False):
        assert self.api is None and self.worker is None, "Stop owned services before offline apply"
        command = [sys.executable, "scripts/reconcile_tasks.py", "--data-dir", str(self.settings.data_dir),
            "--log-dir", str(self.settings.log_dir), "--database-url", self.settings.resolved_database_url]
        command += ["--apply", "--services-stopped"] if apply else ["--check"]
        result = await asyncio.to_thread(subprocess.run, command, cwd=ROOT, capture_output=True, text=True, timeout=30)
        report = json.loads(result.stdout)
        assert result.returncode == 0, report
        return report

    async def review_records(self):
        """Reopen actual persisted records for readable screenshots; no training or Redis."""
        assert self.report["status"] == "passed" and self.report["gpu_execution_verified"]
        self.settings.redis_url = "redis://127.0.0.1:1/0"  # No business broker, even on an unintended mutation.
        cases = self.report["cases"]
        targets = [
            ("browser-success", cases["two_serial_gpu_tasks_and_browser"]["task_ids"][1], "COMPLETED", None),
            ("browser-recovered", cases["before_commit"]["task_id"], "COMPLETED", None),
            ("browser-saving-failed", cases["saving"]["task_id"], "FAILED", "ARTIFACT_WRITE_FAILED"),
            ("browser-interrupted", cases["gpu_interruption_and_queued_abandonment"]["interrupted"]["id"], "FAILED", "WORKER_INTERRUPTED"),
            ("browser-invalid-dataset", cases["controlled_dataset_tamper"]["id"], "FAILED", "INVALID_DATASET"),
        ]
        try:
            await self.start_api()
            await self.start_frontend()
            for name, task_id, status, code in targets:
                await self.browser(name + "-cjk", task_id=task_id, status=status, code=code)
            self.report["browser_visual_review"] = {"status": "passed", "mode": "persisted_real_records_no_gpu_rerun",
                "directories": [name + "-cjk" for name, *_ in targets], "finished_at": datetime.now(timezone.utc).isoformat()}
        finally:
            await self.cleanup()

    async def run(self, socket_dir):
        socket_path = socket_dir / "redis.sock"
        self.settings.redis_url = f"redis+socket://{socket_path}?virtual_host=0"
        self.settings.celery_result_backend = f"redis+socket://{socket_path}?virtual_host=1"
        self.redis_process = subprocess.Popen([shutil.which("redis-server"), "--port", "0", "--unixsocket", str(socket_path),
            "--unixsocketperm", "700", "--save", "", "--appendonly", "no"], stdout=self.log("redis.log"), stderr=subprocess.STDOUT)
        self.broker = redis.Redis(unix_socket_path=str(socket_path), socket_timeout=1)
        try:
            for _ in range(200):
                try:
                    if self.broker.ping(): break
                except redis.RedisError:
                    await asyncio.sleep(0.02)
            else: raise RuntimeError("Redis readiness failed")
            await self.start_api()
            await self.start_frontend()
            await self.start_worker()
            browser = await self.browser("browser-success")
            self.dataset_id = browser["dataset_id"]
            tasks = browser["tasks"]
            assert datetime.fromisoformat(tasks[1]["started_at"].replace("Z", "+00:00")) >= datetime.fromisoformat(tasks[0]["finished_at"].replace("Z", "+00:00"))
            for task in tasks: self.audit(task["id"])
            self.record("two_serial_gpu_tasks_and_browser", {"task_ids": browser["task_ids"], "tasks": tasks,
                "no_overlap": True, "browser_mocked_routes": browser["mocked_routes"]})
            # Replay the real stored request and then duplicate its actual task message.
            submission = browser["submissions"][0]
            before = await self.detail(submission["id"])
            response = await self.client.post("/api/v1/tasks", json=submission["body"], headers={"Idempotency-Key": submission["key"]})
            assert response.status_code == 200 and response.json() == before
            from backend.app.services.task_dispatch import CeleryPublisher
            from backend.app.core.task_contract import PublishOutcome
            assert await asyncio.to_thread(CeleryPublisher(self.settings).publish, submission["id"], str(uuid4())) == PublishOutcome.ACCEPTED
            for _ in range(200):
                if "'outcome': 'skipped'" in self.worker_log.read_text(): break
                await asyncio.sleep(0.03)
            else: raise RuntimeError("Duplicate was not confirmed skipped")
            assert before == await self.detail(submission["id"])
            self.record("request_and_message_deduplication", {"task_id": submission["id"], "http_replay": 200, "duplicate": "skipped"})
            await self.stop_worker()
            # Actual GPU training followed by controlled real SQL commit/publication faults.
            for mode in ("after_commit", "before_commit", "saving"):
                task, _body, _headers = await self.submit(self.dataset_id)
                task_id = task["id"]
                await self.start_worker(fault=mode, task_id=task_id)
                if mode == "before_commit":
                    deadline = time.monotonic() + 240
                    while time.monotonic() < deadline:
                        if "'outcome': 'reconciliation_required'" in self.worker_log.read_text(): break
                        if self.worker.poll() is not None: raise RuntimeError("Fault Worker exited")
                        await asyncio.sleep(0.1)
                    else: raise TimeoutError("Completion rollback not observed")
                    current = await self.detail(task_id)
                    assert current["status"] == "RUNNING" and current["current_step"] == current["total_steps"] == 2
                    self.audit(task_id)
                    await self.stop_worker()
                    await self.stop_api()
                    checked, applied, again = await self.reconcile(), await self.reconcile(apply=True), await self.reconcile()
                    assert applied["applied_count"] == 1 and again["state"] == "current"
                    await self.start_api()
                    recovered = await self.detail(task_id)
                    assert recovered["status"] == "COMPLETED"
                    self.record(mode, {"task_id": task_id, "before": current, "after": recovered, "check": checked, "apply": applied})
                    await self.browser("browser-recovered", task_id=task_id, status="COMPLETED")
                else:
                    expected = "FAILED" if mode == "saving" else "COMPLETED"
                    current = await self.wait(task_id, lambda row: row["status"] == expected)
                    if mode == "saving":
                        directory = self.settings.data_dir / "outputs" / task_id
                        assert current["error_code"] == "ARTIFACT_WRITE_FAILED" and not (directory / "manifest.json").exists()
                        assert (directory / "adapter/adapter_model.safetensors").is_file() and (directory / "failure.json").is_file()
                        await self.browser("browser-saving-failed", task_id=task_id, status="FAILED", code="ARTIFACT_WRITE_FAILED")
                    else: self.audit(task_id)
                    self.record(mode, {"task_id": task_id, "task": current, "controlled_injection": True})
                    await self.stop_worker()
            # Kill only our live GPU Worker after at least one real optimizer update.
            self.settings.training_max_steps = 64
            interrupted, _, _ = await self.submit(self.dataset_id)
            queued, _, _ = await self.submit(self.dataset_id)
            self.settings.training_max_steps = 2
            await self.start_worker()
            current = await self.wait(interrupted["id"], lambda row: row["status"] == "RUNNING" and 0 < row["current_step"] < row["total_steps"])
            await self.stop_worker(kill=True)
            current = await self.detail(interrupted["id"])
            assert current["status"] == "RUNNING" and (await self.detail(queued["id"]))["status"] == "QUEUED"
            directory = self.settings.data_dir / "outputs" / interrupted["id"]
            inventory = {str(p.relative_to(directory)): sha256(p) for p in directory.rglob("*") if p.is_file()}
            await self.stop_api()
            checked, applied = await self.reconcile(), await self.reconcile(apply=True)
            assert applied["applied_count"] == 2 and (await self.reconcile())["state"] == "current"
            assert inventory == {str(p.relative_to(directory)): sha256(p) for p in directory.rglob("*") if p.is_file()}
            await self.start_api()
            failed = await self.detail(interrupted["id"])
            abandoned = await self.detail(queued["id"])
            assert failed["error_code"] == "WORKER_INTERRUPTED" and failed["current_step"] == current["current_step"]
            assert abandoned["error_code"] == "TASK_ABANDONED"
            self.record("gpu_interruption_and_queued_abandonment", {"interrupted": failed, "queued": abandoned,
                "preserved_files": inventory, "check": checked, "apply": applied})
            await self.browser("browser-interrupted", task_id=interrupted["id"], status="FAILED", code="WORKER_INTERRUPTED")
            # A preserved old queue message must skip the now terminal abandoned task.
            await self.start_worker()
            for _ in range(200):
                if "'outcome': 'skipped'" in self.worker_log.read_text(): break
                await asyncio.sleep(0.05)
            else: raise TimeoutError("Residual message not skipped")
            assert abandoned == await self.detail(queued["id"])
            self.record("residual_message_after_reconciliation", {"task_id": queued["id"], "outcome": "skipped"})
            await self.stop_worker()
            # Isolated immutable-file corruption: real hash check must fail before GPU load.
            upload = await self.client.post("/api/v1/datasets", files={"file": ("draft.jsonl", (ROOT / "docs/examples/train.jsonl").read_bytes())})
            assert upload.status_code == 201
            dataset = upload.json()
            (self.settings.data_dir / "datasets" / dataset["id"] / "train.jsonl").write_bytes(b'{"instruction":"changed","output":"changed"}\n')
            tampered, _, _ = await self.submit(dataset["id"])
            await self.start_worker()
            invalid = await self.wait(tampered["id"], lambda row: row["status"] == "FAILED")
            assert invalid["error_code"] == "INVALID_DATASET"
            self.record("controlled_dataset_tamper", invalid)
            await self.browser("browser-invalid-dataset", task_id=tampered["id"], status="FAILED", code="INVALID_DATASET")
            await self.stop_worker()
            missing, _, _ = await self.submit(self.dataset_id)
            await self.start_worker(missing_cache=True)
            failure = await self.wait(missing["id"], lambda row: row["status"] == "FAILED")
            assert failure["error_code"] == "MODEL_NOT_CACHED"
            self.record("isolated_missing_cache", failure)
            self.report.update(status="passed", gpu_execution_verified=True, finished_at=datetime.now(timezone.utc).isoformat(),
                teammate_evidence_review="pending", browser_url=self.front_url)
        finally:
            await self.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpu", action="store_true", help="Explicitly run real LoRA on the local GPU")
    parser.add_argument("--run-dir", type=Path, help="New evidence directory; must not already exist")
    parser.add_argument("--review-run", type=Path, help="Reopen a passed run's actual records for screenshots; no GPU")
    args = parser.parse_args()
    if args.review_run:
        if args.gpu or args.run_dir: parser.error("--review-run cannot be combined with --gpu/--run-dir")
        root = args.review_run.absolute()
        runner = Acceptance(root, Settings(), resolve_model_paths())
        runner.report = json.loads((root / "report.json").read_text())
        asyncio.run(runner.review_records())
        write(root / "report.json", runner.report)
        print(json.dumps({"status": "passed", "mode": "persisted_real_records_no_gpu_rerun"}))
        return
    if not args.gpu: parser.error("--gpu is required; coordinate exclusive GPU use first")
    if not shutil.which("redis-server") or not shutil.which("npm"): parser.error("redis-server/npm required")
    shared, paths = Settings(), resolve_model_paths()
    with WorkerInstanceLock(shared.log_dir):
        verify_model_cache(paths.cache_dir, shared.default_model_revision)
    root = (args.run_dir or shared.data_dir / "acceptance/m3-07" / str(uuid4())).absolute()
    root.mkdir(parents=True, exist_ok=False)
    runner = Acceptance(root, shared, paths)
    print(json.dumps({"run_dir": str(root), "status": "starting"}), flush=True)
    try:
        with tempfile.TemporaryDirectory(prefix="m307-") as directory:
            asyncio.run(runner.run(Path(directory)))
    except BaseException as error:
        runner.report.update(status="failed", error_type=type(error).__name__)
        raise
    finally:
        write(root / "report.json", runner.report)
    print(json.dumps({"status": runner.report["status"], "run_dir": str(root), "gpu_execution_verified": True}), flush=True)


if __name__ == "__main__":
    main()
