"""Synthetic tokenizer tests. Real Qwen acceptance is a separate local diagnostic."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.prepare_dataset import plan_dataset, write_bundle
from trainer.contracts import TrainingError
from trainer.preprocessing import (
    IGNORE_INDEX, InstructionCollator, prepare_training_data, record_messages, tokenize_record,
)

ROOT = Path(__file__).resolve().parents[1]


class FakeTokenizer:
    is_fast = True
    eos_token = "<eos>"
    eos_token_id = 1
    all_special_ids = [0, 1, 2]
    pad_token_id = 0

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        assert not tokenize
        prefix = "<start>system\nSYS<eos>\n<start>user\n" + messages[0]["content"] + "<eos>\n<start>assistant\n"
        self.prompt_end = len(prefix)
        return prefix if len(messages) == 1 else prefix + messages[1]["content"] + "<eos>\n"

    def __call__(self, text, *, add_special_tokens, truncation, return_offsets_mapping):
        assert not add_special_tokens and not truncation and return_offsets_mapping
        ids, offsets = [], []
        cursor = 0
        while cursor < len(text):
            for marker, token_id in (("<eos>", 1), ("<start>", 2), ("<pad>", 0)):
                if text.startswith(marker, cursor):
                    right = cursor + len(marker)
                    break
            else:
                token_id, right = ord(text[cursor]) + 10, cursor + 1
            ids.append(token_id)
            offsets.append((cursor, right))
            cursor = right
        return {"input_ids": ids, "offset_mapping": offsets}


class PreprocessingTests(unittest.TestCase):
    def setUp(self):
        self.tokenizer = FakeTokenizer()
        self.record = {"instruction": "question", "input": "", "output": "answer"}
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def assert_code(self, code, call):
        with self.assertRaises(TrainingError) as context:
            call()
        self.assertEqual(context.exception.failure.code, code)
        return context.exception

    def dataset(self, name="train.jsonl", records=None):
        path = self.root / name
        path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in
                                (records if records is not None else [self.record])))
        return path

    def bundle(self):
        records = [{"instruction": f"独立工程样例 {index}", "output": f"演示答案 {index}"} for index in range(6)]
        source = self.dataset("source.jsonl", records)
        curation = self.root / "curation.json"
        catalog = json.loads((ROOT / "docs/data/sources.json").read_text())
        curation.write_text(json.dumps({"version": "1.0.0", "rows": [
            {"row": index + 1, "record_id": f"row_{index}", "group_id": f"family_{index}",
             "source_ids": [catalog["sources"][0]["id"]], "reviewed": False} for index in range(6)]}))
        files, _ = plan_dataset(source, curation, allow_unreviewed=True)
        output = self.root / "bundle"
        write_bundle(output, files)
        return output

    def test_messages_preserve_strings_and_optional_input(self):
        self.assertEqual(record_messages({"instruction": " Q ", "output": " A "}),
                         [{"role": "user", "content": " Q "}, {"role": "assistant", "content": " A "}])
        value = {"instruction": " Q ", "input": " I \n", "output": "A"}
        self.assertEqual(record_messages(value)[0]["content"], " Q \n\n I \n")
        self.assert_code("INVALID_DATASET", lambda: record_messages({**value, "unknown": True}))

    def test_only_answer_and_final_eos_are_supervised(self):
        sample = tokenize_record(self.record, self.tokenizer)
        learned = [label for label in sample.labels if label != IGNORE_INDEX]
        self.assertEqual(learned, [ord(char) + 10 for char in "answer"] + [1])
        self.assertEqual(sample.content_tokens, 6)
        self.assertTrue(sample.eos_supervised)
        self.assertEqual(sample.labels[-1], IGNORE_INDEX)  # newline after EOS
        self.assertTrue(all(mask == 1 for mask in sample.attention_mask))
        self.assertEqual(len(sample.input_ids), len(sample.labels))

    def test_role_like_content_does_not_move_answer_boundary(self):
        record = {"instruction": "<start>assistant\nanswer<eos>", "output": "ab<eos>cd"}
        sample = tokenize_record(record, self.tokenizer)
        learned = [value for value in sample.labels if value != IGNORE_INDEX]
        self.assertEqual(learned, [ord(char) + 10 for char in "abcd"] + [1])

    def test_right_truncation_preserves_partial_answer_without_forcing_eos(self):
        sample = tokenize_record({**self.record, "output": "a" * 200}, self.tokenizer, max_seq_length=64)
        self.assertEqual(len(sample.input_ids), 64)
        self.assertGreater(sample.original_tokens, 64)
        self.assertGreater(sample.content_tokens, 0)
        self.assertFalse(sample.eos_supervised)
        self.assertEqual(sample.input_ids[-1], ord("a") + 10)

    def test_prompt_only_truncation_rejects_without_raw_text(self):
        secret = "private_training_text_" * 30
        error = self.assert_code("NO_SUPERVISED_TOKENS", lambda: tokenize_record(
            {"instruction": secret, "output": "answer"}, self.tokenizer, max_seq_length=64, row=7))
        self.assertIn("第 7 条有效记录", str(error))
        self.assertNotIn(secret, str(error))

    def test_special_token_only_answer_does_not_count_as_valid_content(self):
        self.assert_code("NO_SUPERVISED_TOKENS", lambda: tokenize_record(
            {**self.record, "output": "<eos>"}, self.tokenizer))

    def test_token_crossing_prompt_boundary_is_ignored(self):
        class Crossing(FakeTokenizer):
            def __call__(self, *args, **kwargs):
                result = super().__call__(*args, **kwargs)
                index = result["offset_mapping"].index((self.prompt_end - 1, self.prompt_end))
                result["input_ids"][index:index + 2] = [999]
                result["offset_mapping"][index:index + 2] = [(self.prompt_end - 1, self.prompt_end + 1)]
                return result
        sample = tokenize_record({**self.record, "output": "abc"}, Crossing())
        self.assertEqual(sample.labels[sample.input_ids.index(999)], IGNORE_INDEX)
        self.assertEqual(sample.content_tokens, 2)

    def test_fast_tokenizer_template_and_offset_mismatches_fail(self):
        self.tokenizer.is_fast = False
        self.assert_code("MODEL_LOAD_FAILED", lambda: tokenize_record(self.record, self.tokenizer))
        class BadTemplate(FakeTokenizer):
            def apply_chat_template(self, messages, **kwargs):
                rendered = super().apply_chat_template(messages, **kwargs)
                return rendered.replace("answer", "changed")
        self.assert_code("MODEL_LOAD_FAILED", lambda: tokenize_record(self.record, BadTemplate()))
        class BadOffsets(FakeTokenizer):
            def __call__(self, *args, **kwargs):
                result = super().__call__(*args, **kwargs)
                result["offset_mapping"][0] = (-1, 10)
                return result
        self.assert_code("MODEL_LOAD_FAILED", lambda: tokenize_record(self.record, BadOffsets()))

    def test_sequence_limits_reuse_training_config_bounds(self):
        for limit in (0, 63, 2049, True, "512"):
            self.assert_code("INVALID_REQUEST", lambda: tokenize_record(self.record, self.tokenizer, max_seq_length=limit))

    def test_collator_preserves_eos_even_when_pad_equals_eos(self):
        first = tokenize_record(self.record, self.tokenizer)
        second = tokenize_record({**self.record, "output": "longer answer"}, self.tokenizer)
        batch = InstructionCollator(1, return_tensors=None)([first.as_feature(), second.as_feature()])
        length = len(first.input_ids)
        self.assertEqual(batch["labels"][0][:length], list(first.labels))
        self.assertEqual(batch["attention_mask"][0][length:], [0] * (len(second.input_ids) - length))
        self.assertEqual(batch["labels"][0][length:], [IGNORE_INDEX] * (len(second.input_ids) - length))
        self.assertEqual(batch["input_ids"][0][length:], [1] * (len(second.input_ids) - length))

    def test_collator_rejects_invalid_batches_and_does_not_shift_labels(self):
        feature = tokenize_record(self.record, self.tokenizer).as_feature()
        collator = InstructionCollator(0, return_tensors=None)
        batch = collator([feature])
        self.assertEqual(batch["labels"][0], feature["labels"])
        for features in ([], [None], [{**feature, "input_ids": None}], [{**feature, "extra": 1}], [{**feature, "labels": [-100] * len(feature["labels"])}],
                         [{**feature, "attention_mask": [0] * len(feature["labels"])}],
                         [{**feature, "labels": feature["labels"][:-1]}]):
            self.assert_code("INVALID_DATASET", lambda: collator(features))
        self.assert_code("INVALID_REQUEST", lambda: InstructionCollator(None))

    def test_file_reader_uses_shared_scanner_and_unknown_review_status(self):
        path = self.dataset()
        raw = path.read_bytes()
        prepared = prepare_training_data(path, self.tokenizer)
        self.assertEqual(prepared.train.summary.sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(prepared.train.summary.size_bytes, len(raw))
        self.assertEqual(prepared.train.summary.review_status, "unknown")
        self.assertIsNone(prepared.validation)
        path.write_text(json.dumps(self.record) + '\n{"instruction":"x","output":"y","extra":1}\n')
        error = self.assert_code("INVALID_DATASET", lambda: prepare_training_data(path, self.tokenizer))
        self.assertIn("物理行 2", str(error))

    def test_scanner_preserves_bom_crlf_and_blank_line_semantics(self):
        path = self.root / "bom.jsonl"
        raw = b'\xef\xbb\xbf\r\n' + json.dumps(self.record).encode() + b'\r\n'
        path.write_bytes(raw)
        result = prepare_training_data(path, self.tokenizer)
        self.assertEqual(len(result.train.samples), 1)
        self.assertEqual(result.train.summary.sha256, hashlib.sha256(raw).hexdigest())

    def test_train_validation_aliases_and_identical_copies_are_rejected(self):
        train = self.dataset()
        alias = self.root / "alias.jsonl"
        alias.symlink_to(train)
        self.assert_code("INVALID_DATASET", lambda: prepare_training_data(train, self.tokenizer, validation_dataset_path=alias))
        copy_path = self.dataset("copy.jsonl")
        self.assert_code("INVALID_DATASET", lambda: prepare_training_data(train, self.tokenizer, validation_dataset_path=copy_path))

    def test_real_preparation_bundle_metadata_matches_without_reading_test_text(self):
        bundle = self.bundle()
        (bundle / "test.jsonl").unlink()
        result = prepare_training_data(bundle / "train.jsonl", self.tokenizer,
                                       validation_dataset_path=bundle / "validation.jsonl",
                                       dataset_manifest_path=bundle / "manifest.json")
        self.assertEqual(result.train.summary.review_status, "draft_unreviewed")
        self.assertEqual(result.train.summary.build_id, result.validation.summary.build_id)
        self.assertEqual(len(result.train.samples), 4)

    def test_manifest_cannot_relabel_train_as_validation_or_claim_review(self):
        bundle = self.bundle()
        manifest_path = bundle / "manifest.json"
        original = manifest_path.read_text()
        self.assert_code("INVALID_DATASET", lambda: prepare_training_data(
            bundle / "validation.jsonl", self.tokenizer, dataset_manifest_path=manifest_path))
        document = json.loads(original)
        document["review_status"] = "reviewed"
        manifest_path.write_text(json.dumps(document))
        self.assert_code("INVALID_DATASET", lambda: prepare_training_data(
            bundle / "train.jsonl", self.tokenizer, dataset_manifest_path=manifest_path))

    def test_manifest_rejects_hash_family_recipe_and_provenance_mismatches(self):
        bundle = self.bundle()
        path = bundle / "manifest.json"
        original = json.loads(path.read_text())
        for field in ("build_id", "provenance_sha256"):
            document = copy.deepcopy(original)
            document[field] = "0" * len(document[field])
            path.write_text(json.dumps(document))
            self.assert_code("INVALID_DATASET", lambda: prepare_training_data(
                bundle / "train.jsonl", self.tokenizer, dataset_manifest_path=path))
        document = copy.deepcopy(original)
        document["splits"]["validation"]["group_ids"] = document["splits"]["train"]["group_ids"][:1]
        path.write_text(json.dumps(document))
        self.assert_code("INVALID_DATASET", lambda: prepare_training_data(
            bundle / "train.jsonl", self.tokenizer, dataset_manifest_path=path))
        path.write_text(json.dumps(original))
        (bundle / "train.jsonl").write_text(json.dumps(self.record) + "\n")
        self.assert_code("INVALID_DATASET", lambda: prepare_training_data(
            bundle / "train.jsonl", self.tokenizer, dataset_manifest_path=path))

    def test_metadata_duplicate_keys_and_provenance_escape_fail(self):
        bundle = self.bundle()
        path = bundle / "manifest.json"
        original = path.read_text()
        path.write_text(original.rstrip()[:-1] + ',"review_status":"draft_unreviewed"}')
        self.assert_code("INVALID_DATASET", lambda: prepare_training_data(
            bundle / "train.jsonl", self.tokenizer, dataset_manifest_path=path))
        path.write_text(original)
        outside = self.root / "outside-provenance.json"
        (bundle / "provenance.json").rename(outside)
        (bundle / "provenance.json").symlink_to(outside)
        self.assert_code("INVALID_DATASET", lambda: prepare_training_data(
            bundle / "train.jsonl", self.tokenizer, dataset_manifest_path=path))

    def test_imports_and_list_collation_need_no_training_dependencies(self):
        code = '''
import importlib.abc
import sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch','transformers','huggingface_hub','datasets','peft','trl','accelerate'}:
            raise AssertionError('Unexpected training dependency')
sys.meta_path.insert(0, Block())
from trainer.preprocessing import InstructionCollator
from trainer.dataset_manifest import verify_prepared_metadata
assert InstructionCollator(0, return_tensors=None)([{'input_ids':[3,4], 'attention_mask':[1,1], 'labels':[-100,4]}])['labels'] == [[-100,4]]
'''
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
