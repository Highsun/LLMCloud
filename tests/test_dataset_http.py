"""HTTP/ASGI behavior against isolated SQLite/files, including streaming failures."""

import asyncio
import errno
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import anyio
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response
from sqlalchemy.exc import OperationalError
from starlette.formparsers import SpooledTemporaryFile
from starlette.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.core.dataset_contract import MAX_DATASET_BYTES, MAX_MULTIPART_BYTES
from backend.app.main import create_app
from backend.app.api.datasets import upload_dataset
from backend.app.api.multipart import parse_dataset_form
from backend.app.models.dataset_schemas import DatasetDetail, DatasetPage
from backend.app.models.error_schemas import ErrorResponse
from scripts.export_dataset_contract import build_contract

RAW = '{"instruction":"什么是云计算？","output":"按需提供计算资源。"}'.encode()
BASE = "/api/v1/datasets"
ORIGIN = "http://localhost:5173"


def multipart(parts):
    """parts: (field, filename or None, raw bytes). Preserve duplicate/wrong types."""
    body = bytearray()
    for field, filename, value in parts:
        body.extend(f'--testboundary\r\nContent-Disposition: form-data; name="{field}"'.encode())
        if filename is not None:
            body.extend(f'; filename="{filename}"'.encode())
        body.extend(b"\r\n\r\n" + value + b"\r\n")
    body.extend(b"--testboundary--\r\n")
    return bytes(body)


class DatasetHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.settings = Settings(_env_file=None, data_dir=root / "data", log_dir=root / "logs", database_url="")
        self.app = create_app(self.settings)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.service = self.app.state.dataset_service

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def upload(self, raw=RAW, filename="train.jsonl", **kwargs):
        return self.client.post(BASE, files={"file": (filename, raw, "application/octet-stream")}, **kwargs)

    def post_parts(self, parts):
        return self.client.post(BASE, content=multipart(parts),
                                headers={"Content-Type": "multipart/form-data; boundary=testboundary"})

    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.text)
        payload = response.json()
        ErrorResponse.model_validate(payload)
        self.assertEqual(payload["error"]["code"], code)
        self.assertEqual(payload["error"]["request_id"], response.headers["x-request-id"])
        self.assertEqual(UUID(response.headers["x-request-id"]).version, 4)
        self.assertNotIn(str(self.settings.data_dir), response.text)
        return payload["error"]

    def assert_no_files(self):
        self.assertEqual(list((self.settings.data_dir / "datasets").rglob("*.part")), [])
        self.assertEqual(list((self.settings.data_dir / "datasets").rglob("train.jsonl")), [])
        self.assertEqual(self.service.list().total, 0)

    def raw_request(self, chunks, *, headers=(), disconnect=False):
        """Real ASGI receive chunks; TestClient/httpx otherwise aggregates generators."""
        async def call():
            iterator = iter(chunks)
            sent, receives = [], 0

            async def receive():
                nonlocal receives
                receives += 1
                try:
                    chunk = next(iterator)
                except StopIteration:
                    if disconnect:
                        return {"type": "http.disconnect"}
                    return {"type": "http.request", "body": b"", "more_body": False}
                return {"type": "http.request", "body": chunk, "more_body": True}

            async def send(message):
                sent.append(message)

            scope = {
                "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                "scheme": "http", "method": "POST", "path": BASE, "raw_path": BASE.encode(),
                "query_string": b"", "root_path": "", "server": ("testserver", 80),
                "client": ("127.0.0.1", 12345), "headers": [
                    (b"content-type", b"multipart/form-data; boundary=testboundary"), *headers,
                ],
            }
            await self.app(scope, receive, send)
            return sent, receives

        return asyncio.run(call())

    def assert_raw_error(self, result, status, code):
        sent, _ = result
        start = next(item for item in sent if item["type"] == "http.response.start")
        self.assertEqual(start["status"], status)
        raw = b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body")
        error = ErrorResponse.model_validate_json(raw).error
        self.assertEqual(error.code, code)
        self.assertEqual(str(error.request_id).encode(), dict(start["headers"])[b"x-request-id"])

    def test_upload_detail_list_persistence_and_raw_bytes(self):
        raw = b'\xef\xbb\xbf\n' + RAW + b'\r\n\n' + RAW
        response = self.upload(raw, filename="../../示例.JSONL", data={"name": "  课程数据  "})
        self.assertEqual(response.status_code, 201, response.text)
        detail = DatasetDetail.model_validate(response.json())
        self.assertEqual(detail.name, "课程数据")
        self.assertEqual(detail.original_filename, "示例.JSONL")
        self.assertEqual(detail.row_count, 2)
        self.assertEqual(detail.size_bytes, len(raw))
        self.assertEqual(detail.sha256, hashlib.sha256(raw).hexdigest())
        self.assertTrue(response.json()["created_at"].endswith("Z"))
        self.assertEqual(response.headers["location"], f"{BASE}/{detail.id}")
        self.assertEqual((self.settings.data_dir / "datasets" / str(detail.id) / "train.jsonl").read_bytes(), raw)
        self.assertEqual(self.client.get(response.headers["location"]).json(), response.json())
        page = DatasetPage.model_validate(self.client.get(BASE).json())
        self.assertEqual(page.total, 1)
        self.assertEqual(page.items[0].id, detail.id)
        self.assertNotIn("storage_path", response.text)
        self.assertNotIn("user_id", response.text)
        # A new application/connection sees the same persisted resource.
        with TestClient(create_app(self.settings)) as reopened:
            self.assertEqual(reopened.get(response.headers["location"]).json(), response.json())

    def test_default_name_duplicate_upload_and_pagination(self):
        self.assertEqual(self.client.get(BASE).json(), {"items": [], "total": 0, "page": 1, "page_size": 20, "total_pages": 0})
        first, second = self.upload().json(), self.upload().json()
        self.assertEqual(first["name"], "train.jsonl")
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(first["sha256"], second["sha256"])
        pages = [self.client.get(BASE, params={"page": page, "page_size": 1}).json() for page in (1, 2, 3)]
        self.assertEqual([page["total_pages"] for page in pages], [2, 2, 2])
        self.assertEqual({page["items"][0]["id"] for page in pages[:2]}, {first["id"], second["id"]})
        self.assertEqual(pages[2]["items"], [])
        self.assertEqual(pages[2]["page"], 3)
        self.assertEqual(self.client.get(BASE + "?page=" + "9" * 100).json()["items"], [])

    def test_detail_uuid_validation_and_metadata_only(self):
        self.assert_error(self.client.get(BASE + "/bad-uuid"), 422, "VALIDATION_ERROR")
        self.assert_error(self.client.get(BASE + "/" + str(uuid4())), 404, "DATASET_NOT_FOUND")
        # A syntactically valid UUID of any version reaches resource lookup.
        self.assert_error(self.client.get(BASE + "/00000000-0000-1000-8000-000000000000"), 404, "DATASET_NOT_FOUND")
        response = self.upload()
        identifier = response.json()["id"]
        (self.settings.data_dir / "datasets" / identifier / "train.jsonl").unlink()
        self.assertEqual(self.client.get(response.headers["location"]).json(), response.json())

    def test_query_rejects_unknown_duplicate_empty_float_and_out_of_range(self):
        for query in ("search=x", "page=1&page=2", "page_size=1&page_size=2", "page=", "page=x",
                      "page=1.0", "page=1.5", "page=-1", "page=0", "page_size=0", "page_size=101"):
            with self.subTest(query=query):
                self.assert_error(self.client.get(BASE + "?" + query), 422, "VALIDATION_ERROR")

    def test_error_detail_limit(self):
        response = self.client.get(BASE, params={f"extra{i}": "private-value" for i in range(15)})
        error = self.assert_error(response, 422, "VALIDATION_ERROR")
        self.assertEqual(len(error["details"]), 10)
        self.assertTrue(error["details_truncated"])
        self.assertNotIn("private-value", response.text)

    def test_multipart_field_shapes(self):
        file = ("file", "train.jsonl", RAW)
        cases = [[], [("name", None, b"test")], [("file", None, RAW)],
                 [file, file], [file, ("name", None, b"a"), ("name", None, b"b")],
                 [file, ("name", "name.txt", b"a")], [file, ("storage_path", None, b"/secret")]]
        for parts in cases:
            with self.subTest(parts=parts):
                self.assert_error(self.post_parts(parts), 422, "VALIDATION_ERROR")
        self.assert_no_files()

    def test_name_normalization_controls_and_utf8_bytes(self):
        for value in (b"", b"   ", b"\nname", b"name\x7f", b"x" * 256, "😀".encode() * 257, b"\xff"):
            with self.subTest(value=value[:20]):
                self.assert_error(self.post_parts([("file", "train.jsonl", RAW), ("name", None, value)]), 422, "VALIDATION_ERROR")
        self.assert_no_files()

    def test_jsonl_content_errors_include_physical_line_and_no_raw_record(self):
        error = self.assert_error(self.upload(RAW + b'\n\n{"instruction":"SECRET-TRAINING-TEXT"}'), 422, "INVALID_DATASET")
        self.assertEqual(error["details"][0]["line"], 3)
        self.assertEqual(error["details"][0]["loc"], ["body", "file", "output"])
        self.assertNotIn("SECRET-TRAINING-TEXT", json.dumps(error))
        for value in (b"", b"\xff", b"{bad}", b'[]', b'{"instruction":"x","output":"x","input":null}'):
            with self.subTest(value=value):
                self.assert_error(self.upload(value), 422, "INVALID_DATASET")
        self.assert_no_files()

    def test_filename_validation(self):
        self.assert_error(self.upload(filename="train.csv"), 422, "INVALID_DATASET")
        for filename in (".jsonl", "x" * 256 + ".jsonl", "bad\x7fname.jsonl"):
            with self.subTest(filename=filename):
                self.assert_error(self.post_parts([("file", filename, RAW)]), 422, "VALIDATION_ERROR")
        self.assert_no_files()

    def test_content_type_encoding_boundary_and_truncated_form(self):
        self.assert_error(self.client.post(BASE, json={"file": "x"}), 415, "UNSUPPORTED_MEDIA_TYPE")
        self.assert_error(self.upload(headers={"Content-Encoding": "gzip"}), 415, "UNSUPPORTED_MEDIA_TYPE")
        self.assertEqual(self.upload(headers={"Content-Encoding": "identity"}).status_code, 201)
        for body, content_type in ((b"x", "multipart/form-data"), (b"x", "multipart/form-data; boundary="),
                                  (b"broken", "multipart/form-data; boundary=testboundary"),
                                  (multipart([("file", "train.jsonl", RAW)])[:-20], "multipart/form-data; boundary=testboundary")):
            with self.subTest(body=body):
                self.assert_error(self.client.post(BASE, content=body, headers={"Content-Type": content_type}), 400, "INVALID_MULTIPART")
        self.assertEqual(self.service.list().total, 1)

    def test_parser_count_and_text_buffer_limits(self):
        for parts in ([ ("file", "train.jsonl", RAW)] * 5,
                      [(f"field{i}", None, b"x") for i in range(5)],
                      [("name", None, b"x" * (64 * 1024 + 1))]):
            with self.subTest(count=len(parts)):
                self.assert_error(self.post_parts(parts), 400, "INVALID_MULTIPART")
        self.assert_no_files()

    def test_spool_disk_failure_returns_503(self):
        with patch("starlette.formparsers.SpooledTemporaryFile", side_effect=OSError(errno.ENOSPC, "SECRET")), self.assertLogs("backend.app.api.multipart", level="ERROR") as logs:
            response = self.upload()
        self.assert_error(response, 503, "STORAGE_UNAVAILABLE")
        self.assertNotIn("SECRET", response.text)
        self.assertIn(response.headers["x-request-id"], " ".join(logs.output))
        self.assert_no_files()

    def test_body_limit_declared_rejected_without_receiving(self):
        result = self.raw_request([], headers=[(b"content-length", str(MAX_MULTIPART_BYTES + 1).encode())])
        self.assert_raw_error(result, 413, "UPLOAD_TOO_LARGE")
        self.assertEqual(result[1], 0)
        self.assert_no_files()

    def test_body_limit_uses_real_chunks_without_or_with_false_length(self):
        body = multipart([("file", "train.jsonl", RAW)])
        for headers in ([], [(b"content-length", b"1")]):
            with self.subTest(headers=headers), patch("backend.app.api.middleware.MAX_MULTIPART_BYTES", len(body) - 1):
                result = self.raw_request([body[:40], body[40:]], headers=headers)
                self.assert_raw_error(result, 413, "UPLOAD_TOO_LARGE")
                self.assertEqual(result[1], 2)
        self.assert_no_files()

    def test_exact_body_limit_and_small_stream_chunks_accepted(self):
        body = multipart([("file", "train.jsonl", RAW)])
        with patch("backend.app.api.middleware.MAX_MULTIPART_BYTES", len(body)):
            result = self.raw_request([body[i:i + 3] for i in range(0, len(body), 3)])
        start = next(item for item in result[0] if item["type"] == "http.response.start")
        self.assertEqual(start["status"], 201)
        self.assertEqual(self.service.list().total, 1)

    def test_exact_50_mib_file_accepted_and_one_byte_more_rejected(self):
        # Valid record plus blank physical lines, none exceeding 1 MiB.
        remaining = MAX_DATASET_BYTES - len(RAW) - 1
        line = b" " * (1024 * 1024 - 1) + b"\n"
        raw = RAW + b"\n" + line * (remaining // len(line)) + b" " * (remaining % len(line))
        self.assertEqual(len(raw), MAX_DATASET_BYTES)
        response = self.upload(raw)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["size_bytes"], MAX_DATASET_BYTES)
        self.assert_error(self.upload(raw + b" "), 413, "UPLOAD_TOO_LARGE")
        self.assertEqual(self.service.list().total, 1)
        self.assertEqual(list((self.settings.data_dir / "datasets").rglob("*.part")), [])

    def test_spooled_files_close_on_malformed_overflow_disconnect_and_cancellation(self):
        real_factory = SpooledTemporaryFile
        spools = []

        def spool(*args, **kwargs):
            result = real_factory(*args, **kwargs)
            spools.append(result)
            return result

        prefix = multipart([("file", "train.jsonl", b"x" * (1024 * 1024 + 1))])[:-20]
        with patch("starlette.formparsers.SpooledTemporaryFile", side_effect=spool):
            self.assert_raw_error(self.raw_request([prefix]), 400, "INVALID_MULTIPART")
            with patch("backend.app.api.middleware.MAX_MULTIPART_BYTES", len(prefix) + 1):
                self.assert_raw_error(self.raw_request([prefix, b"xx"]), 413, "UPLOAD_TOO_LARGE")
            sent, _ = self.raw_request([prefix], disconnect=True)
            self.assertEqual(sent, [])
            # A receive-side cancellation must also release all already-spooled files.
            def cancelled_chunks():
                yield prefix
                raise asyncio.CancelledError()
            with self.assertRaises(asyncio.CancelledError):
                self.raw_request(cancelled_chunks())
        self.assertEqual(len(spools), 4)
        self.assertTrue(all(item.closed for item in spools))
        self.assert_no_files()

    def test_request_ids_cors_success_failure_and_preflight(self):
        response = self.upload(headers={"Origin": ORIGIN, "X-Request-ID": "untrusted"})
        self.assertEqual(response.headers["access-control-allow-origin"], ORIGIN)
        exposed = response.headers["access-control-expose-headers"].lower()
        self.assertIn("x-request-id", exposed)
        self.assertIn("location", exposed)
        self.assertEqual(UUID(response.headers["x-request-id"]).version, 4)
        self.assertNotEqual(response.headers["x-request-id"], "untrusted")
        failure = self.client.post(BASE, json={}, headers={"Origin": ORIGIN})
        self.assert_error(failure, 415, "UNSUPPORTED_MEDIA_TYPE")
        self.assertEqual(failure.headers["access-control-allow-origin"], ORIGIN)
        preflight = self.client.options(BASE, headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"})
        self.assertEqual(preflight.status_code, 200)
        self.assertEqual(UUID(preflight.headers["x-request-id"]).version, 4)
        foreign = self.client.get(BASE, headers={"Origin": "https://foreign.invalid"})
        self.assertNotIn("access-control-allow-origin", foreign.headers)
        self.assertNotEqual(response.headers["x-request-id"], foreign.headers["x-request-id"])

    def test_route_method_and_generic_http_errors(self):
        self.assert_error(self.client.get("/api/v1/nonexistent"), 404, "NOT_FOUND")
        wrong = self.client.delete(BASE)
        self.assert_error(wrong, 405, "METHOD_NOT_ALLOWED")
        self.assertIn("allow", wrong.headers)

        @self.app.get("/test-http-error", include_in_schema=False)
        def generic_error():
            raise HTTPException(429, detail="SECRET", headers={"Retry-After": "5"})

        response = self.client.get("/test-http-error")
        self.assert_error(response, 429, "HTTP_ERROR")
        self.assertEqual(response.headers["retry-after"], "5")
        self.assertNotIn("SECRET", response.text)

    def test_unknown_failure_safe_500_with_cors_and_request_log(self):
        with patch.object(self.service, "list", side_effect=RuntimeError("SECRET /home/private")), self.assertLogs("backend.app.api.middleware", level="ERROR") as logs:
            response = self.client.get(BASE, headers={"Origin": ORIGIN})
        self.assert_error(response, 500, "INTERNAL_ERROR")
        self.assertEqual(response.headers["access-control-allow-origin"], ORIGIN)
        self.assertNotIn("SECRET", response.text)
        self.assertIn(response.headers["x-request-id"], " ".join(logs.output))

    def test_storage_database_failures_are_503_and_leave_no_data(self):
        with patch("backend.app.services.datasets.os.open", side_effect=OSError(errno.ENOSPC, "SECRET")), self.assertLogs("backend.app.services.datasets", level="ERROR") as logs:
            response = self.upload()
        self.assert_error(response, 503, "STORAGE_UNAVAILABLE")
        self.assertIn(response.headers["x-request-id"], " ".join(logs.output))
        self.assertNotIn("SECRET", response.text)
        with patch.object(self.service, "session_factory", side_effect=OperationalError("SECRET", {}, Exception("SECRET"))):
            response = self.client.get(BASE)
        self.assert_error(response, 503, "DATABASE_UNAVAILABLE")
        self.assertNotIn("SECRET", response.text)
        self.assert_no_files()

    def test_upload_closes_form_files_after_service_and_runs_in_threadpool(self):
        files, thread_ids = [], []
        original = self.service.create

        @self.app.get("/test-thread", include_in_schema=False)
        async def event_loop_thread():
            return threading.get_ident()

        def create(source, **kwargs):
            files.append(source)
            thread_ids.append(threading.get_ident())
            self.assertFalse(source.closed)
            return original(source, **kwargs)

        event_thread = self.client.get("/test-thread").json()
        with patch.object(self.service, "create", side_effect=create):
            self.assertEqual(self.upload().status_code, 201)
            self.assert_error(self.upload(b"invalid"), 422, "INVALID_DATASET")
        self.assertTrue(all(source.closed for source in files))
        self.assertTrue(all(identifier != event_thread for identifier in thread_ids))

    def test_server_cancellation_waits_for_service_before_closing_upload(self):
        async def scenario():
            loop = asyncio.get_running_loop()
            started = asyncio.Event()
            release = threading.Event()
            sources = []
            original = self.service.create

            def create(source, **kwargs):
                sources.append(source)
                loop.call_soon_threadsafe(started.set)
                if not release.wait(timeout=5):
                    raise RuntimeError("test worker not released")
                self.assertFalse(source.closed)
                return original(source, **kwargs)

            body = multipart([("file", "train.jsonl", RAW)])

            async def receive():
                return {"type": "http.request", "body": body, "more_body": False}

            request = Request({"type": "http", "app": self.app, "headers": [
                (b"content-type", b"multipart/form-data; boundary=testboundary"),
            ]}, receive)
            with patch.object(self.service, "create", side_effect=create):
                task = asyncio.create_task(upload_dataset(request, Response(), self.service))
                try:
                    await asyncio.wait_for(started.wait(), timeout=5)
                    task.cancel()
                    await asyncio.sleep(0)
                    self.assertFalse(sources[0].closed)
                finally:
                    release.set()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
            self.assertTrue(sources[0].closed)

        asyncio.run(scenario())
        # Once persistence starts, cancellation may still commit; no automatic POST retry.
        self.assertEqual(self.service.list().total, 1)

    def test_cancelled_anyio_scope_still_closes_disk_backed_form(self):
        async def scenario():
            body = multipart([("file", "train.jsonl", b"x" * (1024 * 1024 + 1))])

            async def receive():
                return {"type": "http.request", "body": body, "more_body": False}

            request = Request({"type": "http", "app": self.app, "headers": [
                (b"content-type", b"multipart/form-data; boundary=testboundary"),
            ]}, receive)
            form = await parse_dataset_form(request)
            source = form["file"].file
            self.assertTrue(source._rolled)
            with patch("backend.app.api.datasets.parse_dataset_form", new=AsyncMock(return_value=form)):
                with anyio.CancelScope() as scope:
                    scope.cancel()
                    await upload_dataset(request, Response(), self.service)
            self.assertTrue(source.closed)

        asyncio.run(scenario())
        self.assert_no_files()

    def test_health_models_and_openapi_match_export(self):
        for path in ("/api/v1/health", "/api/v1/models"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(UUID(response.headers["x-request-id"]).version, 4)
        runtime = self.client.get("/openapi.json").json()
        contract = build_contract()
        for path, operations in contract["paths"].items():
            self.assertEqual(runtime["paths"]["/api/v1" + path], operations)
        for name, schema in contract["components"]["schemas"].items():
            self.assertEqual(runtime["components"]["schemas"][name], schema)
        post = runtime["paths"][BASE]["post"]
        self.assertIn("multipart/form-data", post["requestBody"]["content"])
        self.assertEqual(post["responses"]["422"]["content"]["application/json"]["schema"], {"$ref": "#/components/schemas/ErrorResponse"})


if __name__ == "__main__":
    unittest.main()
