from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid1, uuid4

from backend.app.core.task_contract import ExecutionOutcome as Outcome, TaskStatus
from backend.app.core.task_protocols import TaskRepository, TaskStoreError
from trainer.artifacts import sha256
from trainer.contracts import TrainResult, TrainingError, TrainingFailure, TrainingProgress
from worker.execution import execute_training
from worker_support import MemoryRepository, make_spec, synthetic_train


class WorkerExecutionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.settings = SimpleNamespace(data_dir=self.root / "data", log_dir=self.root / "logs",
                                        default_model_revision="c" * 40)
        self.spec = make_spec(self.settings.data_dir)
        self.repo = MemoryRepository(self.spec)
        self.trainer = Mock(side_effect=synthetic_train)
        self.paths = patch("worker.execution.resolve_model_paths",
            return_value=SimpleNamespace(cache_dir=self.root / "cache"))
        self.paths.start(); self.addCleanup(self.paths.stop)
        self.cache = patch("worker.execution.verify_model_cache")
        self.cache_check = self.cache.start(); self.addCleanup(self.cache.stop)

    def run_task(self):
        return execute_training(self.spec.task_id, self.repo, self.settings, self.trainer)

    def failure(self, code, stage="training"):
        return TrainingError(TrainingFailure(code=code, stage=stage, message="安全的测试错误。"))

    def test_success_audits_real_cpu_bundle_and_preserves_snapshot(self):
        self.assertIsInstance(self.repo, TaskRepository)
        self.assertEqual(self.run_task(), Outcome.COMPLETED)
        request = self.trainer.call_args.args[0]
        self.assertEqual(request.model_revision, self.spec.model_revision)
        self.assertEqual(request.runtime, self.spec.runtime)
        self.assertIsNot(request.config, self.spec.config)
        self.assertEqual(request.dataset_path, self.settings.data_dir / self.spec.dataset_key)
        self.assertEqual(request.cache_dir, self.root / "cache")
        self.cache_check.assert_called_once_with(request.cache_dir, self.spec.model_revision)
        self.assertEqual([event.step for event in self.repo.events], [1, 2])
        key, digest, summary = self.repo.completions[0]
        self.assertEqual(key, f"outputs/{self.spec.task_id}")
        self.assertEqual(digest, sha256(request.output_dir / "manifest.json"))
        self.assertEqual(summary.completed_steps, 2)
        self.assertEqual(len(request.output_dir.joinpath("metrics.jsonl").read_text().splitlines()), 2)
        self.assertEqual(self.repo.failures, [])

    def test_duplicate_and_terminal_messages_skip_all_files_and_gpu(self):
        for status in [TaskStatus.RUNNING, TaskStatus.COMPLETED, TaskStatus.FAILED]:
            self.repo.state = status
            self.assertEqual(self.run_task(), Outcome.SKIPPED)
        self.trainer.assert_not_called(); self.cache_check.assert_not_called()
        self.assertFalse((self.settings.data_dir / "outputs").exists())
        self.assertEqual(self.repo.failures, [])

    def test_pending_can_be_claimed_directly_and_duplicate_run_skips(self):
        self.repo.state = TaskStatus.PENDING
        self.assertEqual(self.run_task(), Outcome.COMPLETED)
        self.assertEqual(self.run_task(), Outcome.SKIPPED)
        self.assertEqual(self.trainer.call_count, 1)
        self.assertNotEqual(self.repo.claims[0][1], self.repo.claims[1][1])

    def test_claim_storage_failure_is_not_a_duplicate_or_training_failure(self):
        self.repo.claim = Mock(side_effect=TaskStoreError())
        self.assertEqual(self.run_task(), Outcome.RECONCILIATION_REQUIRED)
        self.assertEqual(self.repo.failures, []); self.trainer.assert_not_called()

    def test_invalid_message_id_is_rejected_before_repository(self):
        for invalid in ["not-uuid", uuid1(), str(uuid4()).upper()]:
            with self.assertRaises(ValueError):
                execute_training(invalid, self.repo, self.settings, self.trainer)
        self.assertEqual(self.repo.claims, [])

    def test_mismatched_claimed_id_fails_before_io(self):
        self.repo.spec = self.spec.model_copy(update={"task_id": uuid4()})
        self.assertEqual(self.run_task(), Outcome.FAILED)
        self.assertEqual(self.repo.failures[0].code, "INVALID_REQUEST")
        self.trainer.assert_not_called(); self.cache_check.assert_not_called()

    def test_mutated_snapshot_or_traversal_rejected_before_io(self):
        self.repo.spec = self.spec.model_copy(update={"dataset_key": "../outside.jsonl"})
        self.assertEqual(self.run_task(), Outcome.FAILED)
        self.assertEqual(self.repo.failures[0].code, "INVALID_REQUEST")
        self.cache_check.assert_not_called()

    def test_missing_modified_or_invalid_dataset_fails_before_train(self):
        path = self.settings.data_dir / self.spec.dataset_key
        for raw in [b'{"instruction":"changed","output":"y"}\n', b'invalid json\n', None]:
            self.repo = MemoryRepository(self.spec)
            if raw is None: path.unlink()
            else: path.write_bytes(raw)
            self.assertEqual(self.run_task(), Outcome.FAILED)
            self.assertEqual(self.repo.failures[0].code, "INVALID_DATASET")
        self.trainer.assert_not_called(); self.cache_check.assert_not_called()

    def test_symlink_input_does_not_escape_dataset_root(self):
        path = self.settings.data_dir / self.spec.dataset_key
        outside = self.root / "outside.jsonl"
        outside.write_bytes(path.read_bytes()); path.unlink()
        try: path.symlink_to(outside)
        except OSError: self.skipTest("Host does not allow creating symlinks")
        self.assertEqual(self.run_task(), Outcome.FAILED)
        self.assertEqual(self.repo.failures[0].code, "INVALID_DATASET")
        self.trainer.assert_not_called()

    def test_existing_output_or_log_is_preserved_and_rejected(self):
        output = self.settings.data_dir / "outputs" / str(self.spec.task_id)
        output.mkdir(parents=True); marker = output / "keep.txt"; marker.write_text("keep")
        self.assertEqual(self.run_task(), Outcome.FAILED)
        self.assertEqual(marker.read_text(), "keep")
        self.assertEqual(self.repo.failures[0].code, "INVALID_REQUEST")
        marker.unlink(); output.rmdir()
        self.repo = MemoryRepository(self.spec)
        log = self.settings.log_dir / "tasks" / f"{self.spec.task_id}.log"
        log.parent.mkdir(parents=True); log.write_text("keep log")
        self.assertEqual(self.run_task(), Outcome.FAILED)
        self.assertEqual(log.read_text(), "keep log"); self.trainer.assert_not_called()

    def test_missing_model_cache_fails_without_downloading(self):
        self.cache.stop()
        self.assertEqual(self.run_task(), Outcome.FAILED)
        self.assertEqual(self.repo.failures[0].code, "MODEL_NOT_CACHED")
        self.trainer.assert_not_called()
        self.assertFalse((self.root / "cache").exists())

    def test_trainer_failures_preserve_their_safe_code(self):
        for code in ["CUDA_OUT_OF_MEMORY", "ARTIFACT_WRITE_FAILED", "MODEL_LOAD_FAILED"]:
            self.repo = MemoryRepository(self.spec)
            self.trainer.side_effect = self.failure(code)
            self.assertEqual(self.run_task(), Outcome.FAILED)
            self.assertEqual(self.repo.failures[0].code, code)

    def test_unknown_exception_text_is_not_leaked(self):
        self.trainer.side_effect = RuntimeError("SECRET credential and /private/training/text")
        with self.assertLogs("worker.execution", level="WARNING") as messages:
            self.assertEqual(self.run_task(), Outcome.FAILED)
        self.assertNotIn("SECRET", " ".join(messages.output))
        self.assertNotIn("SECRET", self.repo.failures[0].message)

    def test_eval_events_are_forwarded_without_rewriting_metrics(self):
        def train(request, on_progress):
            result = synthetic_train(request)
            before = result.metrics_path.read_bytes()
            on_progress(TrainingProgress(step=1, total_steps=2, kind="eval", loss=1.0,
                learning_rate=0.0002, epoch=0.5, recorded_at=datetime.now(timezone.utc)))
            self.assertEqual(before, result.metrics_path.read_bytes())
            return result
        self.trainer.side_effect = train
        self.assertEqual(self.run_task(), Outcome.COMPLETED)
        self.assertEqual(self.repo.events[0].kind, "eval")

    def test_lost_ownership_is_not_recorded_as_failed_even_if_trainer_wraps_callback(self):
        self.repo.record_progress = Mock(return_value=False)
        def train(request, on_progress):
            try: synthetic_train(request, on_progress)
            except Exception: raise self.failure("PROGRESS_CALLBACK_FAILED", "callback")
        self.trainer.side_effect = train
        self.assertEqual(self.run_task(), Outcome.OWNERSHIP_LOST)
        self.assertEqual(self.repo.failures, []); self.assertEqual(self.repo.completions, [])

    def test_progress_store_exception_stops_training_and_records_callback_failure(self):
        self.repo.record_progress = Mock(side_effect=TaskStoreError())
        self.assertEqual(self.run_task(), Outcome.FAILED)
        self.assertEqual(self.repo.failures[0].code, "PROGRESS_CALLBACK_FAILED")

    def test_corrupt_or_mismatched_artifacts_cannot_complete(self):
        def train(request, on_progress):
            result = synthetic_train(request, on_progress)
            (result.adapter_dir / "adapter_model.safetensors").write_bytes(b"corrupt")
            return result
        self.trainer.side_effect = train
        self.assertEqual(self.run_task(), Outcome.FAILED)
        self.assertEqual(self.repo.failures[0].code, "INVALID_ARTIFACT")
        self.assertEqual(self.repo.completions, [])

    def test_valid_artifacts_from_a_different_data_snapshot_are_rejected(self):
        def train(request, on_progress):
            result = synthetic_train(request, on_progress)
            manifest = json.loads(result.manifest_path.read_text())
            manifest["train_dataset"]["sha256"] = "f" * 64
            result.manifest_path.write_text(json.dumps(manifest))
            return result
        self.trainer.side_effect = train
        self.assertEqual(self.run_task(), Outcome.FAILED)
        self.assertEqual(self.repo.failures[0].code, "INVALID_ARTIFACT")

    def test_malformed_result_cannot_complete(self):
        self.trainer.side_effect = None; self.trainer.return_value = {"success": True}
        self.assertEqual(self.run_task(), Outcome.FAILED)
        self.assertEqual(self.repo.failures[0].code, "INVALID_ARTIFACT")

    def test_complete_reply_lost_reads_actual_completed_state_and_keeps_artifacts(self):
        def complete(*args):
            self.repo.state = TaskStatus.COMPLETED
            raise TaskStoreError()
        self.repo.complete = Mock(side_effect=complete)
        self.assertEqual(self.run_task(), Outcome.COMPLETED)
        self.assertEqual(self.repo.reads, 1); self.assertEqual(self.repo.failures, [])
        self.assertTrue((self.settings.data_dir / "outputs" / str(self.spec.task_id) / "manifest.json").exists())

    def test_complete_before_commit_failure_preserves_running_state_for_reconciliation(self):
        self.repo.complete = Mock(side_effect=TaskStoreError())
        self.assertEqual(self.run_task(), Outcome.RECONCILIATION_REQUIRED)
        self.assertEqual(self.repo.state, TaskStatus.RUNNING); self.assertEqual(self.repo.failures, [])

    def test_completion_read_failure_does_not_overwrite_or_delete_success(self):
        self.repo.complete = Mock(side_effect=TaskStoreError())
        self.repo.get_status = Mock(side_effect=TaskStoreError())
        self.assertEqual(self.run_task(), Outcome.RECONCILIATION_REQUIRED)
        self.assertEqual(self.repo.failures, [])
        self.assertTrue((self.settings.data_dir / "outputs" / str(self.spec.task_id) / "manifest.json").exists())

    def test_false_complete_and_fail_mean_ownership_lost(self):
        self.repo.complete = Mock(return_value=False)
        self.assertEqual(self.run_task(), Outcome.OWNERSHIP_LOST)
        self.assertEqual(self.repo.failures, [])
        self.repo = MemoryRepository(self.spec)
        self.repo.fail = Mock(return_value=False)
        self.assertEqual(self.run_task(), Outcome.OWNERSHIP_LOST)  # Existing output preflight fails; no overwrite.

    def test_failure_write_exception_requires_reconciliation(self):
        self.trainer.side_effect = self.failure("TRAINING_FAILED")
        self.repo.fail = Mock(side_effect=TaskStoreError())
        self.assertEqual(self.run_task(), Outcome.RECONCILIATION_REQUIRED)

    def test_process_interrupt_is_not_misreported_as_training_failure(self):
        self.trainer.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt): self.run_task()
        self.assertEqual(self.repo.state, TaskStatus.RUNNING); self.assertEqual(self.repo.failures, [])

    def test_worker_and_celery_import_without_gpu_dependencies(self):
        code = '''
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'torch','numpy','transformers','datasets','peft','trl','accelerate','huggingface_hub'}:
        raise AssertionError('GPU dependency imported: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
import worker.execution, worker.tasks, worker.celery_app
'''
        result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
