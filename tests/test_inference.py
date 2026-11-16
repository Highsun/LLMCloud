"""M5 fault regression: real SQLite/ASGI, explicitly substituted publisher/GPU.

Real GPU/90-second acceptance is a separate opt-in command. No model downloads.
"""
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from starlette.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.core.task_contract import PublishOutcome
from backend.app.main import create_app
from backend.app.models.entities import InferenceJob
from backend.app.models.inference_schemas import InferenceRequest
from backend.app.services.inference_repository import InferenceRepository, WAITING, RUNNING, FINISHED
from task_store_support import setup_store, create_task, summary
from trainer.contracts import TrainingError
from worker.inference import execute_inference


def completed(test):
    task = create_task(test)
    token = uuid4()
    test.repo.claim(task.task.id, token, "cpu-fixture")
    test.repo.complete(task.task.id, token, f"outputs/{task.task.id}", "a" * 64, summary())
    return task.task.id


class InferenceStoreTests(unittest.TestCase):
    def setUp(self):
        setup_store(self)
        self.task_id = completed(self)
        self.infer = InferenceRepository(self.sessions)
        self.body = InferenceRequest(task_id=self.task_id, prompt="CPU fixture", max_new_tokens=4)

    def reserve(self, job_id=None, **kwargs):
        job_id = job_id or str(uuid4())
        result = self.infer.reserve(job_id, self.body, kwargs.get("claim_by", time.time() + 10),
                                    kwargs.get("finish_by", time.time() + 90))
        return job_id, result

    def test_two_simultaneous_reservations_have_one_winner(self):
        gate = threading.Barrier(2)
        def reserve():
            gate.wait(timeout=5)
            return self.reserve()
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: reserve(), range(2)))
        self.assertEqual(sum(code is None for _, code in results), 1)
        self.assertEqual(sum(code == "GPU_BUSY" for _, code in results), 1)

    def test_duplicate_claim_has_one_owner_and_erases_prompt(self):
        job, _ = self.reserve()
        gate = threading.Barrier(2)
        def claim():
            gate.wait(timeout=5)
            return self.infer.claim_inference(job)
        with ThreadPoolExecutor(2) as pool:
            values = list(pool.map(lambda _: claim(), range(2)))
        self.assertEqual(sum(item is not None for item in values), 1)
        with self.sessions() as session:
            self.assertIsNone(session.get(InferenceJob, job).request)

    def test_expired_or_cancelled_waiting_message_cannot_start(self):
        for operation in ("expire", "cancel", "stop"):
            with self.subTest(operation=operation):
                job, _ = self.reserve()
                if operation == "expire":
                    with patch("backend.app.services.inference_repository.time", return_value=time.time() + 11):
                        self.assertIsNone(self.infer.claim_inference(job))
                elif operation == "cancel":
                    self.infer.cancel_inference(job)
                else:
                    self.assertTrue(self.infer.stop_waiting(job))
                self.assertIsNone(self.infer.claim_inference(job))
                self.assertEqual(self.infer.get_inference(job)[0], FINISHED)

    def test_training_claim_releases_waiting_inference_in_same_transaction(self):
        job, _ = self.reserve()
        training = create_task(self)
        self.assertIsNotNone(self.repo.claim(training.task.id, uuid4(), "cpu-worker"))
        self.assertEqual(self.infer.get_inference(job)[:2], (FINISHED, "GPU_BUSY"))
        self.assertIsNone(self.infer.claim_inference(job))

    def test_training_submission_and_inference_claim_race_is_serializable(self):
        job, _ = self.reserve()
        gate = threading.Barrier(2)
        def submit():
            gate.wait(timeout=5)
            return create_task(self)
        def claim():
            gate.wait(timeout=5)
            return self.infer.claim_inference(job)
        with ThreadPoolExecutor(2) as pool:
            submit_result, claim_result = pool.submit(submit), pool.submit(claim)
            submit_result.result(timeout=10)
            claimed = claim_result.result(timeout=10)
        state, error, _ = self.infer.get_inference(job)
        # Claim before submission is allowed: the sole worker will run training later.
        self.assertEqual((state, error), (RUNNING, None) if claimed else (FINISHED, "GPU_BUSY"))

    def test_cancelled_running_job_keeps_gpu_reserved_until_actual_cleanup(self):
        job, _ = self.reserve()
        self.infer.claim_inference(job)
        self.infer.cancel_inference(job)
        self.assertTrue(self.infer.inference_cancelled(job))
        self.assertEqual(self.reserve()[1], "GPU_BUSY")
        self.infer.complete_inference(job, error="INFERENCE_TIMEOUT")
        self.assertIsNone(self.infer.get_inference(job))
        self.assertIsNone(self.reserve()[1])

    def test_elapsed_running_deadline_does_not_free_gpu(self):
        job, _ = self.reserve(finish_by=time.time() - 1)
        self.infer.claim_inference(job)
        self.infer.prune_inference()
        self.assertEqual(self.reserve()[1], "GPU_BUSY")
        self.infer.complete_inference(job, result={"not": "a valid response"})
        self.assertEqual(self.infer.get_inference(job), (FINISHED, "INFERENCE_TIMEOUT", None))

    def test_worker_restart_marks_orphan_failed_and_next_request_can_reserve(self):
        job, _ = self.reserve()
        self.infer.claim_inference(job)
        self.infer.recover_inference()  # Production caller must hold worker.lock.
        self.assertEqual(self.infer.get_inference(job), (FINISHED, "INFERENCE_FAILED", None))
        self.assertIsNone(self.reserve()[1])

    def test_terminal_retention_prunes_answers_without_touching_active_job(self):
        job, _ = self.reserve()
        self.infer.claim_inference(job)
        self.infer.complete_inference(job, result={"answer": "private"})
        active, _ = self.reserve()
        with patch("backend.app.services.inference_repository.time", return_value=time.time() + 601):
            self.infer.prune_inference()
        self.assertIsNone(self.infer.get_inference(job))
        self.assertEqual(self.infer.get_inference(active)[0], FINISHED)  # expired waiting

    def test_corrupted_request_is_failed_without_model_execution(self):
        job, _ = self.reserve()
        with self.sessions.begin() as session:
            session.get(InferenceJob, job).request = {"task_id": str(uuid4())}
        self.assertIsNone(self.infer.claim_inference(job))
        self.assertEqual(self.infer.get_inference(job)[:2], (FINISHED, "INFERENCE_FAILED"))


