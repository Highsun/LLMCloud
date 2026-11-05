"""Real HTTP/SQLite and bounded files; synthetic events are explicitly CPU fixtures."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID, uuid1, uuid4

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.core.observability_contract import (
    MAX_LOG_READ_BYTES, MAX_METRIC_LINE_BYTES, MAX_METRICS_RESPONSE_BYTES, MAX_METRICS_SCAN_BYTES,
)
from backend.app.core.task_contract import PublishOutcome, TaskStatus
from backend.app.core.task_protocols import TaskStoreError
from backend.app.main import create_app
from backend.app.models.error_schemas import ErrorResponse
from backend.app.models.observability_schemas import LogsPage, MetricsPage
from backend.app.services.task_files import TaskFile
from backend.app.services.task_log_projection import project_log
from scripts.export_task_openapi import build_contract
from task_store_support import progress, summary
from trainer.contracts import TrainingFailure


class PublisherDouble:
    def publish(self, *_args):
        return PublishOutcome.ACCEPTED


def metric_bytes(*events):
    return b"".join((event.model_dump_json() + "\n").encode() for event in events)


def log_bytes(stage="model_loading", **fields):
    return (json.dumps({"recorded_at": "2026-11-04T01:00:00+00:00", "stage": stage, **fields},
                       ensure_ascii=False) + "\n").encode()


class TaskObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.settings = Settings(_env_file=None, data_dir=root / "data", log_dir=root / "logs", database_url="")
        self.app = create_app(self.settings, task_publisher=PublisherDouble())
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.repo = self.app.state.task_repository
        self.service = self.app.state.task_observability_service
        self.dataset = self.client.post("/api/v1/datasets", files={"file": (
            "fixture.jsonl", b'{"instruction":"x","output":"y"}\n')}).json()["id"]
        self.task_id = self.new_task()
        self.metrics_path = self.settings.data_dir / "outputs" / self.task_id / "metrics.jsonl"
        self.log_path = self.settings.log_dir / "tasks" / f"{self.task_id}.log"

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def new_task(self):
        response = self.client.post("/api/v1/tasks", json={"dataset_id": self.dataset})
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()["id"]

    def write(self, path, raw):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    def get(self, kind="metrics", task_id=None, **params):
        return self.client.get(f"/api/v1/tasks/{task_id or self.task_id}/{kind}", params=params,
                               headers={"Origin": "http://localhost:5173"})

    def error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.text)
        error = ErrorResponse.model_validate(response.json()).error
        self.assertEqual(error.code, code)
        self.assertEqual(str(error.request_id), response.headers["x-request-id"])
        self.assertNotIn(str(self.settings.data_dir), response.text)
        self.assertNotIn(str(self.settings.log_dir), response.text)
        return error

    def state(self, status, *, step=0):
        token = uuid4()
        self.assertIsNotNone(self.repo.claim(self.task_id, token, "cpu-test"))
        if step:
            self.repo.record_progress(self.task_id, token, progress(step))
        if status == TaskStatus.COMPLETED:
            self.assertTrue(self.repo.complete(self.task_id, token,
                output_key=f"outputs/{self.task_id}", manifest_sha256="a" * 64, summary=summary()))
        elif status == TaskStatus.FAILED:
            self.assertTrue(self.repo.fail(self.task_id, token, TrainingFailure(
                task_id=self.task_id, code="TRAINING_FAILED", stage="training", message="受控 CPU 失败。")))
        return token

    def test_missing_natural_sources_and_empty_existing_files_are_distinct(self):
        for kind in ("metrics", "logs"):
            response = self.get(kind)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["source_state"], "not_created")
            self.assertEqual(response.headers["cache-control"], "no-store")
        self.write(self.metrics_path, b"")
        self.write(self.log_path, b"")
        metrics, logs = self.get().json(), self.get("logs").json()
        self.assertEqual(metrics["source_state"], "ready")
        self.assertEqual(len(metrics["source_id"]), 64)
        self.assertEqual((metrics["items"], metrics["next_cursor"], metrics["has_more"]), ([], 0, False))
        self.assertEqual(logs["source_state"], "ready")
        self.assertEqual(logs["lines"], [])

    def test_missing_task_checked_before_disk_and_sql_failure_is_not_empty(self):
        self.write(self.metrics_path, metric_bytes(progress()))
        self.write(self.log_path, log_bytes())
        for kind in ("metrics", "logs"):
            self.error(self.get(kind, task_id=str(uuid4())), 404, "TASK_NOT_FOUND")
            with patch.object(self.repo, "get_detail", side_effect=TaskStoreError()), \
                    patch("backend.app.services.task_observability.open_task_file", side_effect=AssertionError("SQL first")):
                self.error(self.get(kind), 503, "DATABASE_UNAVAILABLE")

    def test_strict_unknown_duplicate_bad_queries_and_uuid_are_uniform(self):
        bad = {"metrics": ("cursor=1", "cursor=-1", "cursor=%2B1", "cursor=1.0", "cursor=1e2",
            "cursor=1&cursor=2", "source_id=bad", "source_id=" + "a" * 64 + "&source_id=" + "b" * 64,
            "limit=0", "limit=1001", "limit=1.0", "limit=１", "after_step=1", "path=/secret"),
            "logs": ("tail=0", "tail=501", "tail=1.0", "tail=%2B1", "tail=1&tail=2", "path=secret")}
        for kind, queries in bad.items():
            for query in queries:
                with self.subTest(kind=kind, query=query):
                    response = self.client.get(f"/api/v1/tasks/{self.task_id}/{kind}?{query}")
                    self.error(response, 422, "VALIDATION_ERROR")
            for task_id in ("bad", str(uuid1())):
                self.error(self.get(kind, task_id=task_id), 422, "VALIDATION_ERROR")
        self.assertEqual(self.get(limit="0001").status_code, 200)

    def test_pages_keep_both_kinds_offsets_retry_and_terminal_drain(self):
        events = [progress(1), progress(1, kind="eval"), progress(2), progress(2, kind="eval")]
        raw = metric_bytes(*events)
        self.write(self.metrics_path, raw)
        first_response = self.get(limit=1)
        self.assertEqual(first_response.status_code, 200, first_response.text)
        first = MetricsPage.model_validate(first_response.json())
        self.assertEqual(first.items[0].offset, 0)
        self.assertEqual(first.items[0].kind, "train")
        self.assertTrue(first.has_more)
        self.assertEqual(first.next_cursor, len(metric_bytes(events[0])))
        self.assertEqual(first_response.json(), self.get(limit=1).json())
        second = self.get(cursor=first.next_cursor, source_id=first.source_id, limit=1).json()
        self.assertEqual(second["items"][0]["kind"], "eval")
        self.state(TaskStatus.COMPLETED)
        third = self.get(cursor=second["next_cursor"], source_id=first.source_id, limit=2).json()
        self.assertEqual([item["kind"] for item in third["items"]], ["train", "eval"])
        self.assertFalse(third["has_more"])
        self.assertEqual(third["task_status"], "COMPLETED")
        drained = self.get(cursor=third["next_cursor"], source_id=first.source_id).json()
        self.assertEqual((drained["items"], drained["next_cursor"], drained["has_more"]), ([], len(raw), False))

    def test_flush_ahead_of_sql_zero_loss_utc_and_partial_append(self):
        zero = progress().model_copy(update={"loss": 0.0, "learning_rate": 0.0})
        first_line, second_line = metric_bytes(zero), metric_bytes(progress(2))
        self.write(self.metrics_path, first_line + second_line[:20])
        first = self.get().json()
        self.assertEqual((first["items"][0]["loss"], first["items"][0]["learning_rate"]), (0.0, 0.0))
        self.assertTrue(first["items"][0]["recorded_at"].endswith("Z"))
        self.assertEqual(first["task_status"], "QUEUED")  # metadata can lag a flushed event
        self.assertTrue(first["tail_incomplete"])
        self.assertFalse(first["has_more"])
        waiting = self.get(cursor=first["next_cursor"], source_id=first["source_id"]).json()
        self.assertEqual((waiting["items"], waiting["next_cursor"], waiting["has_more"]), ([], len(first_line), False))
        with self.metrics_path.open("ab") as stream:
            stream.write(second_line[20:])
        after = self.get(cursor=first["next_cursor"], source_id=first["source_id"]).json()
        self.assertEqual(after["source_id"], first["source_id"])
        self.assertEqual([item["step"] for item in after["items"]], [2])
        self.assertFalse(after["tail_incomplete"])

    def test_failed_partial_is_visible_completed_partial_or_empty_is_corrupt(self):
        self.state(TaskStatus.FAILED, step=1)
        self.write(self.metrics_path, metric_bytes(progress()) + b'{"half":')
        response = self.get()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["tail_incomplete"])
        task = self.new_task()
        self.task_id = task
        self.metrics_path = self.settings.data_dir / "outputs" / task / "metrics.jsonl"
        self.state(TaskStatus.COMPLETED)
        for raw in (b"", metric_bytes(progress()) + b'{"half":'):
            self.write(self.metrics_path, raw)
            self.error(self.get(), 500, "METRICS_CORRUPTED")

    def test_cursor_rejects_nonboundary_wrong_identity_other_task_replacement_truncation_and_missing(self):
        raw = metric_bytes(progress(), progress(2))
        self.write(self.metrics_path, raw)
        first = self.get(limit=1).json()
        for params in ({"cursor": 1, "source_id": first["source_id"]},
                       {"cursor": len(raw) + 1, "source_id": first["source_id"]},
                       {"source_id": "f" * 64}):
            self.error(self.get(**params), 409, "METRICS_CURSOR_INVALID")
        task = self.new_task()
        self.write(self.metrics_path.parent.parent / task / "metrics.jsonl", raw)
        self.error(self.get(task_id=task, source_id=first["source_id"]), 409, "METRICS_CURSOR_INVALID")
        replaced = self.metrics_path.with_suffix(".new")
        replaced.write_bytes(raw)
        replaced.replace(self.metrics_path)
        self.error(self.get(source_id=first["source_id"]), 409, "METRICS_CURSOR_INVALID")
        current = self.get(limit=1).json()
        self.metrics_path.write_bytes(b"")
        self.error(self.get(cursor=current["next_cursor"], source_id=current["source_id"]), 409, "METRICS_CURSOR_INVALID")
        self.metrics_path.unlink()
        self.error(self.get(source_id=current["source_id"]), 409, "METRICS_CURSOR_INVALID")

    def test_corrupt_complete_lines_are_not_skipped(self):
        valid = metric_bytes(progress())
        samples = [b"\n", b"not json\n", b"\xff\n", b"[]\n", b'{"loss":NaN}\n',
                   valid.replace(b'"loss":1.0', b'"loss":1.0,"loss":2.0'),
                   valid.replace(b'"loss":1.0', b'"loss":1e999'), valid + valid,
                   valid + metric_bytes(progress(2, total=3)),
                   metric_bytes(progress(1, kind="eval"), progress(1)),
                   b" " * MAX_METRIC_LINE_BYTES + b"\n", b"x" * MAX_METRIC_LINE_BYTES,
                   b"x" * (MAX_METRICS_SCAN_BYTES + 10)]
        for raw in samples:
            with self.subTest(raw=raw[:40]):
                self.write(self.metrics_path, raw)
                self.error(self.get(), 500, "METRICS_CORRUPTED")

    def test_cross_page_predecessor_checks_order_and_total(self):
        self.write(self.metrics_path, metric_bytes(progress(), progress(2)))
        first = self.get(limit=1).json()
        self.write(self.metrics_path, metric_bytes(progress(), progress(1)))
        self.error(self.get(cursor=first["next_cursor"], source_id=first["source_id"]), 500, "METRICS_CORRUPTED")

    def test_byte_budget_reserves_lookahead_and_all_pages_advance(self):
        events = [progress(i, total=80) for i in range(1, 81)]
        raw = b"".join(b" " * 14000 + metric_bytes(event) for event in events)
        self.write(self.metrics_path, raw)
        original = TaskFile.read
        reads = []
        def capture(source, count, offset):
            reads.append((count, offset))
            return original(source, count, offset)
        cursor, identity, steps = 0, None, []
        for _ in range(6):
            reads.clear()
            params = {"cursor": cursor, "limit": 1000}
            if identity: params["source_id"] = identity
            with patch.object(TaskFile, "read", capture):
                response = self.get(**params)
            self.assertEqual(response.status_code, 200, response.text)
            page = response.json()
            self.assertLessEqual(sum(count for count, _ in reads), MAX_METRICS_SCAN_BYTES)
            self.assertLessEqual(len(response.content), MAX_METRICS_RESPONSE_BYTES)
            self.assertGreater(page["next_cursor"], cursor)
            steps.extend(item["step"] for item in page["items"])
            cursor, identity = page["next_cursor"], page["source_id"]
            if not page["has_more"]: break
        self.assertEqual(steps, list(range(1, 81)))
        self.assertEqual(cursor, len(raw))

    def test_known_progress_or_completed_missing_sources_are_errors_without_state_mutation(self):
        self.state(TaskStatus.RUNNING, step=1)
        before = self.repo.get_detail(self.task_id).model_dump_json()
        self.error(self.get(), 500, "METRICS_UNAVAILABLE")
        self.error(self.get("logs"), 500, "LOGS_UNAVAILABLE")
        self.assertEqual(self.repo.get_detail(self.task_id).model_dump_json(), before)

    def test_completed_missing_sources_are_not_waiting(self):
        self.state(TaskStatus.COMPLETED)
        self.error(self.get(), 500, "METRICS_UNAVAILABLE")
        self.error(self.get("logs"), 500, "LOGS_UNAVAILABLE")

    def test_log_tail_defaults_maximum_and_snapshot_replacement(self):
        self.write(self.log_path, b"".join(log_bytes("training", total_steps=i, gradient_accumulation_steps=1)
                                         for i in range(1, 602)))
        first = self.get("logs").json()
        self.assertEqual(len(first["lines"]), 100)
        self.assertTrue(first["truncated"])
        self.assertEqual(json.loads(first["lines"][-1])["total_steps"], 601)
        self.assertEqual(self.get("logs").json(), first)
        self.assertLessEqual(len(self.get("logs", tail=500).json()["lines"]), 500)
        self.write(self.log_path, log_bytes("saving"))
        self.assertEqual(len(self.get("logs").json()["lines"]), 1)

    def test_log_window_reads_at_most_64k_and_does_not_decode_partial_prefix(self):
        self.write(self.log_path, b"x" * (MAX_LOG_READ_BYTES * 2) + b"\n" + log_bytes("saving"))
        original, reads = TaskFile.read, []
        def capture(source, count, offset):
            reads.append(count)
            return original(source, count, offset)
        with patch.object(TaskFile, "read", capture):
            response = self.get("logs")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["truncated"])
        self.assertEqual(len(response.json()["lines"]), 1)
        self.assertLessEqual(sum(reads), MAX_LOG_READ_BYTES)

    def test_log_max_tail_returns_exactly_500_when_window_allows_it(self):
        self.write(self.log_path, log_bytes() * 501)
        self.assertLess(self.log_path.stat().st_size, MAX_LOG_READ_BYTES)
        page = self.get("logs", tail=500).json()
        self.assertEqual(len(page["lines"]), 500)
        self.assertTrue(page["truncated"])
        self.assertEqual(page["filtered_lines"], 0)

    def test_log_partial_tail_and_invalid_complete_lines_have_distinct_flags(self):
        self.write(self.log_path, log_bytes("saving") + b"bad json\n\xff\n" + b'{"partial":')
        page = LogsPage.model_validate(self.get("logs").json())
        self.assertEqual(len(page.lines), 1)
        self.assertEqual(page.filtered_lines, 2)
        self.assertTrue(page.tail_incomplete)
        self.assertFalse(page.truncated)
        self.write(self.log_path, b"x" * (MAX_LOG_READ_BYTES + 1))
        page = self.get("logs").json()
        self.assertTrue(page["tail_incomplete"])
        self.assertTrue(page["truncated"])

    def test_log_filter_counts_candidates_once_and_does_not_refill(self):
        self.write(self.log_path, log_bytes("saving") * 3 + log_bytes("unknown") + log_bytes("model_loading", secret="token"))
        page = self.get("logs", tail=2).json()
        self.assertEqual(len(page["lines"]), 1)
        self.assertEqual(page["filtered_lines"], 2)
        self.assertTrue(page["truncated"])
        self.assertNotIn("token", str(page))

    def test_log_nested_projection_omits_paths_text_and_unsafe_values(self):
        diagnostic = [{"type": "ValueError", "message": "credential", "frames": [
            {"file": "train.py", "function": "train", "line": 42, "raw": "secret"},
            {"file": "/home/private.py", "function": "bad", "line": 1}]}]
        self.write(self.log_path, log_bytes("failed", failure={"task_id": self.task_id,
            "code": "TRAINING_FAILED", "stage": "training", "message": "<script>credential /secret</script>"}, diagnostic=diagnostic)
            + log_bytes("parameters", total_parameters=True, trainable_parameters=4,
                target_modules=["/secret"], base_sha256_before="/secret", unexpected="credential")
            + log_bytes("data_verified", train={"sha256": "a" * 64, "path": "/secret", "review_status": "reviewed",
                "build_id": "<script>"}, validation=None))
        page = self.get("logs").json()
        self.assertEqual(page["filtered_lines"], 3)
        text = "\n".join(page["lines"])
        for secret in ("credential", "/secret", "/home/private", "<script>", '"message"', '"raw"'):
            self.assertNotIn(secret, text)
        failure = json.loads(page["lines"][0])
        self.assertEqual(failure["failure"]["code"], "TRAINING_FAILED")
        self.assertEqual(failure["diagnostic"][0]["frames"], [{"file": "train.py", "function": "train", "line": 42}])
        self.assertEqual(json.loads(page["lines"][1])["trainable_parameters"], 4)

    def test_logs_metric_projection_reuses_real_event_and_safe_timestamp(self):
        event = progress().model_dump(mode="json")
        self.write(self.log_path, log_bytes("metric", **event, framework_learning_rate=0.0))
        page = self.get("logs").json()
        self.assertEqual(page["filtered_lines"], 0)
        self.assertEqual(json.loads(page["lines"][0])["loss"], 1.0)
        for raw in (b'{"recorded_at":"bad","stage":"saving"}', b'{"stage":"saving","stage":"saving"}',
                    b"[]", log_bytes("metric", **{**event, "loss": float("inf")})):
            self.assertEqual(project_log(raw, UUID(self.task_id)), (None, True))

    def test_observed_log_disappearance_at_zero_step_is_not_waiting(self):
        self.write(self.log_path, log_bytes())
        self.assertEqual(self.get("logs").status_code, 200)
        self.log_path.unlink()
        self.error(self.get("logs"), 500, "LOGS_UNAVAILABLE")

    def test_symlink_file_directory_root_ancestor_hardlink_fifo_and_io_are_rejected(self):
        outside = Path(self.temp.name) / "outside"
        outside.write_bytes(metric_bytes(progress()))
        for path, kind, code in ((self.metrics_path, "metrics", "METRICS_UNAVAILABLE"),
                                 (self.log_path, "logs", "LOGS_UNAVAILABLE")):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(outside)
            self.error(self.get(kind), 500, code)
            path.unlink()
            os.link(outside, path)
            self.error(self.get(kind), 500, code)
            path.unlink()
            os.mkfifo(path)
            self.error(self.get(kind), 500, code)
            path.unlink()
            path.mkdir()
            self.error(self.get(kind), 500, code)
            path.rmdir()
        # An in-root directory symlink is equally forbidden.
        self.metrics_path.parent.rmdir()
        self.metrics_path.parent.symlink_to(outside.parent, target_is_directory=True)
        self.error(self.get(), 500, "METRICS_UNAVAILABLE")
        self.metrics_path.parent.unlink()
        with patch("backend.app.services.task_files.os.open", side_effect=PermissionError("/private secret")):
            self.error(self.get(), 500, "METRICS_UNAVAILABLE")
            self.error(self.get("logs"), 500, "LOGS_UNAVAILABLE")

    def test_replacement_during_read_is_rejected_and_descriptors_closed(self):
        self.write(self.metrics_path, metric_bytes(progress()))
        original = TaskFile.read
        replaced = False
        def replace(source, count, offset):
            nonlocal replaced
            result = original(source, count, offset)
            if not replaced:
                new = self.metrics_path.with_suffix(".swap")
                new.write_bytes(self.metrics_path.read_bytes())
                new.replace(self.metrics_path)
                replaced = True
            return result
        before = len(list(Path("/proc/self/fd").iterdir()))
        with patch.object(TaskFile, "read", replace):
            self.error(self.get(), 409, "METRICS_CURSOR_INVALID")
        self.assertEqual(len(list(Path("/proc/self/fd").iterdir())), before)

    def test_configured_root_and_ancestor_replaced_with_links_are_rejected(self):
        self.write(self.log_path, log_bytes())
        logs_root = self.settings.log_dir
        moved = logs_root.with_name("moved-logs")
        logs_root.rename(moved)
        logs_root.symlink_to(moved, target_is_directory=True)
        try:
            self.error(self.get("logs"), 500, "LOGS_UNAVAILABLE")
        finally:
            logs_root.unlink()
            moved.rename(logs_root)
        # Check an ancestor of the configured root as well, without moving SQL.
        parent = Path(self.temp.name) / "log-parent"
        child = parent / "child"
        child.mkdir(parents=True)
        self.service.settings = self.settings.model_copy(update={"log_dir": child})
        moved_parent = parent.with_name("moved-parent")
        parent.rename(moved_parent)
        parent.symlink_to(moved_parent, target_is_directory=True)
        self.error(self.get("logs"), 500, "LOGS_UNAVAILABLE")

    def test_openapi_queries_responses_export_and_cors(self):
        runtime, exported = self.app.openapi(), build_contract()
        for kind, query, model in (("metrics", ("cursor", "source_id", "limit"), "MetricsPage"),
                                   ("logs", ("tail",), "LogsPage")):
            path = f"/tasks/{{task_id}}/{kind}"
            operation = runtime["paths"]["/api/v1" + path]["get"]
            self.assertEqual([p["name"] for p in operation["parameters"] if p["in"] == "query"], list(query))
            self.assertEqual(operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"],
                             "#/components/schemas/" + model)
            self.assertEqual(exported["paths"][path]["get"], operation)
            response = self.get(kind)
            self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:5173")
            self.assertIn("X-Request-ID", response.headers["access-control-expose-headers"])
        self.assertIn("/api/v1/tasks/{task_id}/adapter", runtime["paths"])

    def test_file_reads_do_not_load_gpu_libraries_or_take_worker_lock(self):
        program = """
import sys, tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from backend.app.main import create_app
from backend.app.core.config import Settings
from unittest.mock import patch
class Publisher:
    def publish(self, *args): return 'accepted'
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    app = create_app(Settings(_env_file=None, data_dir=root/'data', log_dir=root/'logs'), task_publisher=Publisher())
    with TestClient(app) as client, patch('backend.app.core.worker_lock.WorkerInstanceLock.acquire', side_effect=AssertionError('GPU lock')):
        dataset = client.post('/api/v1/datasets', files={'file':('x.jsonl', b'{"instruction":"x","output":"y"}\\n')}).json()
        created = client.post('/api/v1/tasks',json={'dataset_id':dataset['id']}).json()
        from scripts.export_observability_contract import mock_metric_bytes
        source = root/'data'/'outputs'/created['id']/'metrics.jsonl'
        source.parent.mkdir()
        source.write_bytes(mock_metric_bytes())
        response = client.get('/api/v1/tasks/'+created['id']+'/metrics')
        assert response.status_code == 200, response.text
        assert len(response.json()['items']) == 4
for name in ('torch','numpy','transformers','datasets','peft','trl','accelerate'):
    assert name not in sys.modules, name
"""
        result = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
