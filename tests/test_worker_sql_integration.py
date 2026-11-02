from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from backend.app.core.task_contract import ExecutionOutcome, TaskStatus
from trainer.contracts import RuntimeOptions
from worker.execution import execute_training
from task_store_support import create_task, setup_store
from worker_support import synthetic_train


class WorkerSqlIntegrationTests(unittest.TestCase):
    """Real disposable SQLite + real CPU artifact audit, synthetic training/cache."""
    def setUp(self):
        setup_store(self)
        self.settings = SimpleNamespace(data_dir=self.data, log_dir=self.root / "logs")
        self.created = create_task(self, config={"lora_r": 1, "target_modules": ["q_proj"]},
                                   runtime=RuntimeOptions(max_steps=2))
        self.trainer = Mock(side_effect=synthetic_train)
        for name, value in [("resolve_model_paths", SimpleNamespace(cache_dir=self.root / "cache")),
                            ("verify_model_cache", None)]:
            context = patch("worker.execution." + name, return_value=value)
            context.start(); self.addCleanup(context.stop)

    def run_task(self):
        return execute_training(self.created.task.id, self.repo, self.settings, self.trainer)

    def test_claim_callbacks_completion_and_duplicate_use_real_repository(self):
        self.assertEqual(self.run_task(), ExecutionOutcome.COMPLETED)
        task = self.repo.get_detail(self.created.task.id)
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertEqual(task.current_step, 2)
        self.assertEqual(task.progress, 1.0)
        self.assertEqual(self.run_task(), ExecutionOutcome.SKIPPED)
        self.assertEqual(self.trainer.call_count, 1)

    def test_training_failure_preserves_committed_progress(self):
        from trainer.contracts import TrainingError, TrainingFailure
        from task_store_support import progress
        def train(request, on_progress):
            on_progress(progress(1))
            raise TrainingError(TrainingFailure(code="TRAINING_FAILED", stage="training", message="测试失败。"))
        self.trainer.side_effect = train
        self.assertEqual(self.run_task(), ExecutionOutcome.FAILED)
        task = self.repo.get_detail(self.created.task.id)
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.current_step, 1)
        self.assertEqual(task.error_code, "TRAINING_FAILED")

    def test_actual_completion_ack_loss_is_read_back_as_completed(self):
        original = self.repo.complete
        def lost_ack(session):
            raise OperationalError("injected lost acknowledgement", {}, Exception())
        def complete(*args):
            event.listen(self.sessions.class_, "after_commit", lost_ack)
            try: return original(*args)
            finally: event.remove(self.sessions.class_, "after_commit", lost_ack)
        self.repo.complete = complete
        self.repo.fail = Mock(wraps=self.repo.fail)
        self.assertEqual(self.run_task(), ExecutionOutcome.COMPLETED)
        self.assertEqual(self.repo.get_status(self.created.task.id), TaskStatus.COMPLETED)
        self.repo.fail.assert_not_called()

    def test_actual_completion_rollback_keeps_valid_artifacts_and_running_state(self):
        original = self.repo.complete
        def fail_commit(session):
            raise OperationalError("injected before commit", {}, Exception())
        def complete(*args):
            event.listen(self.sessions.class_, "before_commit", fail_commit)
            try: return original(*args)
            finally: event.remove(self.sessions.class_, "before_commit", fail_commit)
        self.repo.complete = complete
        self.repo.fail = Mock(wraps=self.repo.fail)
        self.assertEqual(self.run_task(), ExecutionOutcome.RECONCILIATION_REQUIRED)
        self.assertEqual(self.repo.get_status(self.created.task.id), TaskStatus.RUNNING)
        self.repo.fail.assert_not_called()
        self.assertTrue((self.data / "outputs" / str(self.created.task.id) / "manifest.json").exists())

    def test_celery_task_wires_id_only_to_real_sql_and_injected_trainer(self):
        from worker.tasks import run_training
        from worker.instance_lock import release_worker_lock
        self.addCleanup(release_worker_lock)
        with patch("backend.app.core.config.get_settings", return_value=self.settings), \
             patch("backend.app.core.database.SessionLocal", self.sessions), \
             patch("trainer.train.train", self.trainer):
            result = run_training.run(str(self.created.task.id))
        self.assertEqual(result, {"task_id": str(self.created.task.id), "outcome": "completed"})
        self.assertEqual(self.repo.get_status(self.created.task.id), TaskStatus.COMPLETED)
