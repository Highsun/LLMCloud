"""Small synthetic Hub/cache fixtures; these never stand in for real GPU evidence."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from trainer.contracts import TrainingError
from trainer.model_cache import (
    MODEL_ID, REPO_FOLDER, REQUIRED_FILES, prepare_model_cache, resolve_model_paths,
    verify_model_cache,
)

ROOT = Path(__file__).resolve().parents[1]
REVISION = "a" * 40


class ModelCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache = self.root / "hub"
        self.snapshot = self.cache / REPO_FOLDER / "snapshots" / REVISION
        self.metadata = self.cache / ".llmcloud" / REPO_FOLDER / f"{REVISION}.json"
        self.contents = {name: b"synthetic fixture" for name in REQUIRED_FILES}
        self.contents["config.json"] = b'{"model_type":"qwen2"}'
        self.contents["tokenizer_config.json"] = b'{"chat_template":"synthetic template"}'
        self.siblings = [SimpleNamespace(
            rfilename=name, size=len(content),
            blob_id=hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest(),
            lfs=SimpleNamespace(sha256=hashlib.sha256(content).hexdigest()) if name == "model.safetensors" else None,
        ) for name, content in self.contents.items()]
        self.api = SimpleNamespace(model_info=Mock(return_value=SimpleNamespace(sha=REVISION, siblings=self.siblings)))
        self.download = Mock(side_effect=self.write_snapshot)

    def write_snapshot(self, *args, **kwargs):
        self.snapshot.mkdir(parents=True, exist_ok=True)
        blobs = self.cache / REPO_FOLDER / "blobs"
        blobs.mkdir(exist_ok=True)
        for sibling in self.siblings:
            blob = blobs / (sibling.lfs.sha256 if sibling.lfs else sibling.blob_id)
            blob.write_bytes(self.contents[sibling.rfilename])
            link = self.snapshot / sibling.rfilename
            if not link.exists():
                link.symlink_to(Path("../../blobs") / blob.name)
        return str(self.snapshot)

    def prepare(self, revision="main"):
        with patch("trainer.model_cache._hub", return_value=(self.api, self.download)):
            return prepare_model_cache(self.cache, revision)

    def assert_code(self, code, call):
        with self.assertRaises(TrainingError) as context:
            call()
        self.assertEqual(context.exception.failure.code, code)

    def test_paths_precedence_and_cwd_independence(self):
        project = self.root / "project"
        project.mkdir()
        (project / ".env").write_text('DATA_DIR=local-data\nHF_HOME=local-hf\n')
        paths = resolve_model_paths(project_root=project, environ={})
        self.assertEqual(paths.data_dir, project / "local-data")
        self.assertEqual(paths.cache_dir, project / "local-hf/hub")
        paths = resolve_model_paths(project_root=project, environ={"HF_HOME": "env-hf", "HF_HUB_CACHE": "env-hub"})
        self.assertEqual(paths.hf_home, project / "env-hf")
        self.assertEqual(paths.cache_dir, project / "env-hub")
        paths = resolve_model_paths(project_root=project, environ={"DATA_DIR": "env-data"},
                                    hf_home="cli-hf", cache_dir="cli-hub")
        self.assertEqual(paths.cache_dir, project / "cli-hub")
        self.assertEqual(paths.data_dir, project / "env-data")
        paths = resolve_model_paths(project_root=self.root, environ={"DATA_DIR": "alternate"})
        self.assertEqual(paths.cache_dir, self.root / "alternate/models/huggingface/hub")
        with self.assertRaises(ValueError):
            resolve_model_paths(project_root=project, env_file="missing.env", environ={})

    def test_prepare_resolves_once_and_downloads_only_pinned_required_files(self):
        cached = self.prepare()
        self.api.model_info.assert_called_once_with(MODEL_ID, revision="main", files_metadata=True, timeout=20)
        arguments = self.download.call_args.kwargs
        self.assertEqual(arguments["revision"], REVISION)
        self.assertEqual(set(arguments["allow_patterns"]), set(REQUIRED_FILES))
        self.assertIs(arguments["token"], False)
        self.assertEqual(cached.manifest.tokenizer_revision, REVISION)
        self.assertEqual(cached.summary()["status"], "cache_verified")
        self.assertTrue(self.metadata.is_file())
        self.assertNotIn(str(self.root), self.metadata.read_text())

    def test_offline_verification_uses_no_hub_and_writes_nothing(self):
        cached = self.prepare()
        before = {str(path.relative_to(self.cache)): path.read_bytes()
                  for path in self.cache.rglob("*") if path.is_file()}
        with patch("trainer.model_cache._hub", side_effect=AssertionError("Network adapter used")):
            result = verify_model_cache(self.cache, REVISION)
        self.assertEqual(result.manifest, cached.manifest)
        after = {str(path.relative_to(self.cache)): path.read_bytes()
                 for path in self.cache.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_missing_cache_check_does_not_create_directories(self):
        self.assert_code("MODEL_NOT_CACHED", lambda: verify_model_cache(self.cache, REVISION))
        self.assertFalse(self.cache.exists())

    def test_invalid_prepare_paths_fail_before_hub_access(self):
        with patch("trainer.model_cache._hub", side_effect=AssertionError("Unexpected Hub access")):
            self.assert_code("INVALID_REQUEST", lambda: prepare_model_cache(Path("relative")))

    def test_relative_cache_and_cyclic_links_are_controlled_errors(self):
        self.assert_code("INVALID_REQUEST", lambda: verify_model_cache(Path("relative"), REVISION))
        self.cache.mkdir()
        (self.cache / REPO_FOLDER).symlink_to(REPO_FOLDER)
        self.assert_code("INVALID_REQUEST", lambda: verify_model_cache(self.cache, REVISION))

    def test_snapshot_directory_alone_is_not_completion(self):
        self.write_snapshot()
        self.assert_code("MODEL_NOT_CACHED", lambda: verify_model_cache(self.cache, REVISION))

    def test_missing_file_wrong_size_and_same_size_corruption_fail(self):
        self.prepare()
        file = self.snapshot / "model.safetensors"
        blob = file.resolve()
        for content in (b"short", b"x" * len(self.contents["model.safetensors"])):
            blob.write_bytes(content)
            self.assert_code("MODEL_NOT_CACHED", lambda: verify_model_cache(self.cache, REVISION))
        blob.unlink()
        self.assert_code("MODEL_NOT_CACHED", lambda: verify_model_cache(self.cache, REVISION))

    def test_offline_check_requires_full_matching_revision(self):
        self.prepare()
        for revision in ("main", "short", "../bad"):
            self.assert_code("INVALID_REQUEST", lambda: verify_model_cache(self.cache, revision))
        self.assert_code("MODEL_NOT_CACHED", lambda: verify_model_cache(self.cache, "b" * 40))
        invalid = json.loads(self.metadata.read_text())
        invalid["model_revision"] = invalid["tokenizer_revision"] = "b" * 40
        self.metadata.write_text(json.dumps(invalid))
        self.assert_code("MODEL_NOT_CACHED", lambda: verify_model_cache(self.cache, REVISION))

    def test_escaped_snapshot_links_are_rejected(self):
        self.prepare()
        outside = self.root / "outside"
        outside.write_bytes(self.contents["config.json"])
        (self.snapshot / "config.json").unlink()
        (self.snapshot / "config.json").symlink_to(outside)
        self.assert_code("INVALID_REQUEST", lambda: verify_model_cache(self.cache, REVISION))

    def test_escaped_metadata_links_are_rejected_before_writing(self):
        self.cache.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        (self.cache / ".llmcloud").symlink_to(outside, target_is_directory=True)
        self.assert_code("INVALID_REQUEST", self.prepare)
        self.download.assert_not_called()
        self.assertEqual(list(outside.iterdir()), [])

    def test_bad_metadata_template_and_inventory_fail_closed(self):
        self.prepare()
        original = self.metadata.read_text()
        for replacement in ("not-json", "x" * (128 * 1024 + 1)):
            self.metadata.write_text(replacement)
            self.assert_code("MODEL_NOT_CACHED", lambda: verify_model_cache(self.cache, REVISION))
        for change in (lambda value: value.update(chat_template_sha256="0" * 64),
                       lambda value: value["files"].__setitem__(0, value["files"][1])):
            value = json.loads(original)
            change(value)
            self.metadata.write_text(json.dumps(value))
            self.assert_code("MODEL_NOT_CACHED", lambda: verify_model_cache(self.cache, REVISION))

    def test_network_failure_cannot_commit_completion_manifest(self):
        self.download.side_effect = TimeoutError("private URL must not be shown")
        with self.assertRaises(TrainingError) as context:
            self.prepare()
        self.assertEqual(context.exception.failure.code, "MODEL_LOAD_FAILED")
        self.assertNotIn("private URL", str(context.exception))
        self.assertFalse(self.metadata.exists())

    def test_source_digest_mismatch_cannot_commit_completion(self):
        self.siblings[0].blob_id = "0" * 40
        self.assert_code("MODEL_NOT_CACHED", self.prepare)
        self.assertFalse(self.metadata.exists())

    def test_remote_revision_and_missing_file_errors(self):
        self.api.model_info.return_value.sha = "b" * 40
        self.assert_code("MODEL_LOAD_FAILED", lambda: self.prepare(REVISION))
        self.download.assert_not_called()
        self.api.model_info.return_value.sha = REVISION
        self.api.model_info.return_value.siblings = self.siblings[:-1]
        self.assert_code("MODEL_LOAD_FAILED", self.prepare)
        self.download.assert_not_called()

    def test_manifest_write_failure_keeps_primary_error_and_no_success_marker(self):
        with patch.object(Path, "replace", side_effect=OSError("write failed")):
            self.assert_code("ARTIFACT_WRITE_FAILED", self.prepare)
        self.assertFalse(self.metadata.exists())
        self.assertEqual(list(self.metadata.parent.glob("*.tmp")), [])

    def test_cpu_cli_check_does_not_import_gpu_or_hub_dependencies(self):
        self.prepare()
        code = '''
import importlib.abc
import runpy
import sys
class BlockDependencies(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch', 'transformers', 'huggingface_hub', 'peft', 'trl', 'accelerate'}:
            raise AssertionError('Unexpected dependency: ' + fullname)
sys.meta_path.insert(0, BlockDependencies())
sys.argv = ['prepare_model.py', 'check', '--revision', sys.argv[1], '--cache-dir', sys.argv[2]]
runpy.run_path('scripts/prepare_model.py', run_name='__main__')
'''
        result = subprocess.run([sys.executable, "-c", code, REVISION, str(self.cache)],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "cache_verified")


if __name__ == "__main__":
    unittest.main()
