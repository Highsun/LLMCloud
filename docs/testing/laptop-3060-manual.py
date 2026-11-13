"""Local human-operated session; reuse production service tools without Playwright."""

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

REPO = Path(os.environ.get("LLMCLOUD_TEST_REPO", str(Path.home() / "LLMCloud"))).expanduser().resolve()
sys.path.insert(0, str(REPO))

from backend.app.core.config import Settings
from backend.app.core.task_contract import DEFAULT_MODEL_REVISION
from backend.app.core.worker_lock import WorkerInstanceLock
from scripts.check_m4_acceptance import Acceptance, code_baseline
from scripts.m4_acceptance_support import new_run_directory, require
from trainer.model_cache import resolve_model_paths, verify_model_cache


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class LocalSession(Acceptance):
    """Only the local human-session wait/stop protocol differs from the shared tool."""

    def __init__(self, *args, evidence, smoke=False, **kwargs):
        self.evidence, self.smoke = evidence, smoke
        super().__init__(*args, **kwargs)
        self.report.update(scope="laptop-3060-local-human-session",
                           browser="user-owned Windows browser; no Playwright",
                           evidence_dir=str(evidence), local_human_review="pending")

    def save(self):
        super().save()
        write(self.evidence / "report.json", self.report)

    async def task_ids(self):
        ids, page = [], 1
        while True:
            response = await self.client.get(f"/api/v1/tasks?page={page}&page_size=100")
            response.raise_for_status()
            body = response.json()
            ids.extend(item["id"] for item in body["items"])
            if page >= body["total_pages"]:
                return ids
            page += 1

    async def manual(self, seconds):
        # A service-only rehearsal never starts a Worker or submits a task.
        if self.smoke:
            response = await self.client.get("/api/v1/datasets")
            require(response.status_code == 200, "Dataset API did not become ready")
            require(await self.task_ids() == [], "A new run must contain no tasks")
            self.report.update(status="service_smoke_passed", real_training=False)
            self.save()
            return
        await self.start_worker()
        for _ in range(300):
            require(self.worker.poll() is None, "Worker exited; inspect the runtime worker log")
            if " ready." in self.worker_log.read_text(errors="replace"):
                break
            await asyncio.sleep(0.1)
        else:
            raise TimeoutError("Worker readiness timed out")
        stop_file = self.root / "STOP_REQUESTED"
        ready = {
            "stage": "local_platform_services", "status": "ready_for_manual_browser",
            "browser_url": self.front_url, "api_url": self.api_url,
            "runtime_dir": str(self.root), "evidence_dir": str(self.evidence),
            "stop_command": f"touch -- '{stop_file}'",
            "worker_pid": self.worker.pid, "max_steps": self.settings.training_max_steps,
            "real_training": False, "joint_human_acceptance": "pending",
            "instruction": "Open the URL in your Windows browser; report readiness before uploading or submitting.",
        }
        write(self.evidence / "ready.json", ready)
        self.report.update(status="local_manual_session_open", worker_pid=self.worker.pid,
                           stop_request_file=str(stop_file))
        self.save()
        print("RETURN_TO_CODEX_BEGIN", flush=True)
        print(json.dumps(ready, ensure_ascii=False, indent=2), flush=True)
        print("RETURN_TO_CODEX_END", flush=True)
        print("Keep this terminal open. To finish, run stop_command in another Ubuntu terminal; avoid Ctrl+C.", flush=True)
        deadline = time.monotonic() + seconds
        waiting = False
        while True:
            require(self.worker.poll() is None, "Worker exited; keep the runtime directory for investigation")
            require(self.vite.poll() is None, "Frontend exited; inspect vite.log")
            require(self.api is not None and not self.api.done(), "API exited")
            if stop_file.exists() or time.monotonic() >= deadline:
                ids = await self.task_ids()
                tasks = [await self.detail(task_id) for task_id in ids]
                unfinished = [x["id"] for x in tasks if x["status"] in ("PENDING", "QUEUED", "RUNNING")]
                if not unfinished:
                    # Capture while the API is still alive, then inherited run() cleans up.
                    await self.capture(ids)
                    self.report.update(status="local_session_closed_pending_review",
                                       real_training=bool(self.report["artifacts"]),
                                       gpu_execution_verified=bool(self.report["artifacts"]))
                    self.save()
                    return
                if not waiting:
                    print("Stop requested: waiting for active/queued tasks to finish before closing services.", flush=True)
                    waiting = True
            await asyncio.sleep(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--start", action="store_true")
    mode.add_argument("--smoke-services", action="store_true")
    parser.add_argument("--max-steps", type=int, default=40,
                        help="Internal real optimizer steps (5..200); no change to the public API")
    args = parser.parse_args()
    if not 5 <= args.max_steps <= 200:
        parser.error("--max-steps must be between 5 and 200")
    os.chdir(REPO)
    report_repo = Path(os.environ.get("LLMCLOUD_REPORT_REPO", str(Path(__file__).resolve().parents[2]))).expanduser().resolve()
    require(report_repo.is_dir(), "Report repository must already exist")
    version = (REPO / "frontend/.node-version").read_text().strip()
    node_bin = Path.home() / f".local/share/llmcloud-tools/node-v{version}-linux-x64/bin"
    os.environ["PATH"] = f"{node_bin}:{Path.home() / '.local/bin'}:{os.environ.get('PATH', '')}"
    os.environ.update(HF_HOME=str(REPO / "data/models/huggingface"),
                      HF_HUB_CACHE=str(REPO / "data/models/huggingface/hub"),
                      HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TMPDIR="/tmp")
    for command in ("node", "npm", "redis-server"):
        require(shutil.which(command), f"Missing {command}")
    require((REPO / "frontend/node_modules/.bin/vite").exists(), "Missing existing frontend dependencies")
    baseline = code_baseline()
    require(not baseline["working_tree_dirty"], "Keep the E-backed Linux runtime checkout clean")
    shared, paths = Settings(), resolve_model_paths()
    # Read-only inspection does not create evidence, acquire a lock, or start services.
    if args.check:
        print(json.dumps({"status": "launcher_ready", "repo": str(REPO), "report_repo": str(report_repo), "baseline": baseline,
                          "model_cache": str(paths.cache_dir), "shared_lock": str(shared.log_dir / "worker.lock"),
                          "max_steps": args.max_steps,
                          "playwright_required": False, "services_started": False, "real_training": False}))
        return
    with WorkerInstanceLock(shared.log_dir):
        verify_model_cache(paths.cache_dir, DEFAULT_MODEL_REVISION)
    parent = report_repo / "data/acceptance/b-review/laptop-3060"
    parent.mkdir(parents=True, exist_ok=True)
    evidence = Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-manual-", dir=parent))
    root = new_run_directory(REPO / "data/acceptance/m4-07")
    source = Path(__file__).resolve()
    (evidence / "runner-used.py").write_bytes(source.read_bytes())
    write(evidence / "metadata.json", {"started_at_utc": datetime.now(timezone.utc).isoformat(),
          "baseline": baseline, "runtime_dir": str(root), "runner_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
          "mode": "service_smoke" if args.smoke_services else "human_browser_session",
          "max_steps": args.max_steps,
          "playwright_required": False})
    runner = LocalSession(root, shared, paths, steps=args.max_steps, timeout=600, baseline=baseline,
                          evidence=evidence, smoke=args.smoke_services)
    runner.save()
    print(f"EVIDENCE_DIR={evidence}\nRUNTIME_DIR={root}", flush=True)
    try:
        with tempfile.TemporaryDirectory(prefix="l3060-") as directory:
            asyncio.run(runner.run(Path(directory), manual_seconds=7200))
    except BaseException as error:
        runner.report.update(status="interrupted_pending_review" if isinstance(error, KeyboardInterrupt) else "failed",
                             error_type=type(error).__name__)
        raise
    finally:
        runner.report["finished_at"] = datetime.now(timezone.utc).isoformat()
        runner.save()
        # Only bounded text evidence is copied to D; data, DB, Adapter and ZIP stay on E.
        for path in [*root.glob("*.log"), *root.glob("*.json")]:
            if path.is_file() and not path.is_symlink() and path.stat().st_size <= 1024 * 1024 and path.name != "report.json":
                shutil.copyfile(path, evidence / path.name)
        hashes = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}" for p in sorted(evidence.iterdir())
                  if p.is_file() and p.name != "SHA256SUMS"]
        (evidence / "SHA256SUMS").write_text("\n".join(hashes) + "\n", encoding="utf-8")
    print(json.dumps({"status": runner.report["status"], "evidence_dir": str(evidence),
                      "runtime_dir": str(root), "joint_human_acceptance": "pending"}), flush=True)


if __name__ == "__main__":
    main()
