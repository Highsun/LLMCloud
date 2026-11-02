"""Offline SQL/CPU artifact checks; synthetic bundles are not GPU evidence."""

from datetime import timedelta
import json
import os
from pathlib import Path
import select
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from backend.app.core.database import create_database_engine
from backend.app.core.task_contract import TaskStatus
from backend.app.core.worker_lock import WorkerInstanceLock, WorkerLockBusy, WorkerLockError
from backend.app.models.entities import TrainingTask, utcnow
from backend.app.services import task_reconciliation as reconciliation
from trainer.artifacts import inventory, verify_training_artifacts
from trainer.contracts import RuntimeOptions, TrainingFailure, TrainingSnapshot
from task_store_support import create_task, progress, setup_store
import test_training_artifacts as artifact_fixtures

ROOT = Path(__file__).resolve().parents[1]
TABLE = TrainingTask.__table__


class TaskReconciliationTests(unittest.TestCase):
    def setUp(self):
        setup_store(self)
        self.logs = self.root / "logs"

    def reconcile(self, **options):
        return reconciliation.reconcile_tasks(self.engine, self.data, self.logs, **options)

    def apply(self, **options):
        return self.reconcile(apply=True, services_stopped=True, **options)

    def running(self, *, config=None, runtime=None):
        created = create_task(self, config=config, runtime=runtime)
        token = uuid4()
        self.repo.claim(created.task.id, token, "synthetic-worker")
        return created, token

    def bundle(self, created):
        # Reuse the existing explicitly synthetic safetensors/tokenizer fixture.
        helper = artifact_fixtures.TrainingArtifactTests()
        helper.parent = self.data
        previous, manifest = helper.bundle()
        root = previous.with_name(str(created.task.id))
        previous.rename(root)
        with self.sessions.begin() as session:
            row = session.execute(TABLE.select().where(TABLE.c.id == str(created.task.id))).mappings().one()
            manifest = manifest.model_copy(update={"task_id": created.task.id,
                "train_dataset": manifest.train_dataset.model_copy(update={"sha256": row["dataset_sha256"],
                    "size_bytes": row["dataset_size_bytes"], "row_count": row["dataset_row_count"]})})
            # Fixture timestamps are real UTC values a few seconds in the past.
            session.execute(TABLE.update().where(TABLE.c.id == row["id"]).values(
                model_revision=manifest.model_revision,
                created_at=manifest.started_at - timedelta(seconds=2),
                started_at=manifest.started_at - timedelta(seconds=1) if row["status"] == TaskStatus.RUNNING else None))
        snapshot = TrainingSnapshot.model_validate({name: getattr(manifest, name) for name in TrainingSnapshot.model_fields})
        (root / "training_config.json").write_text(snapshot.model_dump_json() + "\n")
        manifest = manifest.model_copy(update={"artifacts": inventory(root)})
        (root / "manifest.json").write_text(manifest.model_dump_json() + "\n")
        verify_training_artifacts(root, expected_task_id=created.task.id)
        return root, manifest

    def cpu_run(self):
        return self.running(config={"lora_r": 1, "target_modules": ["q_proj"]}, runtime=RuntimeOptions(max_steps=2))

    def bytes(self, root):
        return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}

    def test_check_is_read_only_including_no_log_or_lock_creation(self):
        running, token = self.running()
        self.repo.record_progress(running.task.id, token, progress())
        waiting = create_task(self)
        before = self.bytes(self.root)
        result = self.reconcile()
        self.assertEqual(result["state"], "ready")
        self.assertEqual(len(result["items"]), 2)
        self.assertFalse(result["instance_lock_acquired"])
        self.assertFalse(result["services_stopped_acknowledged"])
        self.assertEqual(before, self.bytes(self.root))
        self.assertEqual(self.repo.get_status(running.task.id), TaskStatus.RUNNING)
        self.assertEqual(self.repo.get_status(waiting.task.id), TaskStatus.PENDING)
        self.assertFalse(self.logs.exists())

    def test_running_and_queued_fail_without_resetting_progress_or_files(self):
        running, token = self.running()
        self.repo.record_progress(running.task.id, token, progress())
        original = self.repo.get_detail(running.task.id)
        pending, queued = create_task(self), create_task(self)
        self.repo.mark_queued(queued.task.id)
        partial = self.data / f"outputs/{running.task.id}/checkpoints/partial"
        partial.parent.mkdir(parents=True)
        partial.write_text("preserve")
        result = self.apply()
        self.assertEqual((result["state"], result["applied_count"]), ("applied", 3))
        after = self.repo.get_detail(running.task.id)
        self.assertEqual((after.status, after.error_code, after.current_step, after.total_steps, after.progress),
                         (TaskStatus.FAILED, "WORKER_INTERRUPTED", 1, 2, 0.5))
        self.assertEqual(after.started_at, original.started_at)
        self.assertEqual(partial.read_text(), "preserve")
        for task in (pending, queued):
            after = self.repo.get_detail(task.task.id)
            self.assertEqual((after.status, after.error_code, after.progress), (TaskStatus.FAILED, "TASK_ABANDONED", None))
            self.assertIsNone(self.repo.claim(task.task.id, uuid4(), "late-duplicate-message"))
        audit = Path(result["audit_log"])
        self.assertEqual(audit.stat().st_mode & 0o777, 0o600)
        events = [json.loads(line) for line in audit.read_text().splitlines()]
        self.assertEqual([event["event"] for event in events].count("applied"), 3)
        self.assertEqual(events[-1]["report"]["state"], "applied")
        self.assertNotIn("claim_token", audit.read_text())
        before = self.database.read_bytes()
        self.assertEqual(self.apply()["state"], "current")
        self.assertEqual(before, self.database.read_bytes())

    def test_valid_running_bundle_recovers_completion_from_real_auditor(self):
        created, token = self.cpu_run()
        root, manifest = self.bundle(created)
        self.repo.record_progress(created.task.id, token, progress())
        before = self.bytes(root)
        checked = self.reconcile()
        self.assertEqual(checked["items"][0]["to_status"], "COMPLETED")
        self.assertEqual(self.repo.get_status(created.task.id), TaskStatus.RUNNING)
        result = self.apply()
        self.assertEqual(result["state"], "applied")
        detail = self.repo.get_detail(created.task.id)
        self.assertEqual((detail.status, detail.current_step, detail.total_steps, detail.progress), (TaskStatus.COMPLETED, 2, 2, 1.0))
        self.assertEqual(detail.finished_at, manifest.finished_at)
        with self.sessions.begin() as session:
            row = session.execute(TABLE.select()).mappings().one()
        self.assertEqual(row["claim_token"], str(token))
        self.assertEqual(row["output_path"], f"outputs/{created.task.id}")
        self.assertEqual(row["training_summary"], manifest.summary.model_dump(mode="json"))
        self.assertEqual(before, self.bytes(root))
        self.assertFalse(self.repo.fail(created.task.id, token, TrainingFailure(code="TRAINING_FAILED", stage="training", message="late")))
        self.assertEqual(self.reconcile()["state"], "current")

    def test_unknown_steps_can_be_restored_but_never_invented_without_bundle(self):
        created, _ = self.cpu_run()
        self.bundle(created)
        self.assertIsNone(self.repo.get_detail(created.task.id).total_steps)
        self.assertEqual(self.apply()["state"], "applied")
        self.assertEqual(self.repo.get_detail(created.task.id).total_steps, 2)

    def test_mismatching_config_runtime_dataset_or_progress_is_not_success(self):
        for mismatch in ("config", "runtime", "hash", "size", "rows", "steps"):
            with self.subTest(mismatch=mismatch):
                created, _ = self.cpu_run()
                root, _manifest = self.bundle(created)
                changes = {
                    "config": {"training_config": {**created.task.config.model_dump(), "lora_alpha": 32}},
                    "runtime": {"runtime_options": RuntimeOptions(precision="fp32", max_steps=2).model_dump()},
                    "hash": {"dataset_sha256": "c" * 64}, "size": {"dataset_size_bytes": 999},
                    "rows": {"dataset_row_count": 9}, "steps": {"total_steps": 3, "current_step": 1, "progress": 1 / 3},
                }[mismatch]
                with self.sessions.begin() as session:
                    session.execute(TABLE.update().where(TABLE.c.id == str(created.task.id)).values(**changes))
                result = self.apply(task_ids=[created.task.id])
                self.assertEqual(result["items"][0]["reason"], "artifact_snapshot_mismatch")
                self.assertEqual(self.repo.get_detail(created.task.id).error_code, "WORKER_INTERRUPTED")
                self.assertTrue((root / "manifest.json").exists())

    def test_corrupt_or_missing_deliverable_is_failed_and_preserved(self):
        for corruption in ("tensor", "manifest"):
            created, _ = self.cpu_run()
            root, _manifest = self.bundle(created)
            path = root / ("adapter/adapter_model.safetensors" if corruption == "tensor" else "manifest.json")
            path.write_bytes(b"broken")
            self.assertEqual(self.apply(task_ids=[created.task.id])["state"], "applied")
            self.assertEqual(self.repo.get_detail(created.task.id).error_code, "WORKER_INTERRUPTED")
            self.assertEqual(path.read_bytes(), b"broken")

    def test_unclaimed_success_bundle_blocks_instead_of_inventing_an_owner(self):
        created = create_task(self, config={"lora_r": 1, "target_modules": ["q_proj"]}, runtime=RuntimeOptions(max_steps=2))
        root, _manifest = self.bundle(created)
        other = create_task(self)
        result = self.apply()
        self.assertEqual(result["state"], "blocked")
        self.assertIn("unclaimed_success_artifacts", [item["reason"] for item in result["items"]])
        self.assertEqual(self.repo.get_status(created.task.id), TaskStatus.PENDING)
        self.assertEqual(self.repo.get_status(other.task.id), TaskStatus.PENDING)
        self.assertTrue((root / "manifest.json").exists())
        self.assertIsNone(result["audit_log"])

    def test_terminal_records_are_never_reopened_even_with_new_artifacts(self):
        created, token = self.running()
        self.repo.fail(created.task.id, token, TrainingFailure(code="TRAINING_FAILED", stage="training", message="safe"))
        original = self.repo.get_detail(created.task.id)
        with patch.object(reconciliation, "verify_training_artifacts", side_effect=AssertionError("Terminal file IO")):
            self.assertEqual(self.apply()["state"], "current")
        self.assertEqual(self.repo.get_detail(created.task.id), original)

    def test_apply_requires_shutdown_acknowledgement_before_any_side_effect(self):
        create_task(self)
        before = self.bytes(self.root)
        result = self.reconcile(apply=True)
        self.assertEqual(result["code"], "services_stopped_required")
        self.assertEqual(before, self.bytes(self.root))

    def test_selected_ids_do_not_modify_other_tasks_and_missing_id_blocks(self):
        a, b = create_task(self), create_task(self)
        self.assertEqual(self.apply(task_ids=[a.task.id])["applied_count"], 1)
        self.assertEqual(self.repo.get_status(b.task.id), TaskStatus.PENDING)
        result = self.apply(task_ids=[b.task.id, uuid4()])
        self.assertEqual(result["state"], "blocked")
        self.assertEqual(self.repo.get_status(b.task.id), TaskStatus.PENDING)

    def test_sql_snapshot_change_after_audit_blocks_cas(self):
        created = create_task(self)
        original_update = reconciliation._update
        def race(connection, item):
            self.repo.mark_queued(created.task.id)
            return original_update(connection, item)
        with patch.object(reconciliation, "_update", side_effect=race):
            result = self.apply()
        self.assertEqual(result["state"], "blocked")
        self.assertEqual(result["items"][0]["outcome"], "database_changed")
        self.assertEqual(self.repo.get_status(created.task.id), TaskStatus.QUEUED)

    def test_claim_token_change_preserves_the_new_owner(self):
        created, _ = self.running()
        token = str(uuid4())
        update = reconciliation._update
        def race(connection, item):
            with self.sessions.begin() as session:
                session.execute(TABLE.update().where(TABLE.c.id == str(created.task.id)).values(claim_token=token))
            return update(connection, item)
        with patch.object(reconciliation, "_update", side_effect=race):
            result = self.apply()
        self.assertEqual(result["items"][0]["outcome"], "database_changed")
        self.assertEqual(self.repo.get_status(created.task.id), TaskStatus.RUNNING)
        with self.sessions.begin() as session:
            self.assertEqual(session.execute(TABLE.select()).mappings().one()["claim_token"], token)

    def test_artifacts_change_between_plan_and_write_blocks_apply(self):
        created, _ = self.cpu_run()
        root, _manifest = self.bundle(created)
        inspect = reconciliation._inspect
        count = 0
        def change(row, data_dir, now):
            nonlocal count
            count += 1
            if count == 2:
                (root / "manifest.json").unlink()
            return inspect(row, data_dir, now)
        with patch.object(reconciliation, "_inspect", side_effect=change):
            result = self.apply()
        self.assertEqual(result["items"][0]["outcome"], "artifacts_changed")
        self.assertEqual(self.repo.get_status(created.task.id), TaskStatus.RUNNING)

    def test_failed_commit_rolls_back_and_never_falls_back_to_another_state(self):
        created, _ = self.cpu_run()
        root, _manifest = self.bundle(created)
        with patch.object(reconciliation, "_commit", side_effect=sqlite3.OperationalError("private path")):
            result = self.apply()
        self.assertEqual(result["state"], "uncertain")
        self.assertEqual(self.repo.get_status(created.task.id), TaskStatus.RUNNING)
        self.assertNotIn("private path", json.dumps(result))
        self.assertTrue((root / "manifest.json").exists())

    def test_lost_commit_reply_preserves_completed_and_next_check_is_idempotent(self):
        created, _ = self.cpu_run()
        self.bundle(created)
        def lost_reply(connection):
            connection.commit()
            raise sqlite3.OperationalError("injected lost confirmation")
        with patch.object(reconciliation, "_commit", side_effect=lost_reply):
            result = self.apply()
        self.assertEqual(result["state"], "uncertain")
        self.assertEqual(self.repo.get_status(created.task.id), TaskStatus.COMPLETED)
        self.assertEqual(self.reconcile()["state"], "current")

    def test_audit_open_failure_prevents_db_writes_and_releases_lock(self):
        created = create_task(self)
        original = os.open
        def denied(path, *args, **kwargs):
            if Path(path).name.startswith("reconciliation-"):
                raise PermissionError("private diagnostic")
            return original(path, *args, **kwargs)
        with patch.object(reconciliation.os, "open", side_effect=denied):
            result = self.apply()
        self.assertEqual(result["state"], "error")
        self.assertEqual(self.repo.get_status(created.task.id), TaskStatus.PENDING)
        with WorkerInstanceLock(self.logs):
            pass
        self.assertNotIn("private diagnostic", json.dumps(result))

    def test_audit_fsync_failure_after_commit_reports_uncertain_without_reverting(self):
        created = create_task(self)
        fsync = os.fsync
        count = 0
        def failure(descriptor):
            nonlocal count
            count += 1
            if count == 3:  # plan and intent were durable; DB update already committed.
                raise OSError("injected audit failure")
            fsync(descriptor)
        with patch.object(reconciliation.os, "fsync", side_effect=failure):
            result = self.apply()
        self.assertEqual((result["state"], result["applied_count"]), ("uncertain", 1))
        self.assertEqual(self.repo.get_status(created.task.id), TaskStatus.FAILED)
        self.assertEqual(self.reconcile()["state"], "current")

    def test_partial_apply_reports_prior_commits_and_stops_after_conflict(self):
        tasks = [create_task(self) for _ in range(3)]
        update = reconciliation._update
        count = 0
        def conflict(connection, item):
            nonlocal count
            count += 1
            return False if count == 2 else update(connection, item)
        with patch.object(reconciliation, "_update", side_effect=conflict):
            result = self.apply()
        self.assertEqual((result["state"], result["applied_count"]), ("partial", 1))
        self.assertEqual(self.repo.get_status(tasks[0].task.id), TaskStatus.FAILED)
        for task in tasks[1:]:
            self.assertEqual(self.repo.get_status(task.task.id), TaskStatus.PENDING)

    def test_corrupt_sql_or_unsafe_output_root_blocks_without_writes(self):
        task = create_task(self)
        with self.sessions.begin() as session:
            session.execute(TABLE.update().values(training_config={"unexpected": True}))
        self.assertEqual(self.apply()["state"], "blocked")
        with self.sessions.begin() as session:
            session.execute(TABLE.update().values(training_config=task.task.config.model_dump()))
        outside = self.root / "outside"
        outside.mkdir()
        (self.data / "outputs").symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.apply()["items"][0]["reason"], "unsafe_output_path")
        self.assertEqual(self.repo.get_status(task.task.id), TaskStatus.PENDING)
        self.assertEqual(list(outside.iterdir()), [])

    def test_missing_database_is_not_created_and_old_schema_is_not_migrated(self):
        missing = self.root / "missing.sqlite3"
        engine = create_database_engine(f"sqlite:///{missing}")
        try:
            self.assertEqual(reconciliation.reconcile_tasks(engine, self.data, self.logs)["state"], "not_initialized")
            self.assertFalse(missing.exists())
        finally:
            engine.dispose()
        with sqlite3.connect(self.database) as connection:
            connection.execute("ALTER TABLE training_tasks ADD COLUMN unexpected TEXT")
        before = self.database.read_bytes()
        self.assertEqual(self.apply()["code"], "task_schema_migration_required")
        self.assertEqual(before, self.database.read_bytes())

    def test_cli_defaults_to_check_and_apply_uses_same_guard(self):
        created = create_task(self)
        args = [sys.executable, "scripts/reconcile_tasks.py", "--database-url", str(self.engine.url),
                "--data-dir", str(self.data), "--log-dir", str(self.logs)]
        checked = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(json.loads(checked.stdout)["state"], "ready")
        invalid = subprocess.run([*args, "--task-id", "../invalid"], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(invalid.returncode, 2)
        self.assertFalse(self.logs.exists())
        rejected = subprocess.run([*args, "--apply"], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(rejected.returncode, 2)
        self.assertEqual(self.repo.get_status(created.task.id), TaskStatus.PENDING)
        applied = subprocess.run([*args, "--apply", "--services-stopped"], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(json.loads(applied.stdout)["state"], "applied")

    def test_cold_import_and_cli_check_do_not_load_gpu_worker_or_transport(self):
        code = '''
import importlib.abc, runpy, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'worker', 'torch', 'numpy', 'transformers', 'datasets', 'peft', 'trl',
            'accelerate', 'celery', 'kombu', 'redis', 'huggingface_hub'} or fullname == 'trainer.train':
            raise AssertionError(fullname)
sys.meta_path.insert(0, Block())
sys.argv = ['scripts/reconcile_tasks.py', '--check', '--database-url', sys.argv[1]]
runpy.run_path('scripts/reconcile_tasks.py', run_name='__main__')
'''
        result = subprocess.run([sys.executable, "-c", code, f"sqlite:///{self.root / 'absent.db'}"],
                                cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)


class ProcessLockTests(unittest.TestCase):
    def setUp(self):
        setup_store(self)
        self.logs = self.root / "logs"

    def test_same_process_contention_release_and_no_unlink(self):
        lock = WorkerInstanceLock(self.logs)
        with lock:
            self.assertIs(lock.acquire(), lock)
            inode = lock.path.stat().st_ino
            with self.assertRaises(WorkerLockBusy):
                WorkerInstanceLock(self.logs).acquire()
        with WorkerInstanceLock(self.logs) as again:
            self.assertEqual(again.path.stat().st_ino, inode)
        self.assertTrue(lock.path.exists())

    def test_linked_and_hardlinked_lock_files_are_rejected(self):
        self.logs.mkdir()
        outside = self.root / "outside"
        outside.write_text("preserve")
        lock = WorkerInstanceLock(self.logs)
        lock.path.symlink_to(outside)
        with self.assertRaises(WorkerLockError):
            lock.acquire()
        lock.path.unlink()
        os.link(outside, lock.path)
        with self.assertRaises(WorkerLockError):
            lock.acquire()
        self.assertEqual(outside.read_text(), "preserve")

    def test_live_process_blocks_apply_and_abrupt_exit_releases_lock(self):
        created = create_task(self)
        # Real child/OS lock/SQL claim; deliberately NOT a Celery/GPU Worker.
        code = '''
from backend.app.core.worker_lock import WorkerInstanceLock
from backend.app.core.database import create_database_engine
from backend.app.services.task_repository import SqlTaskRepository
from sqlalchemy.orm import sessionmaker
from uuid import uuid4
import os, sys
with WorkerInstanceLock(sys.argv[1]):
    engine = create_database_engine(sys.argv[2])
    SqlTaskRepository(sessionmaker(bind=engine)).claim(sys.argv[3], uuid4(), 'subprocess-interruption-test')
    print('claimed-and-locked', flush=True)
    sys.stdin.readline()
    os._exit(17)
'''
        process = subprocess.Popen([sys.executable, "-c", code, str(self.logs), str(self.engine.url), str(created.task.id)],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertTrue(select.select([process.stdout], [], [], 10)[0], "Child process did not become ready")
            self.assertEqual(process.stdout.readline().strip(), "claimed-and-locked")
            before = self.repo.get_detail(created.task.id)
            result = reconciliation.reconcile_tasks(self.engine, self.data, self.logs, apply=True, services_stopped=True)
            self.assertEqual(result["code"], "instance_lock_busy")
            self.assertEqual(self.repo.get_detail(created.task.id), before)
            # Even an online check only proposes; it does not kill a loading task.
            self.assertEqual(reconciliation.reconcile_tasks(self.engine, self.data, self.logs)["state"], "ready")
            process.communicate("exit\n", timeout=10)
            self.assertEqual(process.returncode, 17)
            result = reconciliation.reconcile_tasks(self.engine, self.data, self.logs, apply=True, services_stopped=True)
            self.assertEqual(result["state"], "applied")
            self.assertEqual(self.repo.get_detail(created.task.id).error_code, "WORKER_INTERRUPTED")
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)


if __name__ == "__main__":
    unittest.main()
