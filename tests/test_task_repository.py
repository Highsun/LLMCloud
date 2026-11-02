from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import threading
import unittest
from unittest.mock import patch
from uuid import uuid1, uuid4

from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError, OperationalError

from backend.app.core.task_contract import TaskStatus
from backend.app.core.task_protocols import TaskRepository, TaskStoreError
from backend.app.models.entities import Dataset, TrainingTask
from backend.app.models.task_schemas import TaskCreate, TaskListQuery
from backend.app.services.task_records import request_sha256
from backend.app.services.task_repository import IdempotencyConflict, SqlTaskRepository, TaskDatasetNotFound
from trainer.contracts import RuntimeOptions, TrainingFailure
from task_store_support import create_task, progress, setup_store, summary

TABLE = TrainingTask.__table__


class TaskRepositoryTests(unittest.TestCase):
    def setUp(self):
        setup_store(self)

    def claim(self, created=None):
        task = created or create_task(self)
        token = uuid4()
        spec = self.repo.claim(task.task.id, token, "test-worker")
        return task, token, spec

    def failure(self, task_id=None):
        return TrainingFailure(task_id=task_id, code="TRAINING_FAILED", stage="training", message="测试安全失败。")

    def test_create_snapshots_data_and_runtime_without_file_or_model_io(self):
        with patch("pathlib.Path.open", side_effect=AssertionError("Unexpected file IO")):
            created = create_task(self, runtime=RuntimeOptions(precision="fp32", max_steps=2))
        self.assertTrue(created.created)
        self.assertEqual(created.task.status, TaskStatus.PENDING)
        self.assertIsNone(created.task.progress)
        self.assertIsNone(created.task.total_steps)
        self.assertIsInstance(self.repo, TaskRepository)
        self.assertFalse((self.data / "outputs").exists())
        with self.sessions.begin() as session:
            session.execute(Dataset.__table__.update().values(sha256="b" * 64))
        _, _, spec = self.claim(created)
        self.assertNotEqual(spec.dataset_sha256, "b" * 64)
        self.assertEqual(spec.dataset_key, self.key)
        self.assertEqual((spec.runtime.precision, spec.runtime.max_steps), ("fp32", 2))

    def test_same_key_default_expansion_returns_original_without_recreation(self):
        key = uuid4()
        first = create_task(self, key=key)
        again = self.repo.create(TaskCreate(dataset_id=self.dataset_id, config=first.task.config),
            model_revision="b" * 40, runtime=RuntimeOptions(precision="fp32"), idempotency_key=key)
        self.assertFalse(again.created)
        self.assertEqual(first.task, again.task)
        self.assertEqual(first.celery_task_id, again.celery_task_id)
        self.assertEqual(self.repo.list().total, 1)
        with self.assertRaises(IdempotencyConflict):
            create_task(self, key=key, config={"lora_r": 16})
        self.assertEqual(self.repo.list().total, 1)

    def test_identical_requests_without_key_or_with_distinct_keys_are_distinct(self):
        tasks = [create_task(self), create_task(self), create_task(self, key=uuid4()), create_task(self, key=uuid4())]
        self.assertEqual(len({task.task.id for task in tasks}), 4)
        self.assertEqual(self.repo.list().total, 4)

    def test_concurrent_same_key_creates_one_record(self):
        barrier, key = threading.Barrier(2), uuid4()
        def create():
            barrier.wait(timeout=5)
            return create_task(self, key=key)
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(create) for _ in range(2)]
            results = [future.result(timeout=10) for future in futures]
        self.assertEqual(sum(item.created for item in results), 1)
        self.assertEqual(results[0].task.id, results[1].task.id)
        self.assertEqual(self.repo.list().total, 1)

    def test_missing_dataset_and_invalid_input_create_nothing(self):
        with self.assertRaises(TaskDatasetNotFound):
            self.repo.create(TaskCreate(dataset_id=uuid4()), model_revision="a" * 40, runtime=RuntimeOptions())
        for update in ({"model_revision": "main"}, {"runtime": RuntimeOptions(local_files_only=False)},
                       {"idempotency_key": uuid1()}):
            options = dict(model_revision="a" * 40, runtime=RuntimeOptions())
            options.update(update)
            with self.subTest(update=update), self.assertRaises(TaskStoreError):
                self.repo.create(TaskCreate(dataset_id=self.dataset_id), **options)
        self.assertEqual(self.repo.list().total, 0)

    def test_canonical_request_hash_fills_defaults_and_preserves_target_order(self):
        a = TaskCreate(dataset_id=self.dataset_id)
        b = TaskCreate.model_validate({"config": a.config.model_dump(), "dataset_id": self.dataset_id})
        self.assertEqual(request_sha256(a), request_sha256(b))
        b.config.target_modules.reverse()
        self.assertNotEqual(request_sha256(a), request_sha256(b))

    def test_filter_before_pagination_stable_sort_and_no_private_fields(self):
        fixed = datetime(2026, 11, 2, 1, tzinfo=timezone.utc)
        with patch("backend.app.services.task_repository.utcnow", return_value=fixed):
            tasks = [create_task(self) for _ in range(5)]
        for task in tasks[:3]:
            self.repo.mark_queued(task.task.id)
        query = TaskListQuery(status="QUEUED", page=2, page_size=2)
        page = self.repo.list(query)
        expected = sorted([task.task.id for task in tasks[:3]], reverse=True)
        self.assertEqual((page.total, page.total_pages), (3, 2))
        self.assertEqual([task.id for task in page.items], expected[2:])
        data = page.model_dump(mode="json")
        self.assertNotIn("config", data["items"][0])
        self.assertNotIn("output_path", json.dumps(data))
        self.assertEqual(self.repo.list(TaskListQuery(status="FAILED")).total_pages, 0)
        self.assertEqual(self.repo.list(TaskListQuery(page=99)).items, [])
        self.assertIsNone(self.repo.get_detail(uuid4()))
        self.assertIsNone(self.repo.get_status(uuid4()))

    def test_two_concurrent_claims_have_exactly_one_owner(self):
        created = create_task(self)
        barrier = threading.Barrier(2)
        def claim():
            barrier.wait(timeout=5)
            token = uuid4()
            return token, self.repo.claim(created.task.id, token, "test-worker")
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(claim) for _ in range(2)]
            values = [future.result(timeout=10) for future in futures]
        self.assertEqual(sum(spec is not None for _, spec in values), 1)
        winner = next(token for token, spec in values if spec is not None)
        loser = next(token for token, spec in values if spec is None)
        self.assertFalse(self.repo.record_progress(created.task.id, loser, progress()))
        self.assertTrue(self.repo.record_progress(created.task.id, winner, progress()))

    def test_pending_and_queued_claim_clear_uncertain_errors(self):
        for queued in (False, True):
            task = create_task(self)
            if queued:
                self.assertTrue(self.repo.mark_queued(task.task.id))
            self.assertTrue(self.repo.mark_dispatch_uncertain(task.task.id))
            self.claim(task)
            detail = self.repo.get_detail(task.task.id)
            self.assertEqual(detail.status, TaskStatus.RUNNING)
            self.assertIsNone(detail.error_code)
            self.assertIsNotNone(detail.started_at)
            self.assertIsNone(detail.total_steps)
            self.assertIsNone(self.repo.claim(task.task.id, uuid4(), "other"))

    def test_late_dispatch_results_cannot_overwrite_running_or_terminal(self):
        task, token, _ = self.claim()
        for operation in (self.repo.mark_queued, self.repo.mark_dispatch_failed, self.repo.mark_dispatch_uncertain):
            self.assertFalse(operation(task.task.id))
        self.repo.fail(task.task.id, token, self.failure())
        for operation in (self.repo.mark_queued, self.repo.mark_dispatch_failed, self.repo.mark_dispatch_uncertain):
            self.assertFalse(operation(task.task.id))
        self.assertEqual(self.repo.get_status(task.task.id), TaskStatus.FAILED)

    def test_dispatch_failure_before_claim_has_queryable_safe_failure(self):
        task = create_task(self)
        self.assertTrue(self.repo.mark_dispatch_failed(task.task.id))
        detail = self.repo.get_detail(task.task.id)
        self.assertEqual((detail.status, detail.error_code), (TaskStatus.FAILED, "DISPATCH_FAILED"))
        self.assertIsNone(detail.started_at)
        self.assertIsNone(self.repo.claim(task.task.id, uuid4(), "worker"))

    def test_progress_is_monotonic_eval_does_not_advance_and_total_is_fixed(self):
        task, token, _ = self.claim()
        self.assertTrue(self.repo.record_progress(task.task.id, token, progress(1, 4, "eval")))
        self.assertIsNone(self.repo.get_detail(task.task.id).total_steps)
        self.assertTrue(self.repo.record_progress(task.task.id, token, progress(2, 4)))
        self.assertTrue(self.repo.record_progress(task.task.id, token, progress(1, 4)))
        self.assertTrue(self.repo.record_progress(task.task.id, token, progress(3, 4, "eval")))
        detail = self.repo.get_detail(task.task.id)
        self.assertEqual((detail.current_step, detail.total_steps, detail.progress), (2, 4, 0.5))
        with self.assertRaises(TaskStoreError):
            self.repo.record_progress(task.task.id, token, progress(3, 5))
        self.assertEqual(self.repo.get_detail(task.task.id), detail)

    def test_runtime_limit_rejects_different_total(self):
        task, token, _ = self.claim(create_task(self, runtime=RuntimeOptions(max_steps=2)))
        with self.assertRaises(TaskStoreError):
            self.repo.record_progress(task.task.id, token, progress(1, 3))
        with self.assertRaises(TaskStoreError):
            self.repo.complete(task.task.id, token, f"outputs/{task.task.id}", "a" * 64, summary(3))
        self.assertEqual(self.repo.get_status(task.task.id), TaskStatus.RUNNING)

    def test_complete_saves_summary_and_terminal_rejects_late_updates(self):
        task, token, _ = self.claim()
        self.repo.record_progress(task.task.id, token, progress(2))
        self.assertEqual(self.repo.get_status(task.task.id), TaskStatus.RUNNING)
        self.assertTrue(self.repo.complete(task.task.id, token, f"outputs/{task.task.id}", "a" * 64, summary()))
        self.assertEqual(self.repo.get_status(task.task.id), TaskStatus.COMPLETED)
        self.assertFalse(self.repo.record_progress(task.task.id, token, progress()))
        self.assertFalse(self.repo.fail(task.task.id, token, self.failure()))
        self.assertFalse(self.repo.complete(task.task.id, token, f"outputs/{task.task.id}", "a" * 64, summary()))
        with self.sessions() as session:
            row = session.execute(select(TABLE)).mappings().one()
            self.assertEqual(row["training_summary"], summary().model_dump(mode="json"))
            self.assertEqual(row["manifest_sha256"], "a" * 64)

    def test_fail_preserves_progress_and_rejects_wrong_owner_or_task(self):
        task, token, _ = self.claim()
        self.repo.record_progress(task.task.id, token, progress())
        self.assertFalse(self.repo.fail(task.task.id, uuid4(), self.failure()))
        self.assertFalse(self.repo.complete(task.task.id, uuid4(), f"outputs/{task.task.id}", "a" * 64, summary()))
        with self.assertRaises(TaskStoreError):
            self.repo.fail(task.task.id, token, self.failure(uuid4()))
        self.assertTrue(self.repo.fail(task.task.id, token, self.failure(task.task.id)))
        detail = self.repo.get_detail(task.task.id)
        self.assertEqual((detail.current_step, detail.total_steps, detail.progress), (1, 2, 0.5))

    def test_invalid_ids_owner_output_and_hash_are_safe_errors(self):
        task, token, _ = self.claim()
        for worker in ("", " " * 3, "bad\nworker", "x" * 256):
            with self.subTest(worker=worker), self.assertRaises(TaskStoreError):
                self.repo.claim(task.task.id, uuid4(), worker)
        with self.assertRaises(TaskStoreError):
            self.repo.get_status("not-a-uuid")
        for key, digest in (("../outside", "a" * 64), (f"outputs/{task.task.id}", "bad")):
            with self.subTest(key=key), self.assertRaises(TaskStoreError):
                self.repo.complete(task.task.id, token, key, digest, summary())

    def test_database_constraints_reject_half_claim_half_key_and_duplicate_key(self):
        first, second = create_task(self, key=uuid4()), create_task(self)
        for update in ({"claim_token": str(uuid4())}, {"worker_id": "orphan"},
                       {"idempotency_key": str(uuid4())}, {"request_sha256": "a" * 64},
                       {"dataset_size_bytes": 0}, {"dataset_key": "../outside"},
                       {"status": "FAILED"}):
            with self.subTest(update=update), self.assertRaises(IntegrityError):
                with self.sessions.begin() as session:
                    session.execute(TABLE.update().where(TABLE.c.id == str(second.task.id)).values(**update))
        with self.sessions() as session:
            original = session.execute(select(TABLE).where(TABLE.c.id == str(first.task.id))).mappings().one()
        with self.assertRaises(IntegrityError):
            with self.sessions.begin() as session:
                session.execute(TABLE.insert().values(**{**original, "id": str(uuid4())}))

    def test_corrupt_record_is_not_silently_skipped(self):
        task = create_task(self)
        with self.sessions.begin() as session:
            session.execute(TABLE.update().values(training_config={"lora_r": 0}))
        for operation in (lambda: self.repo.get_status(task.task.id), lambda: self.repo.claim(task.task.id, uuid4(), "worker")):
            with self.assertRaises(TaskStoreError):
                operation()

    def test_storage_errors_do_not_leak_driver_text(self):
        def unavailable():
            raise OperationalError("SQL password=private path=/secret", {}, Exception("private"))
        with self.assertRaises(TaskStoreError) as context:
            SqlTaskRepository(unavailable).get_status(uuid4())
        self.assertEqual(str(context.exception), "任务存储暂时不可用。")

    def test_completion_commit_ack_loss_is_readable_without_overwriting_success(self):
        task, token, _ = self.claim()
        injected = [True]
        def lost_ack(session):
            if injected[0]:
                injected[0] = False
                raise OperationalError("commit acknowledgement lost", {}, Exception())
        event.listen(self.sessions.class_, "after_commit", lost_ack)
        try:
            with self.assertRaises(TaskStoreError):
                self.repo.complete(task.task.id, token, f"outputs/{task.task.id}", "a" * 64, summary())
            self.assertEqual(self.repo.get_status(task.task.id), TaskStatus.COMPLETED)
            self.assertFalse(self.repo.fail(task.task.id, token, self.failure()))
        finally:
            event.remove(self.sessions.class_, "after_commit", lost_ack)

    def test_completion_commit_failure_rolls_back_and_keeps_running(self):
        task, token, _ = self.claim()
        def fail_commit(session):
            raise OperationalError("injected commit failure", {}, Exception())
        event.listen(self.sessions.class_, "before_commit", fail_commit)
        try:
            with self.assertRaises(TaskStoreError):
                self.repo.complete(task.task.id, token, f"outputs/{task.task.id}", "a" * 64, summary())
        finally:
            event.remove(self.sessions.class_, "before_commit", fail_commit)
        self.assertEqual(self.repo.get_status(task.task.id), TaskStatus.RUNNING)


if __name__ == "__main__":
    unittest.main()
