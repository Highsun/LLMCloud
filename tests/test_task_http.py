"""Real HTTP/ASGI + SQLite; Publisher substitutes are explicitly test-only."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID, uuid1, uuid4

from starlette.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.core.task_contract import MAX_TASK_BODY_BYTES, PublishOutcome, TaskStatus
from backend.app.core.task_protocols import TaskStoreError
from backend.app.main import create_app
from backend.app.models.error_schemas import ErrorResponse
from backend.app.models.task_schemas import TaskDetail, TaskPage, TaskSubmissionErrorResponse
from scripts.export_task_openapi import build_contract, generate_outputs
from task_store_support import progress, summary

BASE = "/api/v1/tasks"
ORIGIN = "http://localhost:5173"
RAW = b'{"instruction":"x","output":"y"}\n'


class PublisherDouble:
    def __init__(self):
        self.calls, self.outcome, self.action = [], PublishOutcome.ACCEPTED, None

    def publish(self, task_id, celery_task_id):
        self.calls.append((task_id, celery_task_id))
        if self.action:
            self.action(task_id, celery_task_id)
        return self.outcome


class TaskHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.settings = Settings(_env_file=None, data_dir=root / "data", log_dir=root / "logs", database_url="")
        self.publisher = PublisherDouble()
        self.app = create_app(self.settings, task_publisher=self.publisher)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.repo = self.app.state.task_repository
        self.dataset = self.client.post("/api/v1/datasets", files={"file": ("test.jsonl", RAW)}).json()
        self.body = {"dataset_id": self.dataset["id"]}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def post(self, **options):
        return self.client.post(BASE, json=options.pop("body", self.body), **options)

    def assert_error(self, response, status, code, *, persisted=False):
        self.assertEqual(response.status_code, status, response.text)
        payload = (TaskSubmissionErrorResponse if persisted else ErrorResponse).model_validate(response.json())
        self.assertEqual(payload.error.code, code)
        self.assertEqual(str(payload.error.request_id), response.headers["x-request-id"])
        self.assertEqual(UUID(response.headers["x-request-id"]).version, 4)
        self.assertNotIn(str(self.settings.data_dir), response.text)
        if persisted:
            self.assertEqual(response.headers["location"], f"{BASE}/{payload.error.task_id}")
        else:
            self.assertNotIn("task_id", response.json()["error"])
        return response.json()["error"]

    def test_create_202_commits_before_publish_and_returns_real_resource_location(self):
        def check_committed(task_id, _message_id):
            self.assertEqual(self.repo.get_status(task_id), TaskStatus.PENDING)
        self.publisher.action = check_committed
        response = self.post(headers={"Origin": ORIGIN})
        self.assertEqual(response.status_code, 202, response.text)
        detail = TaskDetail.model_validate(response.json())
        self.assertEqual(detail.status, TaskStatus.QUEUED)
        self.assertIsNone(detail.total_steps)
        self.assertIsNone(detail.progress)
        self.assertEqual(response.headers["location"], f"{BASE}/{detail.id}")
        self.assertEqual(self.client.get(response.headers["location"]).json(), response.json())
        self.assertEqual(response.headers["access-control-allow-origin"], ORIGIN)
        self.assertEqual(len(self.publisher.calls), 1)
        self.assertNotEqual(self.publisher.calls[0][0], self.publisher.calls[0][1])
        self.assertEqual(list((self.settings.data_dir / "outputs").iterdir()), [])
        self.assertEqual(list(self.settings.log_dir.iterdir()), [])

    def test_idempotent_replay_200_does_not_publish_again_and_conflict_409(self):
        headers = {"Idempotency-Key": str(uuid4())}
        first = self.post(headers=headers)
        replay = self.post(headers=headers, body={**self.body, "config": first.json()["config"]})
        self.assertEqual((first.status_code, replay.status_code), (202, 200))
        self.assertEqual(first.json(), replay.json())
        self.assert_error(self.post(headers=headers, body={**self.body, "config": {"lora_r": 16}}), 409, "IDEMPOTENCY_CONFLICT")
        self.assertEqual(len(self.publisher.calls), 1)
        self.assertEqual(self.repo.list().total, 1)

    def test_concurrent_same_key_posts_create_and_publish_once(self):
        headers = {"Idempotency-Key": str(uuid4())}
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(self.post, headers=headers) for _ in range(2)]
            responses = [future.result(timeout=10) for future in futures]
        self.assertEqual(sorted(response.status_code for response in responses), [200, 202])
        self.assertEqual(responses[0].json()["id"], responses[1].json()["id"])
        self.assertEqual(len(self.publisher.calls), 1)

    def test_no_key_allows_intentional_distinct_tasks(self):
        first, second = self.post(), self.post()
        self.assertNotEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(len(self.publisher.calls), 2)

    def test_queries_filter_before_page_and_hide_private_fields(self):
        created = [self.post().json() for _ in range(3)]
        self.repo.claim(created[0]["id"], uuid4(), "test-worker")
        response = self.client.get(BASE + "?status=QUEUED&page=2&page_size=1")
        page = TaskPage.model_validate(response.json())
        self.assertEqual((page.total, page.total_pages, len(page.items)), (2, 2, 1))
        self.assertEqual(page.items[0].status, TaskStatus.QUEUED)
        self.assertNotIn("config", response.json()["items"][0])
        for name in ("claim_token", "celery_task_id", "output_path", "dataset_key", "runtime_options"):
            self.assertNotIn(name, self.client.get(f"{BASE}/{created[0]['id']}").text)
        self.assertEqual(self.client.get(BASE + "?page=99").json()["items"], [])
        huge = self.client.get(BASE + "?page=" + "9" * 100)
        self.assertEqual(huge.status_code, 200, huge.text)
        self.assertEqual(huge.json()["items"], [])
        self.assertEqual(self.client.get(BASE + "?status=FAILED").json()["total_pages"], 0)

    def test_uuid_missing_dataset_missing_task_and_unknown_payload_fields(self):
        self.assert_error(self.post(body={"dataset_id": str(uuid4())}), 404, "DATASET_NOT_FOUND")
        for task_id in ("bad", str(uuid1())):
            self.assert_error(self.client.get(BASE + "/" + task_id), 422, "VALIDATION_ERROR")
        self.assert_error(self.client.get(BASE + "/" + str(uuid4())), 404, "TASK_NOT_FOUND")
        for body in ({}, {"dataset_id": str(uuid1())}, {**self.body, "status": "COMPLETED"},
                     {**self.body, "revision": "main"}, {**self.body, "config": {"max_steps": 2}},
                     {**self.body, "config": {"lora_r": 0}}):
            with self.subTest(body=body):
                self.assert_error(self.post(body=body), 422, "VALIDATION_ERROR")
        self.assertEqual(self.publisher.calls, [])
        self.assertEqual(self.repo.list().total, 0)

    def test_unknown_duplicate_float_and_bad_status_queries_are_rejected(self):
        for query in ("page=1&page=2", "status=RUNNING&status=FAILED", "extra=secret", "status=ALL",
                      "status=running", "page=1.0", "page=1.5", "page=", "page=0", "page_size=101"):
            with self.subTest(query=query):
                self.assert_error(self.client.get(BASE + "?" + query), 422, "VALIDATION_ERROR")
        self.assert_error(self.client.post(BASE + "?extra=secret", json=self.body), 422, "VALIDATION_ERROR")

    def test_duplicate_and_invalid_idempotency_headers_do_not_persist_or_send(self):
        self.assert_error(self.post(headers=[("Idempotency-Key", str(uuid4())), ("idempotency-key", str(uuid4()))]),
                          422, "VALIDATION_ERROR")
        for value in ("", "invalid", str(uuid1())):
            self.assert_error(self.post(headers={"Idempotency-Key": value}), 422, "VALIDATION_ERROR")
        self.assertEqual(self.repo.list().total, 0)
        self.assertEqual(self.publisher.calls, [])

    def test_invalid_json_duplicate_nested_fields_nonfinite_and_wrong_top_level(self):
        for raw in (b"", b"{bad}", b"\xff", b"[]", b"null", b'{"dataset_id":NaN}',
                    b'{"config":{"lora_r":8,"lora_r":16}}', b'{"dataset_id":"private","dataset_id":"secret"}'):
            with self.subTest(raw=raw):
                response = self.client.post(BASE, content=raw, headers={"Content-Type": "application/json"})
                self.assert_error(response, 422, "VALIDATION_ERROR")
                self.assertNotIn("secret", response.text)
        self.assertEqual(self.repo.list().total, 0)

    def test_json_media_and_encoding_are_explicit(self):
        for headers in ({"Content-Type": "text/plain"}, {"Content-Type": "application/json; charset=utf-16"},
                        {"Content-Type": "application/json", "Content-Encoding": "gzip"}):
            self.assert_error(self.client.post(BASE, content=json.dumps(self.body), headers=headers), 415, "UNSUPPORTED_MEDIA_TYPE")
        self.assertEqual(self.client.post(BASE, content=json.dumps(self.body),
            headers={"Content-Type": 'application/json; charset="UTF-8"'}).status_code, 202)

    def raw_request(self, chunks, headers=()):
        async def run():
            sent, consumed = [], 0
            iterator = iter(chunks)
            async def receive():
                nonlocal consumed
                consumed += 1
                try: return {"type": "http.request", "body": next(iterator), "more_body": True}
                except StopIteration: return {"type": "http.request", "body": b"", "more_body": False}
            async def send(message): sent.append(message)
            await self.app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                "scheme": "http", "method": "POST", "path": BASE, "raw_path": BASE.encode(),
                "query_string": b"", "root_path": "", "server": ("test", 80), "client": ("127.0.0.1", 1),
                "headers": [(b"content-type", b"application/json"), *headers]}, receive, send)
            start = next(message for message in sent if message["type"] == "http.response.start")
            body = b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body")
            return start, body, consumed
        return asyncio.run(run())

    def test_declared_and_chunked_body_limits_use_task_error_not_upload_error(self):
        start, body, consumed = self.raw_request([], [(b"content-length", str(MAX_TASK_BODY_BYTES + 1).encode())])
        self.assertEqual((start["status"], consumed), (413, 0))
        self.assertEqual(ErrorResponse.model_validate_json(body).error.code, "REQUEST_TOO_LARGE")
        for headers in ([], [(b"content-length", b"1")]):
            start, body, _ = self.raw_request([b" " * (MAX_TASK_BODY_BYTES // 2), b" " * (MAX_TASK_BODY_BYTES // 2 + 1)], headers)
            self.assertEqual(start["status"], 413)
            self.assertEqual(ErrorResponse.model_validate_json(body).error.code, "REQUEST_TOO_LARGE")
        self.assertEqual(self.repo.list().total, 0)

    def test_exact_body_limit_and_invalid_content_length(self):
        raw = json.dumps(self.body).encode()
        start, body, _ = self.raw_request([raw + b" " * (MAX_TASK_BODY_BYTES - len(raw))])
        self.assertEqual(start["status"], 202, body)
        for lengths in ([(b"content-length", b"-1")], [(b"content-length", b"1"), (b"content-length", b"2")]):
            start, body, consumed = self.raw_request([], lengths)
            self.assertEqual((start["status"], consumed), (400, 0))

    def test_definite_failure_has_task_id_failed_record_and_replay_does_not_resend(self):
        self.publisher.outcome = PublishOutcome.NOT_SENT
        headers = {"Idempotency-Key": str(uuid4())}
        error = self.assert_error(self.post(headers=headers), 503, "DISPATCH_FAILED", persisted=True)
        self.assertEqual(self.client.get(f"{BASE}/{error['task_id']}").json()["status"], "FAILED")
        self.assertEqual(self.post(headers=headers).status_code, 200)
        self.assertEqual(len(self.publisher.calls), 1)

    def test_unknown_dispatch_preserves_id_pending_and_replay_without_retry(self):
        self.publisher.outcome = PublishOutcome.UNKNOWN
        headers = {"Idempotency-Key": str(uuid4())}
        error = self.assert_error(self.post(headers=headers), 503, "DISPATCH_UNCERTAIN", persisted=True)
        detail = self.client.get(f"{BASE}/{error['task_id']}").json()
        self.assertEqual((detail["status"], detail["error_code"]), ("PENDING", "DISPATCH_UNCERTAIN"))
        replay = self.post(headers=headers)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()["id"], error["task_id"])
        self.assertEqual(len(self.publisher.calls), 1)

    def test_fast_worker_running_or_completed_is_not_overwritten_by_publish_ack(self):
        for complete in (False, True):
            def fast_worker(task_id, _message):
                token = uuid4()
                self.repo.claim(task_id, token, "test-only-worker")
                if complete:
                    self.repo.complete(task_id, token, f"outputs/{task_id}", "a" * 64, summary())
            self.publisher.action = fast_worker
            response = self.post()
            self.assertEqual(response.status_code, 202, response.text)
            self.assertEqual(response.json()["status"], "COMPLETED" if complete else "RUNNING")

    def test_unknown_or_contradictory_failure_does_not_overwrite_claimed_task(self):
        self.publisher.action = lambda task_id, _message: self.repo.claim(task_id, uuid4(), "test-worker")
        for outcome in (PublishOutcome.UNKNOWN, PublishOutcome.NOT_SENT):
            self.publisher.outcome = outcome
            error = self.assert_error(self.post(), 503, "DISPATCH_UNCERTAIN", persisted=True)
            self.assertEqual(self.repo.get_status(error["task_id"]), TaskStatus.RUNNING)

    def test_publisher_exception_or_state_commit_failure_is_uncertain_with_original_id(self):
        def broken(*_args): raise OSError("private credentials")
        self.publisher.action = broken
        self.assert_error(self.post(), 503, "DISPATCH_UNCERTAIN", persisted=True)
        self.publisher.action = None
        with patch.object(self.repo, "mark_queued", side_effect=TaskStoreError()):
            self.assert_error(self.post(), 503, "DISPATCH_UNCERTAIN", persisted=True)
        with patch.object(self.repo, "mark_dispatch_uncertain", side_effect=TaskStoreError()):
            self.publisher.outcome = PublishOutcome.UNKNOWN
            self.assert_error(self.post(), 503, "DISPATCH_UNCERTAIN", persisted=True)

    def test_database_failure_before_known_id_has_no_submission_id_or_publish(self):
        with patch.object(self.repo, "create", side_effect=TaskStoreError()):
            self.assert_error(self.post(), 503, "DATABASE_UNAVAILABLE")
        self.assertEqual(self.publisher.calls, [])
        with patch.object(self.repo, "list", side_effect=TaskStoreError()):
            self.assert_error(self.client.get(BASE), 503, "DATABASE_UNAVAILABLE")

    def test_cors_idempotency_header_request_ids_and_safe_unhandled_failure(self):
        preflight = self.client.options(BASE, headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,idempotency-key"})
        self.assertEqual(preflight.status_code, 200)
        self.assertIn("Idempotency-Key", preflight.headers["access-control-allow-headers"])
        self.assertNotIn("access-control-allow-credentials", preflight.headers)
        with patch.object(self.app.state.task_service, "list", side_effect=RuntimeError("private secret")):
            response = self.client.get(BASE, headers={"Origin": ORIGIN})
        self.assert_error(response, 500, "INTERNAL_ERROR")
        self.assertEqual(response.headers["access-control-allow-origin"], ORIGIN)
        self.assertNotIn("private secret", response.text)

    def test_runtime_export_matches_actual_operations_schemas_and_resolves_all_refs(self):
        runtime = self.client.get("/openapi.json").json()
        contract = build_contract()
        self.assertEqual(contract["x-implementation-status"], "implemented")
        self.assertEqual(set(contract["paths"]), {"/tasks", "/tasks/{task_id}"})
        for path, value in contract["paths"].items():
            self.assertEqual(runtime["paths"]["/api/v1" + path], value)
        for name, value in contract["components"]["schemas"].items():
            self.assertEqual(runtime["components"]["schemas"][name], value)
        schema503 = contract["paths"]["/tasks"]["post"]["responses"]["503"]["content"]["application/json"]["schema"]
        self.assertIn("anyOf", schema503)
        self.assertNotIn("$ref", schema503)
        def walk(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    target = contract
                    for part in value["$ref"].removeprefix("#/").split("/"): target = target[part]
                for item in value.values(): walk(item)
            elif isinstance(value, list):
                for item in value: walk(item)
        walk(contract)
        for path, expected in generate_outputs().items():
            self.assertEqual(path.read_text(encoding="utf-8"), expected)


if __name__ == "__main__":
    unittest.main()
