import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from backend.app.core.worker_lock import WorkerLockError
from celery.concurrency.solo import TaskPool
from celery.signals import worker_init, worker_shutdown
from worker.celery_app import celery_app, guard_worker_instance
from worker.instance_lock import (
    WorkerAlreadyRunning, WorkerInstanceLock, acquire_worker_lock, release_worker_lock,
)

ROOT = Path(__file__).resolve().parents[1]


class WorkerSender:
    pool_cls = TaskPool
    concurrency = 1
    prefetch_multiplier = 1


class WorkerInstanceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        release_worker_lock()
        self.addCleanup(release_worker_lock)

    def env(self):
        return {**os.environ, "LOG_DIR": str(self.root / "logs"), "DATA_DIR": str(self.root / "data"),
                "HF_HOME": str(self.root / "hf"), "REDIS_URL": "redis://127.0.0.1:1/0",
                "CELERY_RESULT_BACKEND": "redis://127.0.0.1:1/1", "PYTHONUTF8": "1"}

    def child(self, *args):
        return subprocess.run([sys.executable, *args], cwd=ROOT, env=self.env(),
                              capture_output=True, text=True, encoding="utf-8", timeout=15)

    def test_exclusive_nonblocking_lock_and_persistent_file(self):
        first = WorkerInstanceLock(self.root).acquire()
        try:
            self.assertIs(first.acquire(), first)
            with self.assertRaises(WorkerAlreadyRunning): WorkerInstanceLock(self.root).acquire()
            self.assertTrue(first.path.exists())
        finally: first.release()
        self.assertTrue(first.path.exists())
        with WorkerInstanceLock(self.root): pass

    def test_process_lock_is_idempotent_but_cannot_change_root(self):
        lock = acquire_worker_lock(self.root)
        self.assertIs(lock, acquire_worker_lock(self.root))
        with self.assertRaises(ValueError): acquire_worker_lock(self.root / "other")
        release_worker_lock()
        with WorkerInstanceLock(self.root): pass

    def test_os_releases_lock_after_process_is_killed(self):
        code = '''
import os, sys
from worker.instance_lock import WorkerInstanceLock
with WorkerInstanceLock(os.environ['LOG_DIR']):
    print('LOCKED', flush=True)
    sys.stdin.readline()
'''
        child = subprocess.Popen([sys.executable, "-c", code], cwd=ROOT, env=self.env(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        try:
            self.assertEqual(child.stdout.readline().strip(), "LOCKED")
            with self.assertRaises(WorkerAlreadyRunning): WorkerInstanceLock(self.root / "logs").acquire()
            child.terminate(); child.wait(timeout=5)
            with WorkerInstanceLock(self.root / "logs"): pass
        finally:
            if child.poll() is None: child.kill(); child.wait(timeout=5)
            child.stdin.close(); child.stdout.close(); child.stderr.close()

    def test_released_lock_object_is_not_mistaken_for_held_process_guard(self):
        lock = acquire_worker_lock(self.root)
        lock.release()
        with WorkerInstanceLock(self.root):
            with self.assertRaises(WorkerAlreadyRunning): acquire_worker_lock(self.root)

    def test_standard_entrypoint_refuses_second_process_before_broker_connection(self):
        with WorkerInstanceLock(self.root / "logs"):
            result = self.child("-m", "worker")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Worker 启动被拒绝", result.stderr + result.stdout)
        self.assertFalse((self.root / "data").exists())

    def test_direct_celery_cli_also_exits_instead_of_swallowing_lock_error(self):
        with WorkerInstanceLock(self.root / "logs"):
            result = self.child("-m", "celery", "-A", "worker.celery_app:celery_app", "worker",
                "--pool=solo", "--concurrency=1", "--loglevel=WARNING", "--without-gossip", "--without-mingle")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Worker 启动被拒绝", result.stderr + result.stdout)
        self.assertNotIn("Trying again", result.stderr + result.stdout)

    def test_signal_dispatch_cannot_swallow_duplicate_instance_rejection(self):
        with patch("worker.celery_app.get_settings", return_value=type("Settings", (), {"log_dir": self.root})()):
            with WorkerInstanceLock(self.root):
                with self.assertRaises(SystemExit): worker_init.send(sender=WorkerSender())

    def test_real_celery_worker_initialization_accepts_the_first_safe_instance(self):
        from celery import Celery
        app = Celery("isolated-lock-check", broker="memory://", backend="cache+memory://")
        app.conf.update(worker_pool="solo", worker_concurrency=1, worker_prefetch_multiplier=1)
        self.addCleanup(app.close)
        with patch("worker.celery_app.get_settings", return_value=type("Settings", (), {"log_dir": self.root})()):
            worker = app.Worker(pool="solo", concurrency=1, loglevel="ERROR",
                                without_gossip=True, without_mingle=True, without_heartbeat=True)
        with self.assertRaises(WorkerAlreadyRunning): WorkerInstanceLock(self.root).acquire()
        worker_shutdown.send(sender=worker)
        with WorkerInstanceLock(self.root): pass

    def test_wrapper_lock_and_signal_hook_share_one_process_lock_until_shutdown(self):
        acquire_worker_lock(self.root)
        with patch("worker.celery_app.get_settings", return_value=type("Settings", (), {"log_dir": self.root})()):
            guard_worker_instance(WorkerSender())
        with self.assertRaises(WorkerAlreadyRunning): WorkerInstanceLock(self.root).acquire()
        worker_shutdown.send(sender=WorkerSender())
        with WorkerInstanceLock(self.root): pass

    def test_unsafe_pool_concurrency_or_prefetch_is_rejected(self):
        for key, value in [("pool_cls", object), ("concurrency", 2), ("prefetch_multiplier", 4)]:
            sender = WorkerSender(); setattr(sender, key, value)
            with self.assertRaises(SystemExit): guard_worker_instance(sender)

    def test_celery_defaults_preserve_serial_early_ack_without_retries(self):
        self.assertEqual(celery_app.conf.worker_pool, "solo")
        self.assertEqual(celery_app.conf.worker_concurrency, 1)
        self.assertEqual(celery_app.conf.worker_prefetch_multiplier, 1)
        self.assertFalse(celery_app.conf.task_acks_late)
        self.assertFalse(celery_app.conf.task_reject_on_worker_lost)
        from worker.tasks import run_training
        self.assertEqual(run_training.max_retries, 0)
        self.assertFalse(run_training.acks_late)

    def test_lock_symlink_is_rejected_without_modifying_target(self):
        self.root.joinpath("target").write_bytes(b"keep")
        try: (self.root / "worker.lock").symlink_to(self.root / "target")
        except OSError: self.skipTest("Host does not allow creating symlinks")
        with self.assertRaises((ValueError, WorkerLockError)): WorkerInstanceLock(self.root).acquire()
        self.assertEqual(self.root.joinpath("target").read_bytes(), b"keep")


    @unittest.skipIf(os.name == "nt", "Reconciliation shared flock targets Linux")
    def test_linux_worker_reuses_shared_reconciliation_primitive(self):
        from backend.app.core.worker_lock import WorkerInstanceLock as SharedLock
        self.assertIsInstance(WorkerInstanceLock(self.root), SharedLock)
        with SharedLock(self.root):
            with self.assertRaises(WorkerAlreadyRunning): WorkerInstanceLock(self.root).acquire()
        with WorkerInstanceLock(self.root):
            with self.assertRaises(WorkerAlreadyRunning): SharedLock(self.root).acquire()

    @unittest.skipIf(os.name == "nt", "Reconciliation shared flock targets Linux")
    def test_worker_and_reconciliation_lock_exclude_other_process_in_both_directions(self):
        from backend.app.core.worker_lock import WorkerInstanceLock as SharedLock
        code = """
import os, sys
from backend.app.core.worker_lock import WorkerLockBusy
from MODULE import WorkerInstanceLock
try:
    with WorkerInstanceLock(os.environ['LOG_DIR']):
        sys.exit(9)
except WorkerLockBusy:
    print('BUSY')
"""
        for parent_class, child_module in (
                (WorkerInstanceLock, 'backend.app.core.worker_lock'),
                (SharedLock, 'worker.instance_lock')):
            with self.subTest(parent=parent_class.__module__):
                with parent_class(self.root / 'logs'):
                    result = self.child('-c', code.replace('MODULE', child_module))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), 'BUSY')
