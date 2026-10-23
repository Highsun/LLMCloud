"""CPU orchestration/error checks; GPU generation evidence is recorded separately."""

import importlib.util
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from trainer.contracts import TrainingError, TrainingFailure
from trainer.reload import reload_and_generate, validate_generation

ROOT = Path(__file__).resolve().parents[1]


class ReloadTests(unittest.TestCase):
    def assert_code(self, code, call):
        with self.assertRaises(TrainingError) as error:
            call()
        self.assertEqual(error.exception.failure.code, code)

    def test_generation_limits_are_checked_before_file_or_ml_access(self):
        for prompt, text, count in (("", "", 1), (" ", "", 1), (None, "", 1), ("x", None, 1),
                                    ("x" * 8193, "", 1), ("x", "", 0), ("x", "", 257), ("x", "", True)):
            with patch("trainer.reload.verify_training_artifacts", side_effect=AssertionError("Unexpected IO")):
                self.assert_code("INVALID_REQUEST", lambda: reload_and_generate("/tmp/no-task", "/tmp/no-cache",
                    prompt=prompt, input_text=text, max_new_tokens=count))

    def test_valid_generation_bounds(self):
        validate_generation(" x ", "", 1)
        validate_generation("x", "context", 256)

    def test_invalid_artifact_prevents_cache_and_gpu_access(self):
        failure = TrainingError(TrainingFailure(code="INVALID_ARTIFACT", stage="reloading", message="controlled"))
        with patch("trainer.reload.verify_training_artifacts", side_effect=failure), \
                patch("trainer.reload.verify_model_cache", side_effect=AssertionError("Unexpected cache access")):
            self.assert_code("INVALID_ARTIFACT", lambda: reload_and_generate("/tmp/task", "/tmp/cache", prompt="test"))

    def verified(self):
        return SimpleNamespace(manifest=SimpleNamespace(model_revision="a" * 40, chat_template_sha256="b" * 64))

    def test_cache_revision_comes_from_audited_manifest(self):
        verified = self.verified()
        cached = SimpleNamespace(manifest=SimpleNamespace(chat_template_sha256="b" * 64))
        with patch("trainer.reload.verify_training_artifacts", return_value=verified), \
                patch("trainer.reload.verify_model_cache", return_value=cached) as cache, \
                patch("trainer.reload._generate", return_value={"response": "controlled"}) as generate:
            self.assertEqual(reload_and_generate("/tmp/task", "/tmp/cache", prompt="test"), {"response": "controlled"})
            cache.assert_called_once_with("/tmp/cache", "a" * 40)
            self.assertIs(generate.call_args.args[0], verified)

    def test_template_mismatch_prevents_gpu(self):
        with patch("trainer.reload.verify_training_artifacts", return_value=self.verified()), \
                patch("trainer.reload.verify_model_cache", return_value=SimpleNamespace(manifest=SimpleNamespace(chat_template_sha256="c" * 64))), \
                patch("trainer.reload._generate", side_effect=AssertionError("Unexpected GPU access")):
            self.assert_code("INVALID_ARTIFACT", lambda: reload_and_generate("/tmp/task", "/tmp/cache", prompt="test"))

    def test_missing_cache_failure_propagates(self):
        failure = TrainingError(TrainingFailure(code="MODEL_NOT_CACHED", stage="model_loading", message="controlled"))
        with patch("trainer.reload.verify_training_artifacts", return_value=self.verified()), \
                patch("trainer.reload.verify_model_cache", side_effect=failure):
            self.assert_code("MODEL_NOT_CACHED", lambda: reload_and_generate("/tmp/task", "/tmp/cache", prompt="test"))

    def test_cli_errors_are_nonzero_and_safe(self):
        spec = importlib.util.spec_from_file_location("reload_cli", ROOT / "scripts/reload_adapter.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        task = "992aa53a-a246-45de-a8f1-4d4164d9b42e"
        for code in ("CUDA_OUT_OF_MEMORY", "MODEL_LOAD_FAILED", "INVALID_ARTIFACT"):
            failure = TrainingError(TrainingFailure(code=code, stage="reloading", message="controlled failure"))
            with patch.object(sys, "argv", ["reload_adapter.py", "--task-id", task, "--prompt", "dev test"]), \
                    patch.object(module, "reload_and_generate", side_effect=failure), \
                    redirect_stderr(io.StringIO()) as err, redirect_stdout(io.StringIO()) as out:
                self.assertEqual(module.main(), 1)
            self.assertEqual(out.getvalue(), "")
            self.assertEqual(json.loads(err.getvalue())["code"], code)

    def test_cpu_import_boundary(self):
        code = '''
import importlib.abc,sys,runpy
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'torch','numpy','transformers','peft','datasets','accelerate','trl'}:
            raise AssertionError('Unexpected ML import')
sys.meta_path.insert(0,Block())
import trainer.reload
from backend.app.main import create_app
assert '/api/v1/datasets' in create_app().openapi()['paths']
'''
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