class Publisher:
    outcome = PublishOutcome.ACCEPTED
    action = None
    def publish_inference(self, job):
        if self.action:
            self.action(job)
        return self.outcome


class InferenceHTTPTests(unittest.TestCase):
    def setUp(self):
        setup_store(self)
        self.task_id = completed(self)
        self.publisher = Publisher()
        self.app = create_app(Settings(_env_file=None, data_dir=self.data, log_dir=self.root / "logs",
            database_url=f"sqlite:///{self.database}"), inference_publisher=self.publisher)
        self.client = self.enterContext(TestClient(self.app))
        self.infer = self.app.state.inference_repository
        self.body = {"task_id": str(self.task_id), "prompt": "fixture", "max_new_tokens": 4, "mode": "adapter"}

    def result(self):
        return {**self.body, "base_model": "Qwen/Qwen2.5-0.5B-Instruct", "model_revision": "a" * 40,
            "input_tokens": 3, "base": None, "adapter": {"generated_text": "test", "generated_tokens": 1}}

    def post(self):
        return self.client.post("/api/v1/inference", json=self.body)

    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(response.json()["error"]["code"], code)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-request-id"], response.json()["error"]["request_id"])
        self.assertNotIn(str(self.root), response.text)

    def test_unknown_publish_before_claim_stops_and_late_message_is_ignored(self):
        self.publisher.outcome = PublishOutcome.UNKNOWN
        jobs = []
        self.publisher.action = jobs.append
        self.assert_error(self.post(), 503, "INFERENCE_UNAVAILABLE")
        self.assertIsNone(self.infer.claim_inference(jobs[0]))

    def test_unknown_publish_after_claim_returns_original_result_without_retry(self):
        self.publisher.outcome = PublishOutcome.UNKNOWN
        jobs = []
        def claim(job):
            jobs.append(job)
            self.infer.claim_inference(job)
            self.infer.complete_inference(job, result=self.result())
        self.publisher.action = claim
        response = self.post()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(jobs), 1)
        self.assertIsNone(self.infer.get_inference(jobs[0]))

    def test_not_sent_and_publish_exception_are_safe_503_without_republish(self):
        for exception in (False, True):
            calls = []
            def publish(job):
                calls.append(job)
                if exception:
                    raise OSError("private broker URL")
            self.publisher.action = publish
            self.publisher.outcome = PublishOutcome.NOT_SENT
            self.assert_error(self.post(), 503, "INFERENCE_UNAVAILABLE")
            self.assertEqual(len(calls), 1)

    def test_claim_deadline_late_duplicate_messages_do_not_start(self):
        self.publisher.action = None
        with patch("backend.app.api.inference.INFERENCE_CLAIM_SECONDS", 0.02):
            self.assert_error(self.post(), 503, "INFERENCE_UNAVAILABLE")

    def test_claimed_http_deadline_returns_504_cancels_and_waits_for_gpu_cleanup(self):
        jobs = []
        def claim(job):
            jobs.append(job)
            self.infer.claim_inference(job)
        self.publisher.action = claim
        with patch("backend.app.api.inference.INFERENCE_WAIT_SECONDS", 0.05):
            self.assert_error(self.post(), 504, "INFERENCE_TIMEOUT")
        self.assertTrue(self.infer.inference_cancelled(jobs[0]))
        self.assert_error(self.post(), 409, "GPU_BUSY")
        self.infer.complete_inference(jobs[0], error="INFERENCE_TIMEOUT")
        def success(job):
            self.infer.claim_inference(job)
            self.infer.complete_inference(job, result=self.result())
        self.publisher.action = success
        self.assertEqual(self.post().status_code, 200)

    def test_worker_failure_codes_preserve_status_and_request_id(self):
        for code, status in (("MODEL_NOT_CACHED", 503), ("INFERENCE_FAILED", 500),
                             ("INVALID_ARTIFACT", 500), ("INFERENCE_TIMEOUT", 504)):
            def fail(job):
                self.infer.claim_inference(job)
                self.infer.complete_inference(job, error=code)
            self.publisher.action = fail
            self.assert_error(self.post(), status, code)

    def test_input_boundaries_do_not_publish(self):
        calls = []
        self.publisher.action = calls.append
        for patch_body in ({"prompt": " "}, {"mode": "base"}, {"max_new_tokens": 257},
                           {"max_new_tokens": True}, {"prompt": "x" * 8193}, {"extra": 1}):
            response = self.client.post("/api/v1/inference", json={**self.body, **patch_body})
            self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(calls, [])


