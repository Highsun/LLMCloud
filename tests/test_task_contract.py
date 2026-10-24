"""Task contract behavior; no SQL repository, Broker or GPU execution is claimed."""

import copy
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import get_args
import unittest
from unittest.mock import patch
from uuid import uuid1, uuid4

from pydantic import ValidationError

from backend.app.core.config import Settings
from backend.app.core.task_contract import (
    DEFAULT_MODEL_REVISION, ExecutionOutcome, MAX_TASK_BODY_BYTES, PublishOutcome, TaskStatus,
)
from backend.app.core.task_protocols import Publisher, TaskExecutionSpec, TaskRepository, TaskStoreError
from backend.app.models.error_schemas import ErrorResponse
from backend.app.models.task_schemas import (
    TaskCreate, TaskDetail, TaskListQuery, TaskPage, TaskSubmissionErrorResponse,
    TaskSubmissionHeaders, TaskSummary,
)
from scripts.export_task_contract import generate_outputs, main as export_main
from trainer.contracts import FailureCode, RuntimeOptions
from trainer.lora_config import TrainingConfig

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "docs/examples/tasks"


def example(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


class TaskContractTests(unittest.TestCase):
    def test_original_import_and_training_defaults_remain_available(self):
        from backend.app.models.schemas import TaskCreate as OriginalCreate
        from backend.app.models.entities import TaskStatus as OriginalStatus, TrainingTask
        self.assertIs(OriginalCreate, TaskCreate)
        self.assertIs(OriginalStatus, TaskStatus)
        self.assertEqual(TrainingTask.__table__.c.status.type.enums, [status.value for status in TaskStatus])
        request = TaskCreate(dataset_id=uuid4())
        self.assertEqual(request.config.model_dump(), TrainingConfig().model_dump())
        self.assertEqual(request.base_model, "Qwen/Qwen2.5-0.5B-Instruct")

    def test_create_rejects_non_v4_and_private_execution_fields(self):
        source = example("create-request.json")
        invalid = [dict(dataset_id=str(uuid1())), dict(base_model="Qwen/Qwen2.5-7B-Instruct")]
        invalid += [{field: "client-supplied"} for field in (
            "revision", "model_revision", "runtime", "max_steps", "status", "user_id",
            "dataset_path", "output_path", "sha256", "size_bytes", "row_count",
        )]
        invalid += [{"config": {"max_steps": 2}}, {"config": {"lora_r": 0}}]
        for update in invalid:
            with self.subTest(update=update), self.assertRaises(ValidationError):
                TaskCreate.model_validate({**source, **update})

    def test_headers_extract_uuid_without_accepting_arbitrary_fields(self):
        value = example("submission-headers.json")
        parsed = TaskSubmissionHeaders.model_validate(value)
        self.assertEqual(str(parsed.idempotency_key), value["Idempotency-Key"])
        self.assertIsNone(TaskSubmissionHeaders().idempotency_key)
        self.assertEqual(TaskSubmissionHeaders(idempotency_key=parsed.idempotency_key), parsed)
        for invalid in ({"Idempotency-Key": str(uuid1())}, {"Idempotency-Key": ""},
                        {"Idempotency-Key": "not-a-uuid"}, {"X-Arbitrary": "value"}):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                TaskSubmissionHeaders.model_validate(invalid)

    def test_query_filters_and_pagination_validation(self):
        self.assertEqual(TaskListQuery().model_dump(), {"page": 1, "page_size": 20, "status": None})
        for status in TaskStatus:
            query = TaskListQuery(page="2", page_size="100", status=status.value)
            self.assertEqual((query.page, query.page_size, query.status), (2, 100, status))
        for invalid in ({"page": 0}, {"page": True}, {"page": 1.5}, {"page_size": 101},
                        {"page_size": False}, {"status": "ALL"}, {"status": "running"},
                        {"sort": "asc"}):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                TaskListQuery.model_validate(invalid)

    def test_all_detail_fixtures_and_five_statuses_are_valid(self):
        values = [TaskDetail.model_validate(json.loads(path.read_text()))
                  for path in sorted(EXAMPLES.glob("detail-*.json"))]
        self.assertEqual({value.status for value in values}, set(TaskStatus))
        self.assertEqual(len(values), 8)
        running = TaskDetail.model_validate(example("detail-running-saving.json"))
        self.assertEqual((running.status, running.progress), (TaskStatus.RUNNING, 1.0))
        failed = TaskDetail.model_validate(example("detail-failed-training.json"))
        self.assertEqual((failed.current_step, failed.total_steps, failed.progress), (1, 2, 0.5))

    def test_progress_has_real_step_and_null_semantics(self):
        source = example("detail-running.json")
        for update in ({"current_step": 1}, {"total_steps": 0}, {"progress": 0.0},
                       {"current_step": True}, {"total_steps": True},
                       {"total_steps": 2, "current_step": 3, "progress": 1.0},
                       {"total_steps": 2, "current_step": 1, "progress": None},
                       {"total_steps": 2, "current_step": 1, "progress": 0.2},
                       {"total_steps": 2, "progress": float("nan")},
                       {"total_steps": 2, "progress": float("inf")}):
            with self.subTest(update=update), self.assertRaises(ValidationError):
                TaskDetail.model_validate({**source, **update})

    def test_state_times_and_failure_diagnostics_are_consistent(self):
        running = example("detail-running.json")
        invalid = [
            (running, {"started_at": None}), (running, {"finished_at": "2026-10-24T01:00:04Z"}),
            (running, {"started_at": "2026-10-24T00:00:00Z"}),
            (running, {"error_code": "DISPATCH_UNCERTAIN"}),
            (running, {"error_message": "missing code"}),
            (example("detail-queued.json"), {"started_at": "2026-10-24T01:00:01Z"}),
            (example("detail-pending.json"), {"total_steps": 2, "progress": 0.0}),
            (example("detail-failed.json"), {"finished_at": None}),
            (example("detail-failed.json"), {"error_code": None, "error_message": None}),
            (example("detail-completed.json"), {"current_step": 1, "progress": 0.5}),
            (example("detail-completed.json"), {"started_at": None}),
            (example("detail-completed.json"), {"finished_at": "2026-10-24T00:00:00Z"}),
            (example("detail-completed.json"), {"error_code": "TRAINING_FAILED", "error_message": "failed"}),
        ]
        for source, update in invalid:
            with self.subTest(update=update), self.assertRaises(ValidationError):
                TaskDetail.model_validate({**source, **update})
        # Dispatch can fail before the Worker starts, with no known steps.
        TaskDetail.model_validate({**example("detail-failed.json"), "started_at": None,
                                   "error_code": "DISPATCH_FAILED"})

    def test_time_is_utc_and_only_sqlite_datetime_can_be_naive(self):
        source = example("detail-pending.json")
        for value in ("2026-10-24T09:00:00+08:00", datetime(2026, 10, 24, 1)):
            parsed = TaskDetail.model_validate({**source, "created_at": value})
            self.assertEqual(parsed.model_dump(mode="json")["created_at"], "2026-10-24T01:00:00Z")
        for value in ("2026-10-24T01:00:00", "2026-10-24 01:00:00Z", 1792803600, "1792803600"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                TaskDetail.model_validate({**source, "created_at": value})

    def test_private_output_and_legacy_config_alias_are_rejected(self):
        source = example("detail-running.json")
        for field in ("output_path", "log_path", "cache_dir", "celery_task_id", "claim_token",
                      "worker_id", "user_id", "training_config", "loss"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                TaskDetail.model_validate({**source, field: "must-not-leak"})
        page = TaskPage.model_validate(example("list-response.json"))
        self.assertTrue(all("config" not in item for item in page.model_dump(mode="json")["items"]))

    def test_pages_and_empty_or_beyond_end_results(self):
        for name in ("list-response.json", "empty-page.json", "beyond-last-page.json"):
            TaskPage.model_validate(example(name))
        source = example("list-response.json")
        for update in ({"total_pages": 9}, {"page": 2}, {"total": 0, "total_pages": 0},
                       {"page_size": 1, "total_pages": 5}, {"total": True}):
            with self.subTest(update=update), self.assertRaises(ValidationError):
                TaskPage.model_validate({**source, **update})

    def test_submission_error_extends_only_dispatch_errors(self):
        source = example("submission-error.json")
        TaskSubmissionErrorResponse.model_validate(source)
        for code in ("DISPATCH_UNCERTAIN", "DISPATCH_FAILED"):
            TaskSubmissionErrorResponse.model_validate({"error": {**source["error"], "code": code}})
        for code in ("DATABASE_UNAVAILABLE", "INVALID_DATASET"):
            with self.subTest(code=code), self.assertRaises(ValidationError):
                TaskSubmissionErrorResponse.model_validate({"error": {**source["error"], "code": code}})
        missing = copy.deepcopy(source)
        del missing["error"]["task_id"]
        with self.assertRaises(ValidationError):
            TaskSubmissionErrorResponse.model_validate(missing)
        with self.assertRaises(ValidationError):
            ErrorResponse.model_validate(source)
        database = ErrorResponse.model_validate(example("database-error.json"))
        self.assertNotIn("task_id", database.model_dump(mode="json")["error"])

    def test_business_errors_reuse_all_trainer_codes_without_changing_trainer(self):
        source = example("detail-failed.json")
        for code in (*get_args(FailureCode), "WORKER_INTERRUPTED", "TASK_ABANDONED",
                     "DISPATCH_FAILED", "DISPATCH_UNCERTAIN"):
            with self.subTest(code=code):
                self.assertEqual(TaskDetail.model_validate({**source, "error_code": code}).error_code, code)
        with self.assertRaises(ValidationError):
            TaskDetail.model_validate({**source, "error_code": "arbitrary"})

    def test_execution_snapshot_rejects_untrusted_keys_revisions_and_statistics(self):
        source = example("execution-spec.json")
        invalid = [{"dataset_key": key} for key in (
            "../train.jsonl", "/srv/data/train.jsonl", "datasets/other/train.jsonl",
            source["dataset_key"].replace("/", "\\"), source["dataset_key"] + "/../train.jsonl",
        )]
        invalid += [{"dataset_sha256": "bad"}, {"dataset_size_bytes": 0},
                    {"dataset_row_count": True}, {"model_revision": "main"},
                    {"runtime": {"local_files_only": False}}, {"contract_version": "0.0.0"},
                    {"task_id": str(uuid1())}, {"dataset_id": str(uuid4())}]
        for update in invalid:
            with self.subTest(update=update), self.assertRaises(ValidationError):
                TaskExecutionSpec.model_validate({**source, **update})
        with patch.object(Path, "exists", side_effect=AssertionError("Unexpected filesystem access")):
            TaskExecutionSpec.model_validate(source)

    def test_execution_snapshot_detaches_and_revalidates_mutable_config(self):
        source = example("execution-spec.json")
        config = TrainingConfig()
        spec = TaskExecutionSpec.model_validate({**source, "config": config})
        config.target_modules.append("k_proj")
        config.lora_r = 32
        self.assertEqual(spec.config.target_modules, ["q_proj", "v_proj"])
        self.assertEqual(spec.config.lora_r, 8)
        config.lora_r = -1
        with self.assertRaises(ValidationError):
            TaskExecutionSpec.model_validate({**source, "config": config})

    def test_protocols_are_structural_and_storage_errors_are_safe(self):
        class RepositoryDouble:
            def get_status(self, task_id): return TaskStatus.RUNNING
            def claim(self, task_id, claim_token, worker_id): return None
            def record_progress(self, task_id, claim_token, event): return False
            def complete(self, task_id, claim_token, output_key, manifest_sha256, summary): return False
            def fail(self, task_id, claim_token, failure): return False

        class PublisherDouble:
            def publish(self, task_id, celery_task_id): return PublishOutcome.UNKNOWN

        self.assertIsInstance(RepositoryDouble(), TaskRepository)
        self.assertIsInstance(PublisherDouble(), Publisher)
        self.assertNotIsInstance(object(), TaskRepository)
        self.assertEqual(RepositoryDouble().get_status(uuid4()), TaskStatus.RUNNING)
        self.assertEqual(str(TaskStoreError()), "任务存储暂时不可用。")
        self.assertEqual({value.value for value in PublishOutcome}, {"accepted", "not_sent", "unknown"})
        self.assertIn(ExecutionOutcome.RECONCILIATION_REQUIRED, list(ExecutionOutcome))

    def test_service_settings_pin_model_and_parse_internal_step_environment(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)
        self.assertEqual(settings.default_model_revision, DEFAULT_MODEL_REVISION)
        self.assertEqual((settings.training_precision, settings.training_max_steps), ("bf16", None))
        with patch.dict(os.environ, {"TRAINING_MAX_STEPS": "2"}, clear=True):
            settings = Settings(_env_file=None)
        self.assertEqual(settings.training_max_steps, 2)
        RuntimeOptions(precision=settings.training_precision, max_steps=settings.training_max_steps)
        for update in ({"default_model_revision": "main"}, {"training_precision": "auto"},
                       {"training_max_steps": 0}, {"training_max_steps": True},
                       {"training_max_steps": 1.5}, {"training_max_steps": "2.5"}):
            with self.subTest(update=update), patch.dict(os.environ, {}, clear=True), self.assertRaises(ValidationError):
                Settings(_env_file=None, **update)
        self.assertEqual(MAX_TASK_BODY_BYTES, 65536)

    def test_generated_schema_examples_and_references_have_no_drift(self):
        for path, expected in generate_outputs().items():
            self.assertEqual(path.read_text(encoding="utf-8"), expected, str(path))
        schema = json.loads((ROOT / "docs/contracts/tasks.schema.json").read_text())
        self.assertEqual(schema["x-contract-version"], "1.0.0")
        self.assertEqual(schema["x-implementation-status"], "types_only")
        self.assertNotIn("paths", schema)

        def walk(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    target = schema
                    for part in value["$ref"].removeprefix("#/").split("/"):
                        target = target[part]
                for item in value.values(): walk(item)
            elif isinstance(value, list):
                for item in value: walk(item)
        walk(schema)

    def test_check_mode_detects_drift_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stale.json"
            path.write_text("original")
            with patch("scripts.export_task_contract.generate_outputs", return_value={path: "new"}), \
                 patch.object(sys, "argv", ["export_task_contract.py", "--check"]), \
                 redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                # The stale path must be in PROJECT_ROOT for the relative diagnostic.
                with patch("scripts.export_task_contract.PROJECT_ROOT", Path(directory)):
                    self.assertEqual(export_main(), 1)
            self.assertEqual(path.read_text(), "original")

    def test_shared_types_import_without_sql_transport_or_training_packages(self):
        code = '''
import importlib.abc
import sys
class BlockHeavy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch', 'numpy', 'transformers', 'datasets', 'peft', 'trl',
                'accelerate', 'huggingface_hub', 'sqlalchemy', 'celery', 'fastapi', 'pydantic_settings'}:
            raise AssertionError('Forbidden import: ' + fullname)
sys.meta_path.insert(0, BlockHeavy())
from backend.app.core.task_protocols import TaskExecutionSpec, TaskRepository
from backend.app.models.task_schemas import TaskCreate, TaskDetail
from backend.app.models.schemas import TaskCreate as LegacyCreate
assert LegacyCreate is TaskCreate
'''
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_runtime_app_still_does_not_claim_task_api_is_implemented(self):
        from backend.app.main import create_app
        paths = create_app(Settings(_env_file=None)).openapi()["paths"]
        self.assertFalse(any("/tasks" in path for path in paths))
        self.assertFalse((ROOT / "docs/api/tasks.openapi.json").exists())


if __name__ == "__main__":
    unittest.main()
