"""Behavior and fixture checks for the CPU-only internal training boundary."""

import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from scripts.export_training_contract import generate_outputs, main as export_main
from trainer.contracts import (
    RuntimeOptions, TrainRequest, TrainResult, TrainingError, TrainingFailure,
    TrainingManifest, TrainingProgress, TrainingSnapshot,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "docs/examples/training"


def example(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


class TrainingContractTests(unittest.TestCase):
    def test_request_requires_pinned_model_and_private_execution_fields(self):
        value = example("request.json")
        request = TrainRequest.model_validate(value)
        self.assertIsInstance(request.dataset_path, Path)
        self.assertEqual(request.output_dir.name, str(request.task_id))
        with self.assertRaises(ValidationError):
            request.model_revision = "main"
        for update in ({"model_revision": "main"}, {"model_revision": "abcd"},
                       {"base_model": "Qwen/Qwen2.5-1.5B-Instruct"},
                       {"user_id": "client-supplied"}):
            with self.subTest(update=update), self.assertRaises(ValidationError):
                TrainRequest.model_validate({**value, **update})
        for field in ("model_revision", "cache_dir", "log_path"):
            invalid = copy.deepcopy(value)
            del invalid[field]
            with self.subTest(field=field), self.assertRaises(ValidationError):
                TrainRequest.model_validate(invalid)

    def test_internal_paths_are_absolute_and_task_isolated_without_io(self):
        value = example("request.json")
        output = value["output_dir"]
        for update in (
            {"dataset_path": "relative/train.jsonl"},
            {"dataset_path": "/srv/llmcloud/../train.jsonl"},
            {"output_dir": "/srv/llmcloud/data/outputs/other-task"},
            {"log_path": "/srv/llmcloud/logs/tasks/other-task.log"},
            {"validation_dataset_path": value["dataset_path"]},
            {"dataset_path": output + "/train.jsonl"},
            {"dataset_manifest_path": output + "/source.json"},
            {"cache_dir": output + "/cache"},
            {"cache_dir": "/srv/llmcloud/data/outputs"},
        ):
            with self.subTest(update=update), self.assertRaises(ValidationError):
                TrainRequest.model_validate({**value, **update})
        with patch.object(Path, "exists", side_effect=AssertionError("Unexpected filesystem access")):
            TrainRequest.model_validate(value)

    def test_runtime_defaults_and_strict_smoke_controls(self):
        self.assertEqual(RuntimeOptions().model_dump(),
                         {"precision": "bf16", "max_steps": None, "local_files_only": True})
        self.assertEqual(RuntimeOptions(precision="fp32", max_steps=1).max_steps, 1)
        for invalid in ({"max_steps": 0}, {"max_steps": -1}, {"max_steps": True},
                        {"max_steps": 1.5}, {"local_files_only": "false"},
                        {"precision": "auto"}, {"quantization": "4bit"}):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                RuntimeOptions(**invalid)

    def test_progress_real_values_bounds_and_utc(self):
        value = json.loads((EXAMPLES / "progress.jsonl").read_text().splitlines()[0])
        event = TrainingProgress.model_validate({**value, "recorded_at": "2026-10-22T16:00:01+08:00"})
        self.assertEqual(event.model_dump(mode="json")["recorded_at"], "2026-10-22T08:00:01Z")
        for update in ({"step": 0}, {"step": 3}, {"total_steps": 0},
                       {"step": True}, {"loss": float("nan")}, {"loss": float("inf")},
                       {"loss": -1.0}, {"loss": True}, {"epoch": -0.5},
                       {"learning_rate": -1.0}, {"recorded_at": "2026-10-22T08:00:01"},
                       {"recorded_at": 1792656000}, {"recorded_at": "1792656000"},
                       {"kind": "loading"}, {"contract_version": "2.0.0"}):
            with self.subTest(update=update), self.assertRaises(ValidationError):
                TrainingProgress.model_validate({**value, **update})

    def test_train_and_eval_can_share_optimizer_step(self):
        events = [TrainingProgress.model_validate_json(line)
                  for line in (EXAMPLES / "progress.jsonl").read_text().splitlines()]
        self.assertEqual([(event.kind, event.step) for event in events],
                         [("train", 1), ("train", 2), ("eval", 2)])
        self.assertEqual(events[-1].loss, 2.1)

    def test_result_cannot_mix_task_artifacts(self):
        value = example("result.json")
        TrainResult.model_validate(value)
        for update in ({"metrics_path": "/tmp/another-task/metrics.jsonl"},
                       {"adapter_dir": value["adapter_dir"] + "/wrong"},
                       {"manifest_path": "relative/manifest.json"}):
            with self.subTest(update=update), self.assertRaises(ValidationError):
                TrainResult.model_validate({**value, **update})

    def test_snapshot_is_portable_and_preserves_public_config(self):
        request = TrainRequest.model_validate(example("request.json"))
        snapshot = TrainingSnapshot.model_validate(example("training_config.json"))
        self.assertEqual(request.config, snapshot.config)
        self.assertEqual(snapshot.config.gradient_accumulation_steps, 8)
        self.assertEqual(snapshot.config.max_seq_length, 512)
        self.assertEqual(snapshot.runtime.max_steps, 2)
        self.assertNotIn("/srv/", snapshot.model_dump_json())
        self.assertNotIn("max_steps", snapshot.config.model_dump())

    def test_manifest_requires_complete_unique_safe_artifact_inventory(self):
        value = example("manifest.json")
        manifest = TrainingManifest.model_validate(value)
        self.assertEqual(manifest.status, "completed")
        for path in ("/tmp/adapter", "../secret", "adapter/../../secret", "adapter/./weights",
                     "adapter//weights", "adapter\\weights", "C:/weights",
                     "adapter/weights\x00", "tokenizer/config\njson",
                     "manifest.json", "train.jsonl", "checkpoints/step-1"):
            invalid = copy.deepcopy(value)
            invalid["artifacts"][0]["path"] = path
            with self.subTest(path=path), self.assertRaises(ValidationError):
                TrainingManifest.model_validate(invalid)
        for artifacts in (value["artifacts"][1:], value["artifacts"] + [value["artifacts"][0]]):
            with self.assertRaises(ValidationError):
                TrainingManifest.model_validate({**value, "artifacts": artifacts})

    def test_manifest_rejects_inconsistent_revision_time_and_eval(self):
        value = example("manifest.json")
        for update in ({"tokenizer_revision": "9" * 40},
                       {"finished_at": "2026-10-21T00:00:00Z"},
                       {"started_at": "2026-10-22T08:00:00"},
                       {"validation_dataset": None}, {"status": "failed"}):
            with self.subTest(update=update), self.assertRaises(ValidationError):
                TrainingManifest.model_validate({**value, **update})
        value["validation_dataset"] = None
        value["summary"]["eval_loss"] = None
        value["train_dataset"].pop("review_status")
        parsed = TrainingManifest.model_validate(value)
        self.assertIsNone(parsed.summary.eval_loss)
        self.assertEqual(parsed.train_dataset.review_status, "unknown")

    def test_manifest_cannot_describe_partial_or_full_parameter_run_as_success(self):
        value = example("manifest.json")
        for update in ({"completed_steps": 1}, {"trainable_parameters": 1000},
                       {"peak_memory_allocated_bytes": -1}, {"elapsed_seconds": float("inf")},
                       {"final_loss": float("nan")}):
            invalid = copy.deepcopy(value)
            invalid["summary"].update(update)
            with self.subTest(update=update), self.assertRaises(ValidationError):
                TrainingManifest.model_validate(invalid)
        invalid = copy.deepcopy(value)
        invalid["runtime"]["max_steps"] = 3
        with self.assertRaises(ValidationError):
            TrainingManifest.model_validate(invalid)

    def test_manifest_requires_data_hashes_and_environment_versions(self):
        value = example("manifest.json")
        for section, key, replacement in (
            ("train_dataset", "sha256", "invalid"),
            ("train_dataset", "row_count", 0),
            ("train_dataset", "review_status", "automatically_reviewed"),
            ("environment", "uv_lock_sha256", "invalid"),
            ("environment", "packages", {"torch": "2.9.1"}),
            ("environment", "working_tree_dirty", "false"),
        ):
            invalid = copy.deepcopy(value)
            invalid[section][key] = replacement
            with self.subTest(section=section, key=key), self.assertRaises(ValidationError):
                TrainingManifest.model_validate(invalid)

    def test_failure_is_structured_without_auto_retry_or_http_status(self):
        failure = TrainingFailure.model_validate(example("failure.json"))
        error = TrainingError(failure)
        self.assertIs(error.failure, failure)
        self.assertEqual(str(error), failure.message)
        for update in ({"code": "UNKNOWN"}, {"stage": "queued"}, {"http_status": 500},
                       {"raw_record": "training contents"}, {"message": ""}):
            with self.subTest(update=update), self.assertRaises(ValidationError):
                TrainingFailure.model_validate({**failure.model_dump(), **update})

    def test_generated_files_and_schema_references_are_current(self):
        for path, expected in generate_outputs().items():
            self.assertEqual(path.read_text(encoding="utf-8"), expected, str(path))
        schema = json.loads((ROOT / "docs/contracts/training.schema.json").read_text())
        self.assertEqual(schema["x-implementation-status"], "types_only")
        self.assertEqual(schema["x-contract-version"], "1.0.0")
        def walk(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    target = schema
                    for key in value["$ref"].removeprefix("#/").split("/"):
                        target = target[key]
                for item in value.values():
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
        walk(schema)

    def test_export_check_detects_missing_and_stale_files_without_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "example.json"
            for existing in (None, "stale"):
                if existing is not None:
                    target.write_text(existing)
                with patch("scripts.export_training_contract.generate_outputs", return_value={target: "expected"}), \
                     patch.object(sys, "argv", ["export_training_contract.py", "--check"]), \
                     redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    # Reporting paths normally reside under PROJECT_ROOT.
                    with patch("scripts.export_training_contract.PROJECT_ROOT", Path(temporary)):
                        self.assertEqual(export_main(), 1)
                self.assertEqual(target.read_text() if target.exists() else None, existing)

    def test_cpu_imports_and_original_import_locations_remain_usable(self):
        code = '''
import importlib.abc
import sys
class BlockTrainingImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch', 'transformers', 'datasets', 'peft', 'trl', 'accelerate'}:
            raise AssertionError('GPU dependency imported: ' + fullname)
sys.meta_path.insert(0, BlockTrainingImports())
from trainer.contracts import TrainRequest
from trainer.train import TrainRequest as OriginalRequest, train
from backend.app.main import create_app
assert OriginalRequest is TrainRequest
assert '/api/v1/datasets' in create_app().openapi()['paths']
try:
    train(None)
except Exception as error:
    from trainer.contracts import TrainingError
    assert isinstance(error, TrainingError)
    assert error.failure.code == 'INVALID_REQUEST'
else:
    raise AssertionError('Invalid input must fail before loading optional training libraries')
'''
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
