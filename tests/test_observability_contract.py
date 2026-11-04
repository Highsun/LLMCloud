"""M4 types and fixture behavior; no file reader, routes or GPU are claimed."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid1

from pydantic import ValidationError

from backend.app.core.observability_contract import (
    MAX_LOG_READ_BYTES, MAX_LOG_RESPONSE_BYTES, MAX_LOG_TAIL, MAX_SAFE_INTEGER,
    OBSERVABILITY_ERROR_STATUS, ObservabilityErrorCode, contract_limits,
)
from backend.app.core.observability_protocols import CompletedArtifactRepository, CompletedArtifactSpec
from backend.app.core.task_protocols import TaskRepository
from backend.app.models.error_schemas import ApiErrorCode, ErrorResponse
from backend.app.models.observability_schemas import (
    AdapterDownloadHeaders, AdapterQuery, DownloadBusyHeaders, LogsPage, LogsQuery,
    MetricRecord, MetricsPage, MetricsQuery,
)
from scripts import export_observability_contract as exporter
from trainer.contracts import TrainingProgress

ROOT = Path(__file__).resolve().parents[1]


def value(name):
    return exporter.build_examples()[name].model_dump(mode="json", by_alias=True)


class ObservabilityContractTests(unittest.TestCase):
    def test_query_defaults_and_decimal_text(self):
        self.assertEqual(MetricsQuery().model_dump(), {"cursor": 0, "source_id": None, "limit": 200})
        self.assertEqual(LogsQuery().tail, 100)
        query = MetricsQuery(cursor="00042", source_id="a" * 64, limit="1000")
        self.assertEqual((query.cursor, query.limit), (42, 1000))
        self.assertEqual(LogsQuery(tail="500").tail, 500)
        self.assertEqual(AdapterQuery().model_dump(), {})

    def test_queries_reject_loose_numbers_and_private_or_unknown_fields(self):
        for bad in (True, False, 1.0, 1.5, "1.0", "1e2", "+1", "-1", " 1", "１", "", "9" * 5000):
            for model, field in ((MetricsQuery, "cursor"), (MetricsQuery, "limit"), (LogsQuery, "tail")):
                with self.subTest(bad=str(bad)[:30], field=field), self.assertRaises(ValidationError):
                    model.model_validate({field: bad})
        for model in (MetricsQuery, LogsQuery, AdapterQuery):
            for key in ("path", "dataset_path", "user_id", "after_step", "tail_bytes"):
                with self.subTest(model=model.__name__, key=key), self.assertRaises(ValidationError):
                    model.model_validate({key: "client-supplied"})

    def test_cursor_source_pair_and_safe_integer_bounds(self):
        MetricsQuery(cursor=MAX_SAFE_INTEGER, source_id="b" * 64)
        MetricsQuery(cursor=0, source_id="b" * 64)
        for update in ({"cursor": 1}, {"cursor": MAX_SAFE_INTEGER + 1, "source_id": "b" * 64},
                       {"cursor": -1}, {"source_id": "A" * 64}, {"source_id": "b" * 63},
                       {"limit": 0}, {"limit": 1001}):
            with self.subTest(update=update), self.assertRaises(ValidationError):
                MetricsQuery.model_validate(update)
        for tail in (0, 501, -1):
            with self.subTest(tail=tail), self.assertRaises(ValidationError):
                LogsQuery(tail=tail)

    def test_metric_wrapper_preserves_training_event_and_zero(self):
        event = exporter.mock_events()[0]
        record = MetricRecord(**event.model_dump(), offset=0)
        self.assertEqual(record.model_dump(exclude={"offset"}), event.model_dump())
        self.assertNotIn("offset", event.model_dump())
        zero = MetricsPage.model_validate(value("metrics-zero-loss.json"))
        self.assertEqual((zero.items[0].loss, zero.items[0].learning_rate), (0.0, 0.0))
        for update in ({"offset": True}, {"offset": -1}, {"offset": MAX_SAFE_INTEGER + 1},
                       {"loss": float("nan")}, {"loss": float("inf")}, {"kind": "validation"},
                       {"recorded_at": "2026-11-04T01:00:00"}, {"step": 3}):
            with self.subTest(update=update), self.assertRaises(ValidationError):
                MetricRecord.model_validate({**record.model_dump(), **update})

    def test_fixture_pages_use_physical_bytes_and_retain_both_kinds(self):
        raw = exporter.mock_metric_bytes()
        first = MetricsPage.model_validate(value("metrics-first-page.json"))
        following = MetricsPage.model_validate(value("metrics-next-page.json"))
        initial = MetricsQuery.model_validate(value("metrics-query-initial.json"))
        query = MetricsQuery.model_validate(value("metrics-query-next.json"))
        self.assertEqual(len(first.items), initial.limit)
        self.assertEqual(query.cursor, first.next_cursor)
        self.assertEqual(first.next_cursor, following.items[0].offset)
        self.assertEqual(query.source_id, first.source_id)
        self.assertEqual(following.next_cursor, len(raw))
        records = first.items + following.items
        self.assertEqual([(r.kind, r.step) for r in records], [("train", 1), ("eval", 1), ("train", 2), ("eval", 2)])
        for index, record in enumerate(records):
            end = records[index + 1].offset if index + 1 < len(records) else len(raw)
            event = TrainingProgress.model_validate_json(raw[record.offset:end])
            self.assertEqual(event.model_dump(), record.model_dump(exclude={"offset"}))
        # A page can legitimately start at eval after the corresponding train
        # record was returned by the previous page.
        MetricsPage.model_validate({**first.model_dump(), "items": [records[1]], "has_more": True})

    def test_page_rejects_bad_order_duplicates_totals_and_cursor(self):
        source = value("metrics-first-page.json")
        invalid = []
        for field, bad in (("offset", 0), ("kind", "train"), ("total_steps", 3)):
            changed = deepcopy(source)
            changed["items"][1][field] = bad
            invalid.append(changed)
        invalid.append({**source, "items": list(reversed(source["items"]))})
        invalid.append({**source, "next_cursor": source["items"][-1]["offset"]})
        invalid.append({**source, "items": [], "has_more": True})
        for changed in invalid:
            with self.subTest(changed=changed), self.assertRaises(ValidationError):
                MetricsPage.model_validate(changed)

    def test_not_created_ready_empty_and_terminal_drained_are_distinct(self):
        missing = MetricsPage.model_validate(value("metrics-not-created.json"))
        empty = MetricsPage.model_validate(value("metrics-empty.json"))
        terminal = MetricsPage.model_validate(value("metrics-terminal-drained.json"))
        self.assertIsNone(missing.source_id)
        self.assertIsNotNone(empty.source_id)
        self.assertEqual(empty.next_cursor, 0)
        self.assertGreater(terminal.next_cursor, 0)
        self.assertEqual(terminal.items, [])
        partial = MetricsPage.model_validate(value("metrics-incomplete-tail.json"))
        self.assertTrue(partial.tail_incomplete)
        for update in ({"task_status": "COMPLETED"}, {"source_id": "a" * 64},
                       {"next_cursor": 1}, {"tail_incomplete": True}):
            with self.subTest(update=update), self.assertRaises(ValidationError):
                MetricsPage.model_validate({**missing.model_dump(), **update})
        with self.assertRaises(ValidationError):
            MetricsPage.model_validate({**empty.model_dump(), "source_id": None})
        with self.assertRaises(ValidationError):
            MetricsPage.model_validate({**partial.model_dump(), "task_status": "COMPLETED"})

    def test_page_strict_flags_ids_counts_and_no_server_paths(self):
        source = value("metrics-first-page.json")
        for update in ({"has_more": 1}, {"tail_incomplete": "false"}, {"task_id": str(uuid1())},
                       {"items": source["items"] * 501}, {"output_path": "/private/server/path"},
                       {"contract_version": "2.0.0"}, {"next_cursor": str(source["next_cursor"])}):
            with self.subTest(update=list(update)), self.assertRaises(ValidationError):
                MetricsPage.model_validate({**source, **update})

    def test_record_time_normalizes_utc_without_changing_the_optimizer_step(self):
        source = value("metrics-first-page.json")["items"][0]
        record = MetricRecord.model_validate({**source, "recorded_at": "2026-11-04T09:00:01+08:00"})
        self.assertEqual(record.model_dump(mode="json")["recorded_at"], "2026-11-04T01:00:01Z")
        self.assertEqual(record.step, source["step"])

    def test_logs_snapshot_flags_and_invalid_lines(self):
        for name in ("logs-not-created.json", "logs-empty.json", "logs-ready.json", "logs-truncated.json", "logs-filtered-tail.json"):
            LogsPage.model_validate(value(name))
        source = value("logs-ready.json")
        for update in ({"lines": ["line\nsecond"]}, {"lines": ["line\r"]}, {"lines": ["\0"]},
                       {"lines": ["\ud800"]}, {"lines": [1]}, {"lines": ["line"] * 501},
                       {"filtered_lines": True}, {"filtered_lines": -1},
                       {"filtered_lines": MAX_LOG_TAIL + 1}, {"truncated": 1}, {"path": "/server/logs"}):
            with self.subTest(update=list(update)), self.assertRaises(ValidationError):
                LogsPage.model_validate({**source, **update})

    def test_logs_enforce_serialized_utf8_response_bound(self):
        source = value("logs-ready.json")
        LogsPage.model_validate({**source, "lines": ["中" * 1000]})
        for lines in (["a" * MAX_LOG_READ_BYTES] * 4, ["😀" * MAX_LOG_READ_BYTES]):
            self.assertGreater(len(json.dumps({**source, "lines": lines}, ensure_ascii=False).encode()), MAX_LOG_RESPONSE_BYTES)
            with self.assertRaises(ValidationError):
                LogsPage.model_validate({**source, "lines": lines})

    def test_missing_log_source_cannot_claim_records_or_completion(self):
        source = value("logs-not-created.json")
        for update in ({"lines": ["actual"]}, {"filtered_lines": 1}, {"truncated": True},
                       {"tail_incomplete": True}, {"task_status": "COMPLETED"}):
            with self.subTest(update=update), self.assertRaises(ValidationError):
                LogsPage.model_validate({**source, **update})

    def test_download_headers_are_binary_metadata_with_canonical_task_identity(self):
        descriptor = AdapterDownloadHeaders.model_validate(value("adapter-headers.json"))
        headers = descriptor.as_headers()
        self.assertEqual(headers["Content-Type"], "application/zip")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn("task_id", headers)
        self.assertEqual(descriptor.archive_root, f"{descriptor.task_id}/")
        self.assertIn(descriptor.filename, headers["Content-Disposition"])
        self.assertEqual(DownloadBusyHeaders().model_dump(by_alias=True), {"Retry-After": "2"})
        for disposition in ('attachment; filename="../../private.zip"', 'attachment; filename="other.zip"',
                            headers["Content-Disposition"] + "\r\nInjected: value"):
            with self.subTest(disposition=disposition), self.assertRaises(ValidationError):
                AdapterDownloadHeaders.model_validate({**value("adapter-headers.json"), "Content-Disposition": disposition})
        for identity in (str(uuid1()), "../other", "bad\r\nheader"):
            with self.subTest(identity=identity), self.assertRaises(ValidationError):
                AdapterDownloadHeaders.for_task(identity)

    def test_completed_artifact_snapshot_is_detached_and_revalidates_nested_values(self):
        original = exporter.build_examples()["completed-artifact-spec.json"]
        detached = CompletedArtifactSpec.model_validate(original.model_dump())
        original.spec.config.target_modules.append("synthetic_new_module")
        self.assertNotIn("synthetic_new_module", detached.spec.config.target_modules)
        for update in ({"output_key": "outputs/other"}, {"output_key": "/private/output"},
                       {"manifest_sha256": "A" * 64}, {"status": "RUNNING"}):
            with self.subTest(update=update), self.assertRaises(ValidationError):
                CompletedArtifactSpec.model_validate({**detached.model_dump(), **update})
        wrong = detached.model_dump()
        wrong["training_summary"].update(completed_steps=3, total_steps=3)
        with self.assertRaises(ValidationError):
            CompletedArtifactSpec.model_validate(wrong)

    def test_revalidation_rejects_mutated_metric_instances(self):
        page = exporter.build_examples()["metrics-first-page.json"]
        object.__setattr__(page.items[0], "offset", True)
        with self.assertRaises(ValidationError):
            MetricsPage.model_validate(page)

    def test_new_repository_interface_does_not_change_worker_protocol(self):
        self.assertEqual({name for name in TaskRepository.__dict__ if not name.startswith("_")},
                         {"get_status", "claim", "record_progress", "complete", "fail"})
        self.assertEqual({name for name in CompletedArtifactRepository.__dict__ if not name.startswith("_")},
                         {"get_completed_artifact"})

    def test_errors_reuse_public_shape_and_status_table(self):
        examples = exporter.build_examples()
        for code, status in OBSERVABILITY_ERROR_STATUS.items():
            self.assertEqual(ApiErrorCode(code.value).value, code.value)
            name = f"error-{code.value.lower().replace('_', '-')}.json"
            parsed = ErrorResponse.model_validate(examples[name].model_dump())
            self.assertEqual(parsed.error.code.value, code.value)
            self.assertIn(status, (409, 413, 429, 500))
            self.assertNotIn("task_id", parsed.error.model_dump())
        self.assertEqual(set(OBSERVABILITY_ERROR_STATUS), set(ObservabilityErrorCode))

    def test_types_validate_without_opening_or_resolving_files(self):
        values = exporter.build_examples()
        with patch.object(Path, "open", side_effect=AssertionError("Types must not open files")), \
                patch.object(Path, "resolve", side_effect=AssertionError("Types must not resolve files")):
            for model in values.values():
                type(model).model_validate(model.model_dump(mode="json", by_alias=True))

    def test_types_and_exporter_import_without_transport_sql_or_training_libraries(self):
        program = """
