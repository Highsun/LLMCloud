"""CPU failure/lifecycle checks. No mocked run is evidence of real GPU training."""

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from trainer.cli import main
from trainer.contracts import TrainRequest, TrainingError, TrainingFailure
from trainer.events import MetricWriter
from trainer.run_storage import finish, resolve_request, snapshot
from trainer.train import train

ROOT = Path(__file__).resolve().parents[1]


class TrainingExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.dataset = self.root / "train.jsonl"
        self.dataset.write_text('{"instruction":"q","output":"a"}\n')
        task_id = uuid4()
        self.request = TrainRequest(task_id=task_id, dataset_path=self.dataset,
            output_dir=self.root / "outputs" / str(task_id), cache_dir=self.root / "cache",
            log_path=self.root / "logs" / f"{task_id}.log", base_model="Qwen/Qwen2.5-0.5B-Instruct",
            model_revision="a" * 40, config={})

    def assert_code(self, code, call):
        with self.assertRaises(TrainingError) as context:
            call()
        self.assertEqual(context.exception.failure.code, code)
        return context.exception

    def emit(self, writer, step=1, total_steps=2, kind="train", **kwargs):
        return writer.emit(kind=kind, step=step, total_steps=total_steps, loss=kwargs.get("loss", 2.0),
                           learning_rate=0.0002, epoch=0.5)

    def test_callback_observes_flushed_identical_event(self):
        stream = io.StringIO()
        def callback(event):
            self.assertEqual(json.loads(stream.getvalue().splitlines()[-1]), event.model_dump(mode="json"))
        writer = MetricWriter(stream, callback)
        self.emit(writer)
        self.emit(writer, step=2)
        self.emit(writer, step=2, kind="eval")
        self.assertEqual(len(stream.getvalue().splitlines()), 3)

    def test_metric_order_total_and_nonfinite_are_rejected_without_append(self):
        for update in ({"step": 1}, {"step": 1, "kind": "eval"}, {"step": 2, "total_steps": 3}, {"step": 2, "loss": float("nan")}):
            stream = io.StringIO()
            writer = MetricWriter(stream)
            self.emit(writer, step=2)
            self.assert_code("TRAINING_FAILED", lambda: self.emit(writer, **update))
            self.assertEqual(len(stream.getvalue().splitlines()), 1)

    def test_callback_failure_preserves_event_and_safe_failure(self):
        stream = io.StringIO()
        def callback(_event):
            raise RuntimeError("private callback detail")
        error = self.assert_code("PROGRESS_CALLBACK_FAILED", lambda: self.emit(MetricWriter(stream, callback)))
        self.assertNotIn("private", str(error))
        self.assertEqual(len(stream.getvalue().splitlines()), 1)

    def test_flush_failure_does_not_call_consumer(self):
        class Broken(io.StringIO):
            def flush(self):
                raise OSError("disk full")
        events = []
        self.assert_code("ARTIFACT_WRITE_FAILED", lambda: self.emit(MetricWriter(Broken(), events.append)))
        self.assertEqual(events, [])

    def test_invalid_nested_config_is_revalidated_without_io(self):
        self.request.config.max_seq_length = 0
        self.assert_code("INVALID_REQUEST", lambda: train(self.request))
        self.assertFalse(self.request.output_dir.exists())

    def test_symlinked_output_parent_alias_cannot_enter_cache(self):
        self.request.cache_dir.mkdir()
        self.request.output_dir.parent.symlink_to(self.request.cache_dir, target_is_directory=True)
        self.assert_code("INVALID_REQUEST", lambda: resolve_request(self.request))
        self.assertFalse(self.request.output_dir.exists())

    def test_existing_output_or_log_is_preserved(self):
        self.request.output_dir.mkdir(parents=True)
        marker = self.request.output_dir / "owned_by_other_task"
        marker.write_text("keep")
        self.assert_code("INVALID_REQUEST", lambda: train(self.request))
        self.assertEqual(marker.read_text(), "keep")
        other = self.request.model_copy(update={"output_dir": self.root / str(self.request.task_id)})
        self.request.log_path.parent.mkdir(parents=True)
        self.request.log_path.write_text("existing log")
        self.assert_code("INVALID_REQUEST", lambda: train(other))
        self.assertEqual(self.request.log_path.read_text(), "existing log")

    def test_missing_cache_retains_safe_failure_no_success_and_no_fake_loss(self):
        error = self.assert_code("MODEL_NOT_CACHED", lambda: train(self.request))
        self.assertEqual(error.failure.task_id, self.request.task_id)
        self.assertTrue((self.request.output_dir / "failure.json").is_file())
        self.assertFalse((self.request.output_dir / "manifest.json").exists())
        self.assertFalse((self.request.output_dir / "metrics.jsonl").exists())
        log = self.request.log_path.read_text()
        self.assertNotIn('"loss"', log)
        self.assertNotIn(str(self.root), log)

    def test_bad_callback_and_distributed_launch_fail_before_reservation(self):
        self.assert_code("INVALID_REQUEST", lambda: train(self.request, False))
        with patch.dict("os.environ", {"WORLD_SIZE": "2"}):
            self.assert_code("INVALID_REQUEST", lambda: train(self.request))
        self.assertFalse(self.request.output_dir.exists())

    def test_snapshot_has_no_private_paths_and_copies_mutable_config(self):
        resolved = resolve_request(self.request)
        self.request.config.learning_rate = 0.001
        self.assertEqual(resolved.config.learning_rate, 0.0002)
        self.assertNotIn(str(self.root), snapshot(resolved).model_dump_json())

    def test_finish_missing_artifacts_does_not_publish_success(self):
        self.request.output_dir.mkdir(parents=True)
        self.assert_code("ARTIFACT_WRITE_FAILED", lambda: finish(self.request, None, None, None, None,
                         datetime.now(timezone.utc), 0))
        self.assertFalse((self.request.output_dir / "manifest.json").exists())

    def test_executor_failures_retain_diagnosis_and_never_publish_success(self):
        # Controlled failures exercise the CPU orchestrator, not actual OOM/GPU behavior.
        for code, stage in (("CUDA_OUT_OF_MEMORY", "training"), ("TRAINING_FAILED", "training"),
                            ("ARTIFACT_WRITE_FAILED", "saving")):
            with self.subTest(code=code):
                task_id = uuid4()
                request = self.request.model_copy(update={"task_id": task_id,
                    "output_dir": self.root / "outputs" / str(task_id),
                    "log_path": self.root / "logs" / f"{task_id}.log"})
                failure = TrainingError(TrainingFailure(code=code, stage=stage, message="controlled failure"))
                prepared = SimpleNamespace(train=SimpleNamespace(summary=SimpleNamespace(model_dump=lambda: {})), validation=None)
                fake_torch = SimpleNamespace(cuda=SimpleNamespace(is_initialized=lambda: False))
                with patch("trainer.train.verify_model_cache"), patch("trainer.train.load_training_tokenizer"), \
                        patch("trainer.train.prepare_training_data", return_value=prepared), \
                        patch("trainer.train.environment"), patch.dict(sys.modules, {"torch": fake_torch}), \
                        patch("trainer.hf_training.execute", side_effect=failure) as execute:
                    error = self.assert_code(code, lambda: train(request))
                    self.assertEqual(error.failure.stage, stage)
                    self.assertEqual(execute.call_count, 1)
                self.assertFalse((request.output_dir / "manifest.json").exists())
                self.assertEqual(json.loads((request.output_dir / "failure.json").read_text())["code"], code)
                self.assertIn('"stage": "failed"', request.log_path.read_text())

    def test_cli_success_stdout_is_only_result_json(self):
        from trainer.contracts import TrainResult
        result = TrainResult(adapter_dir=self.request.output_dir / "adapter", tokenizer_dir=self.request.output_dir / "tokenizer",
            metrics_path=self.request.output_dir / "metrics.jsonl", config_path=self.request.output_dir / "training_config.json",
            manifest_path=self.request.output_dir / "manifest.json")
        def execute(*args):
            print("framework output")
            return result
        args = ["trainer.train", "--dataset", str(self.dataset), "--revision", "a" * 40]
        with patch.object(sys, "argv", args), patch("trainer.train.train", side_effect=execute), \
                redirect_stderr(io.StringIO()) as error, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(), 0)
        self.assertEqual(json.loads(output.getvalue()), result.model_dump(mode="json"))
        self.assertIn("framework output", error.getvalue())

    def test_cli_invalid_config_returns_structured_error_and_no_output(self):
        args = ["trainer.train", "--dataset", str(self.dataset), "--revision", "main", "--data-dir", str(self.root)]
        with patch.object(sys, "argv", args), redirect_stderr(io.StringIO()) as error, redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(), 2)
        self.assertEqual(json.loads(error.getvalue())["code"], "INVALID_REQUEST")
        self.assertEqual(out.getvalue(), "")

    def test_cli_training_error_returns_nonzero_and_main_uses_shared_function(self):
        args = ["trainer.train", "--dataset", str(self.dataset), "--revision", "a" * 40, "--data-dir", str(self.root)]
        failure = TrainingError(TrainingFailure(code="CUDA_OUT_OF_MEMORY", stage="training", message="controlled test"))
        with patch.object(sys, "argv", args), patch("trainer.train.train", side_effect=failure) as run, \
                redirect_stderr(io.StringIO()) as error:
            self.assertEqual(main(), 1)
        self.assertEqual(json.loads(error.getvalue())["code"], "CUDA_OUT_OF_MEMORY")
        self.assertTrue(run.call_args.args[0].runtime.local_files_only)

    def test_execution_modules_are_cpu_importable(self):
        code = '''
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch','transformers','datasets','peft','trl','accelerate','safetensors'}:
            raise AssertionError('Unexpected training import')
sys.meta_path.insert(0, Block())
import trainer.train, trainer.cli, trainer.hf_training, trainer.events, trainer.run_storage
'''
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
