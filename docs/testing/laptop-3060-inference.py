"""Isolated M5 human session using copies of existing real completed tasks."""

import argparse
import asyncio
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time

REPO = Path(os.environ.get("LLMCLOUD_TEST_REPO", str(Path.home() / "LLMCloud"))).expanduser().resolve()
sys.path.insert(0, str(REPO))

from backend.app.core.config import Settings
from backend.app.core.task_contract import DEFAULT_MODEL_REVISION
from backend.app.core.worker_lock import WorkerInstanceLock
from scripts.check_m4_acceptance import Acceptance, code_baseline
from scripts.m4_acceptance_support import audit_gpu_output, new_run_directory, require
from trainer.artifacts import sha256, verify_training_artifacts
from trainer.model_cache import resolve_model_paths, verify_model_cache


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


@contextmanager
def readonly_database(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)) as connection:
        yield connection


def inspect_source(source):
    require(source.is_dir() and source.resolve() == source, "Source must be a real data directory")
    database = source / "llmcloud.db"
    require(database.is_file() and not database.is_symlink(), "Source database missing or linked")
    # Reject links and non-regular files before copying. Model caches are never copied.
    for name in ("datasets", "outputs"):
        directory = source / name
        require(directory.is_dir() and not directory.is_symlink(), f"Missing real {name} directory")
        for path in directory.rglob("*"):
            require(not path.is_symlink() and (path.is_file() or path.is_dir()), "Unsafe source entry")
            if path.is_file():
                require(path.stat().st_nlink == 1, "Linked source file")
    with readonly_database(database) as connection:
        tasks = connection.execute("SELECT id, status FROM training_tasks ORDER BY created_at").fetchall()
        if connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='inference_jobs'").fetchone():
            require(connection.execute("SELECT COUNT(*) FROM inference_jobs WHERE state != 'FINISHED'").fetchone()[0] == 0,
                    "Source has unfinished inference")
    require(tasks and all(status in ("COMPLETED", "FAILED") for _, status in tasks),
            "Source must contain only terminal training tasks")
    completed = []
    for task_id, status in tasks:
        if status != "COMPLETED":
            continue
        audited = verify_training_artifacts(source / "outputs" / task_id, outputs_root=source / "outputs",
            expected_task_id=task_id, expected_revision=DEFAULT_MODEL_REVISION)
        completed.append({"task_id": task_id, "manifest_sha256": sha256(audited.result.manifest_path),
                          "source_commit": audited.manifest.environment.code_commit,
                          "completed_steps": audited.manifest.summary.completed_steps})
    require(completed, "No completed real Adapter is available")
    return {"source_data": str(source), "source_db_sha256": sha256(database), "seed_tasks": completed}


def copy_source(source, destination, inspected):
    require(not destination.exists(), "Destination must be new")
    require(inspect_source(source) == inspected, "Source changed before copy")
    destination.mkdir(mode=0o700)
    with readonly_database(source / "llmcloud.db") as original:
        with closing(sqlite3.connect(destination / "llmcloud.db")) as snapshot:
            original.backup(snapshot)
    for name in ("datasets", "outputs"):
        shutil.copytree(source / name, destination / name, symlinks=False)
        for original in (source / name).rglob("*"):
            if original.is_file():
                copied = destination / original.relative_to(source)
                require(sha256(original) == sha256(copied), "Copied file differs from original")
    require(inspect_source(source) == inspected, "Source changed during copy")
    copied = inspect_source(destination)
    require(copied["seed_tasks"] == inspected["seed_tasks"], "Copied Adapter audit differs")
    return copied