class InferenceExecutionTests(unittest.TestCase):
    """Exercise the production worker with explicit CPU artifact/model substitutes."""
    setUp = InferenceStoreTests.setUp
    reserve = InferenceStoreTests.reserve

    def test_missing_cache_finishes_then_next_request_can_reserve(self):
        from types import SimpleNamespace
        from trainer.contracts import TrainingFailure
        job, _ = self.reserve()
        settings = Settings(_env_file=None, data_dir=self.data, log_dir=self.root / "logs")
        completed_artifact = SimpleNamespace(spec=SimpleNamespace(model_revision="a" * 40))
        missing = TrainingError(TrainingFailure(code="MODEL_NOT_CACHED", stage="model_loading", message="test"))
        with patch.object(self.infer, "get_completed_artifact", return_value=completed_artifact), \
             patch("worker.inference.snapshot_completed_artifact", return_value=(None, object(), None, None)), \
             patch("worker.inference.verify_model_cache", side_effect=missing), \
             patch("worker.inference.generate_verified_adapter") as generate:
            execute_inference(job, self.infer, settings)
        generate.assert_not_called()
        self.assertEqual(self.infer.get_inference(job)[:2], (FINISHED, "MODEL_NOT_CACHED"))
        self.assertIsNone(self.reserve()[1])

    def test_duplicate_worker_delivery_never_reenters_model(self):
        job, _ = self.reserve()
        self.infer.stop_waiting(job)
        with patch("worker.inference.generate_verified_adapter") as generate:
            execute_inference(job, self.infer, None)
            execute_inference(job, self.infer, None)
        generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
