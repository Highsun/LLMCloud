"""Behavior checks for reproducibility, held-out leakage, and private bundle output."""

import copy
from contextlib import redirect_stderr
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.prepare_dataset import (
    PROTOCOL, PreparationError, load_protocol, plan_dataset, write_bundle,
)
from trainer.dataset import DatasetValidationError, iter_records, scan_dataset


class DatasetPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "curated.jsonl"
        self.curation = self.root / "curation.json"
        self.records = [{"instruction": f"独立问题 {i} 的变体 {j}？", "input": "", "output": f" 保留答案空白 {i}-{j} \n"}
                        for i in range(10) for j in range(2)]
        self.metadata = {"version": "1.0.0", "rows": [
            {"row": i + 1, "record_id": f"r-{i}", "group_id": f"family-{i // 2}",
             "source_ids": ["nist-cloud"], "reviewed": True}
            for i in range(len(self.records))
        ]}
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        self.source.write_bytes(b"\xef\xbb\xbf\n" + b"\n".join(json.dumps(record, ensure_ascii=False).encode() for record in self.records))
        self.curation.write_text(json.dumps(self.metadata), encoding="utf-8")

    def test_reproducible_grouped_splits_preserve_text_hashes_and_provenance(self):
        source_before = self.source.read_bytes()
        first, manifest = plan_dataset(self.source, self.curation)
        self.assertEqual((first, manifest), plan_dataset(self.source, self.curation))
        self.assertEqual(manifest["source_sha256"], hashlib.sha256(source_before).hexdigest())
        self.assertEqual(manifest["review_status"], "reviewed")
        groups = [set(split["group_ids"]) for split in manifest["splits"].values()]
        self.assertTrue(all(groups[i].isdisjoint(groups[j]) for i in range(3) for j in range(i + 1, 3)))
        self.assertEqual([manifest["splits"][name]["row_count"] for name in ("train", "validation", "test")], [16, 2, 2])
        output = self.root / "output"
        write_bundle(output, first)
        reconstructed = []
        for name in ("train", "validation", "test"):
            path = output / f"{name}.jsonl"
            stats = scan_dataset(path)
            self.assertEqual(stats.sha256, manifest["splits"][name]["sha256"])
            reconstructed.extend(iter_records(path))
        self.assertEqual(sorted(record["output"] for record in reconstructed), sorted(record["output"] for record in self.records))
        provenance = json.loads(first["provenance.json"])
        self.assertEqual(sum(map(len, provenance.values())), len(self.records))
        self.assertEqual(self.source.read_bytes(), source_before)
        self.assertNotIn(str(self.root), first["manifest.json"].decode())

    def test_changed_seed_changes_assignment_but_not_records(self):
        first, _ = plan_dataset(self.source, self.curation, seed=42)
        second, _ = plan_dataset(self.source, self.curation, seed=17)
        self.assertNotEqual(first["provenance.json"], second["provenance.json"])

    def test_unreviewed_is_rejected_unless_explicitly_draft(self):
        self.metadata["rows"][0]["reviewed"] = False
        self.save()
        with self.assertRaisesRegex(PreparationError, "Unreviewed"):
            plan_dataset(self.source, self.curation)
        _, manifest = plan_dataset(self.source, self.curation, allow_unreviewed=True)
        self.assertEqual(manifest["review_status"], "draft_unreviewed")

    def test_unknown_sources_duplicate_ids_and_incomplete_row_mapping(self):
        original = copy.deepcopy(self.metadata)
        for mutate in (
            lambda rows: rows.pop(),
            lambda rows: rows[1].update(row=1),
            lambda rows: rows[1].update(record_id=rows[0]["record_id"]),
            lambda rows: rows[0].update(source_ids=["unknown"]),
            lambda rows: rows[0].update(reviewed="true"),
        ):
            with self.subTest(mutate=mutate):
                self.metadata = copy.deepcopy(original)
                mutate(self.metadata["rows"])
                self.save()
                with self.assertRaises(PreparationError):
                    plan_dataset(self.source, self.curation)

    def test_duplicate_normalized_questions_and_frozen_case_families_rejected(self):
        self.records[1]["instruction"] = self.records[0]["instruction"].replace(" ", "").replace("？", "!")
        self.save()
        with self.assertRaisesRegex(PreparationError, "Duplicate normalized"):
            plan_dataset(self.source, self.curation)
        self.records[1]["instruction"] = "一个不同的问题"
        case = json.loads(PROTOCOL.read_text())["cases"][0]
        self.records[0]["instruction"] = case["prompt"]
        self.save()
        with self.assertRaisesRegex(PreparationError, "Frozen evaluation"):
            plan_dataset(self.source, self.curation)
        self.records[0]["instruction"] = "一个没有重复的新问题"
        self.metadata["rows"][0]["group_id"] = case["group_id"]
        self.save()
        with self.assertRaisesRegex(PreparationError, "Frozen evaluation"):
            plan_dataset(self.source, self.curation)

    def test_shared_scanner_and_minimum_family_checks(self):
        self.source.write_bytes(b'{"instruction":"x","output":"y","output":"z"}')
        with self.assertRaises(DatasetValidationError) as failure:
            plan_dataset(self.source, self.curation)
        self.assertEqual(failure.exception.code, "duplicate_key")
        for item in self.metadata["rows"]:
            item["group_id"] = "only-one-family"
        self.save()
        with self.assertRaisesRegex(PreparationError, "three independent"):
            plan_dataset(self.source, self.curation)

    def test_bundle_never_overwrites_existing_directory(self):
        files, _ = plan_dataset(self.source, self.curation)
        output = self.root / "owned-by-someone-else"
        output.mkdir()
        marker = output / "keep.txt"
        marker.write_text("keep")
        with self.assertRaises(FileExistsError):
            write_bundle(output, files)
        self.assertEqual(marker.read_text(), "keep")
        self.assertEqual(list(output.iterdir()), [marker])

    def test_write_failure_cleans_only_this_bundle(self):
        files, _ = plan_dataset(self.source, self.curation)
        output = self.root / "new-bundle"
        original = Path.open

        def failing_open(path, *args, **kwargs):
            if path == output / "validation.jsonl":
                raise OSError("injected disk error")
            return original(path, *args, **kwargs)

        with patch.object(Path, "open", failing_open), self.assertRaises(OSError):
            write_bundle(output, files)
        self.assertFalse(output.exists())
        self.assertTrue(self.source.exists())

    def test_frozen_evaluation_protocol_has_valid_references_and_unique_questions(self):
        _, _, _, protocol = load_protocol()
        self.assertEqual(len(protocol["cases"]), 12)
        self.assertEqual(len({case["prompt"] for case in protocol["cases"]}), 12)
        self.assertFalse(protocol["generation"]["do_sample"])
        self.assertEqual(protocol["version"], "1.0.0")

    def test_cleanup_failure_preserves_the_primary_write_error(self):
        files, _ = plan_dataset(self.source, self.curation)
        output = self.root / "cleanup-failure"
        original = Path.open

        def fail_write(path, *args, **kwargs):
            if path == output / "validation.jsonl":
                raise OSError("primary write failure")
            return original(path, *args, **kwargs)

        warning = io.StringIO()
        with patch.object(Path, "open", fail_write), patch.object(Path, "unlink", side_effect=PermissionError("cleanup")), redirect_stderr(warning):
            with self.assertRaisesRegex(OSError, "primary write failure"):
                write_bundle(output, files)
        self.assertIn("cleanup incomplete", warning.getvalue())
        self.assertFalse((output / "manifest.json").exists())
        self.assertTrue(self.source.exists())


if __name__ == "__main__":
    unittest.main()
