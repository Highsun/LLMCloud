"""Image source integrity, honest dirty state and checkout/Git failure isolation."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from trainer.code_provenance import code_identity, export_provenance, source_files


class CodeProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.temp)
        for name in ("backend", "trainer", "worker", "scripts"):
            (self.root / name).mkdir()
            (self.root / name / "entry.py").write_text("# original\n")
        for name in ("pyproject.toml", "uv.lock", "README.md"):
            (self.root / name).write_text(name)
        self.path = self.root / "build-provenance.json"

    def write(self, **changes):
        with patch("trainer.code_provenance.git_identity", return_value=("a" * 40, True)):
            value = export_provenance(self.root)
        value.update(changes)
        self.path.write_text(json.dumps(value))

    def test_valid_image_records_real_commit_and_preserves_dirty(self):
        self.write()
        self.assertEqual(code_identity(self.root), ("a" * 40, True))

    def test_modified_missing_or_added_source_is_rejected(self):
        self.write()
        file = self.root / "trainer" / "entry.py"
        file.write_text("# modified")
        with self.assertRaises(ValueError): code_identity(self.root)
        file.unlink()
        with self.assertRaises(ValueError): code_identity(self.root)
        file.write_text("# original\n")
        (self.root / "worker" / "extra.py").write_text("# new")
        with self.assertRaises(ValueError): code_identity(self.root)

    def test_bad_identity_types_or_missing_manifest_are_rejected(self):
        with self.assertRaises(ValueError): code_identity(self.root)
        for changes in ({"code_commit": "main"}, {"working_tree_dirty": "false"}, {"version": True}, {"files": {}}):
            self.write(**changes)
            with self.assertRaises(ValueError): code_identity(self.root)

    def test_manifest_source_symlink_is_rejected(self):
        self.write()
        file = self.root / "backend" / "entry.py"
        file.unlink()
        try: file.symlink_to(self.root / "README.md")
        except OSError: self.skipTest("Symlinks unavailable on this test platform")
        with self.assertRaises(ValueError): code_identity(self.root)

    def test_git_checkout_never_hides_a_git_failure_with_image_fallback(self):
        self.write()
        (self.root / ".git").mkdir()
        with patch("trainer.code_provenance.git_identity", side_effect=OSError("Git unavailable")):
            with self.assertRaises(OSError): code_identity(self.root)


if __name__ == "__main__":
    unittest.main()