import sys
from backend.app.models import observability_schemas
from backend.app.core import observability_protocols
from scripts import export_observability_contract
export_observability_contract.generate_outputs()
for name in ('fastapi','celery','sqlalchemy','torch','numpy','transformers','datasets','peft','trl','accelerate'):
    assert name not in sys.modules, name
"""
        result = subprocess.run([sys.executable, "-c", program], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_runtime_openapi_and_http_do_not_publish_unimplemented_routes(self):
        from fastapi.testclient import TestClient
        from backend.app.core.config import Settings
        from backend.app.main import create_app

        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            app = create_app(Settings(_env_file=None, data_dir=root / "data", log_dir=root / "logs", database_url=""))
            paths = app.openapi()["paths"]
            with TestClient(app) as client:
                for suffix in ("metrics", "logs", "adapter"):
                    path = f"/api/v1/tasks/{exporter.TASK_ID}/{suffix}"
                    self.assertNotIn(f"/api/v1/tasks/{{task_id}}/{suffix}", paths)
                    self.assertEqual(client.get(path).status_code, 404)

    def test_export_is_deterministic_valid_and_marks_mocks_without_runtime_claims(self):
        first, second = exporter.generate_outputs(), exporter.generate_outputs()
        self.assertEqual(first, second)
        for name, model in exporter.build_examples().items():
            payload = json.loads(first[ROOT / "docs/examples/observability" / name])
            type(model).model_validate(payload)
        schema = json.loads(first[ROOT / "docs/contracts/observability.schema.json"])
        self.assertEqual(schema["x-implementation-status"], "types_only")
        self.assertEqual(schema["x-http-implementation-status"], "not_asserted")
        self.assertNotIn("paths", schema)
        self.assertEqual(schema["x-limits"], contract_limits())
        index = json.loads(first[ROOT / "docs/examples/observability/index.json"])
        self.assertTrue(index["mock"])
        self.assertFalse(index["http_evidence"])
        self.assertEqual(index["fixtures"]["adapter-headers.json"]["usage"], "header_description_not_json_body")

    def test_check_detects_drift_missing_files_and_extra_json_without_writing(self):
        with tempfile.TemporaryDirectory() as name, patch.object(exporter, "PROJECT_ROOT", Path(name)):
            outputs = exporter.generate_outputs()
            for path, content in outputs.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            def check():
                with patch.object(sys, "argv", ["export", "--check"]), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    return exporter.main()
            self.assertEqual(check(), 0)
            path = next(iter(outputs))
            path.write_text("changed", encoding="utf-8")
            self.assertEqual(check(), 1)
            self.assertEqual(path.read_text(), "changed")
            path.write_text(outputs[path], encoding="utf-8")
            path.unlink()
            self.assertEqual(check(), 1)
            path.write_text(outputs[path], encoding="utf-8")
            extra = Path(name) / "docs/examples/observability/old.json"
            extra.write_text("{}", encoding="utf-8")
            self.assertEqual(check(), 1)
            self.assertEqual(extra.read_text(), "{}")


if __name__ == "__main__":
    unittest.main()