class InferenceSession(Acceptance):
    def __init__(self, *args, evidence, seed, smoke=False, **kwargs):
        self.evidence, self.seed, self.smoke = evidence, seed, smoke
        super().__init__(*args, **kwargs)
        self.settings.training_queue = "m5-local-" + self.root.name
        self.report.update(scope="M5 local real inference; human confirmation pending",
            source=seed, seeded_historical_tasks=True, inference_verified=False,
            human_review="pending", browser="user-owned Windows browser; no browser robot")

    def save(self):
        super().save()
        write(self.evidence / "report.json", self.report)

    async def training_tasks(self):
        items, page = [], 1
        while True:
            response = await self.client.get(f"/api/v1/tasks?page={page}&page_size=100")
            response.raise_for_status()
            body = response.json()
            items.extend(body["items"])
            if page >= body["total_pages"]:
                return items
            page += 1

    def active_inference(self):
        with readonly_database(self.settings.data_dir / "llmcloud.db") as connection:
            return connection.execute("SELECT COUNT(*) FROM inference_jobs WHERE state IN ('WAITING','RUNNING')").fetchone()[0]

    async def capture(self):
        tasks = [await self.detail(task["id"]) for task in await self.training_tasks()]
        self.report["tasks"] = tasks
        seeded = {item["task_id"] for item in self.seed["seed_tasks"]}
        for task in tasks:
            if task["status"] != "COMPLETED":
                continue
            task_id = task["id"]
            output = self.settings.data_dir / "outputs" / task_id
            completed = self.app.state.task_repository.get_completed_artifact(task_id)
            if task_id in seeded:
                audited = verify_training_artifacts(output, outputs_root=output.parent,
                    expected_task_id=task_id, expected_revision=DEFAULT_MODEL_REVISION)
                require(completed.manifest_sha256 == sha256(output / "manifest.json") and
                    completed.training_summary == audited.manifest.summary, "Seed SQL/artifact mismatch")
                self.report["artifacts"][task_id] = {**audited.summary(), "historical_seed": True,
                    "training_code_commit": audited.manifest.environment.code_commit}
            else:
                self.report["artifacts"][task_id] = audit_gpu_output(output, task, completed,
                    revision=DEFAULT_MODEL_REVISION, steps=self.settings.training_max_steps,
                    commit=self.report["baseline"]["commit"])
        self.save()

    async def manual(self, seconds):
        schema = (await self.client.get("/openapi.json")).json()
        require("post" in schema["paths"].get("/api/v1/inference", {}), "Inference route not published")
        # Admission-only probes never dispatch a GPU job or alter training state.
        missing = {"task_id": "00000000-0000-4000-8000-000000000000", "prompt": "检查", "mode": "compare"}
        invalid = await self.client.post("/api/v1/inference", json={**missing, "max_new_tokens": 257})
        require(invalid.status_code == 422, "Invalid inference input was not rejected")
        absent = await self.client.post("/api/v1/inference", json=missing)
        require(absent.status_code == 404 and absent.json()["error"]["code"] == "TASK_NOT_FOUND",
                "Missing task error differs from contract")
        await self.capture()
        self.report["admission_preflight"] = {"openapi": True, "invalid_input": 422, "missing_task": 404}
        if self.smoke:
            self.report.update(status="isolated_services_smoke_passed", real_generation=False)
            self.save()
            return
        await self.start_worker()
        for _ in range(300):
            require(self.worker.poll() is None, "Worker exited; inspect runtime worker log")
            if " ready." in self.worker_log.read_text(errors="replace"):
                break
            await asyncio.sleep(0.1)
        else:
            raise TimeoutError("Worker readiness timed out")
        stop_file = self.root / "STOP_REQUESTED"
        ready = {"stage": "m5_inference_services", "status": "ready_for_manual_browser",
            "browser_url": self.front_url + "/#inference", "api_url": self.api_url,
            "runtime_dir": str(self.root), "evidence_dir": str(self.evidence),
            "stop_command": f"touch -- '{stop_file}'", "worker_pid": self.worker.pid,
            "seed_task_ids": [item["task_id"] for item in self.seed["seed_tasks"]],
            "training_max_steps_for_new_tasks": self.settings.training_max_steps,
            "real_generation": False, "joint_acceptance": "pending"}
        write(self.evidence / "ready.json", ready)
        self.report.update(status="manual_inference_session_open", worker_pid=self.worker.pid)
        self.save()
        print("RETURN_TO_CODEX_BEGIN\n" + json.dumps(ready, ensure_ascii=False, indent=2) + "\nRETURN_TO_CODEX_END", flush=True)
        deadline, noted = time.monotonic() + seconds, False
        while True:
            require(self.worker.poll() is None and self.vite.poll() is None and not self.api.done(),
                    "A service exited; retain logs for review")
            if stop_file.exists() or time.monotonic() >= deadline:
                tasks = await self.training_tasks()
                if not any(task["status"] in ("PENDING", "QUEUED", "RUNNING") for task in tasks) and not self.active_inference():
                    await self.capture()
                    self.report["status"] = "manual_session_closed_pending_review"
                    self.save()
                    return
                if not noted:
                    print("Stop requested: waiting for training and inference GPU cleanup.", flush=True)
                    noted = True
            await asyncio.sleep(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--start", action="store_true")
    action.add_argument("--smoke-services", action="store_true")
    parser.add_argument("--source-data", type=Path, required=True)
    args = parser.parse_args()
    os.chdir(REPO)
    report_repo = Path(os.environ.get("LLMCLOUD_REPORT_REPO", str(Path(__file__).resolve().parents[2]))).resolve()
    require(report_repo.is_dir(), "Report checkout missing")
    version = (REPO / "frontend/.node-version").read_text().strip()
    node_bin = Path.home() / f".local/share/llmcloud-tools/node-v{version}-linux-x64/bin"
    os.environ["PATH"] = f"{node_bin}:{Path.home() / '.local/bin'}:{os.environ.get('PATH', '')}"
    os.environ.update(HF_HOME=str(REPO / "data/models/huggingface"),
        HF_HUB_CACHE=str(REPO / "data/models/huggingface/hub"), HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1", TMPDIR="/tmp")
    for command in ("node", "npm", "redis-server"):
        require(shutil.which(command), f"Missing {command}")
    require((REPO / "frontend/node_modules/.bin/vite").exists(), "Frontend dependencies missing")
    baseline = code_baseline()
    require(not baseline["working_tree_dirty"], "Keep runtime checkout clean")
    source = args.source_data.expanduser().absolute()
    allowed = REPO / "data/acceptance/m4-07"
    require(source.parent.parent == allowed and source.name == "data", "Use an existing local M4 runtime data directory")
    inspected = inspect_source(source)
    shared, paths = Settings(), resolve_model_paths()
    if args.check:
        print(json.dumps({"status": "inference_launcher_ready", "baseline": baseline, "source": inspected,
            "model_cache": str(paths.cache_dir), "shared_lock": str(shared.log_dir / "worker.lock"),
            "services_started": False, "real_generation": False}, ensure_ascii=False, indent=2))
        return
    with WorkerInstanceLock(shared.log_dir):
        verify_model_cache(paths.cache_dir, DEFAULT_MODEL_REVISION)
    parent = report_repo / "data/acceptance/b-review/laptop-3060"
    parent.mkdir(parents=True, exist_ok=True)
    evidence = Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-m5-", dir=parent))
    root = new_run_directory(REPO / "data/acceptance/m5-inference")
    runner_path = Path(__file__).resolve()
    shutil.copyfile(runner_path, evidence / "runner-used.py")
    write(evidence / "metadata.json", {"baseline": baseline, "runtime_dir": str(root),
        "runner_sha256": sha256(runner_path), "source": inspected, "real_generation": False})
    copied = copy_source(source, root / "data", inspected)
    write(root / "seed-copy.json", copied)
    runner = InferenceSession(root, shared, paths, steps=200, timeout=600, baseline=baseline,
        evidence=evidence, seed=inspected, smoke=args.smoke_services)
    runner.save()
    try:
        with tempfile.TemporaryDirectory(prefix="m5-local-") as socket_dir:
            asyncio.run(runner.run(Path(socket_dir), manual_seconds=7200))
    except BaseException as error:
        runner.report.update(status="interrupted_pending_review", error_type=type(error).__name__)
        raise
    finally:
        runner.report["finished_at"] = datetime.now(timezone.utc).isoformat()
        runner.report["source_unchanged"] = inspect_source(source) == inspected
        runner.save()
        for path in root.glob("*.log"):
            if path.is_file() and path.stat().st_size <= 1024 * 1024:
                shutil.copyfile(path, evidence / path.name)
        (evidence / "SHA256SUMS").write_text("".join(
            f"{sha256(path)}  {path.name}\n" for path in sorted(evidence.iterdir())
            if path.is_file() and path.name != "SHA256SUMS"), encoding="utf-8")
    print(json.dumps({"status": runner.report["status"], "evidence_dir": str(evidence),
        "runtime_dir": str(root), "real_generation": runner.report.get("real_generation", False)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
