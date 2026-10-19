"""Contract checks only; HTTP, storage and migration tests follow in M1-02/M1-03."""

import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import unittest

from pydantic import ValidationError

from backend.app.core.dataset_contract import MAX_DATASET_BYTES, MAX_MULTIPART_BYTES
from backend.app.models.dataset_schemas import (
    DatasetDetail, DatasetListQuery, DatasetPage, DatasetUploadMetadata,
)
from backend.app.models.error_schemas import ErrorResponse
from scripts.export_dataset_contract import generate_outputs
from trainer.dataset_schema import InstructionRecord

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "docs/examples/datasets"


class DatasetContractTests(unittest.TestCase):
    def load_example(self, name):
        return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))

    def test_upload_metadata_defaults_normalization_and_rejections(self):
        self.assertIsNone(DatasetUploadMetadata().name)
        self.assertEqual(DatasetUploadMetadata(name="  课程数据  ").name, "课程数据")
        for value in ("", "   ", "x" * 256, "a\nb", "a\x7fb", 123):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                DatasetUploadMetadata(name=value)
        with self.assertRaises(ValidationError):
            DatasetUploadMetadata(storage_path="/tmp/untrusted")

    def test_query_defaults_boundaries_and_unknown_keys(self):
        self.assertEqual(DatasetListQuery().model_dump(), {"page": 1, "page_size": 20})
        self.assertEqual(DatasetListQuery(page="2", page_size="100").page_size, 100)
        for invalid in ({"page": 0}, {"page_size": 101}, {"page_size": 0}, {"page": "1.5"}, {"sort": "name"}):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                DatasetListQuery(**invalid)

    def test_instruction_record_strictness_and_text_preservation(self):
        record = InstructionRecord(instruction="  解释云计算  ", output="答案\n")
        self.assertEqual(record.input, "")
        self.assertEqual(record.instruction, "  解释云计算  ")
        self.assertEqual(record.output, "答案\n")
        for invalid in (
            {"instruction": "x"}, {"instruction": " ", "output": "x"},
            {"instruction": 1, "output": "x"}, {"instruction": "x", "output": "x", "input": None},
            {"instruction": "x", "output": "x", "messages": []},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                InstructionRecord(**invalid)

    def test_jsonl_fixtures_are_intentionally_valid_or_invalid(self):
        valid = (EXAMPLES / "valid-minimal.jsonl").read_text()
        self.assertEqual(InstructionRecord.model_validate_json(valid).input, "")
        for name in ("invalid-missing-output.jsonl", "invalid-input-null.jsonl", "invalid-extra-field.jsonl"):
            lines = (EXAMPLES / name).read_text().splitlines()
            with self.subTest(name=name), self.assertRaises(ValidationError):
                InstructionRecord.model_validate_json(lines[-1])
        error = self.load_example("error-response.json")
        lines = (EXAMPLES / "invalid-missing-output.jsonl").read_text().splitlines()
        self.assertNotIn("output", json.loads(lines[error["error"]["details"][0]["line"] - 1]))

    def test_detail_matches_source_file_and_hides_storage_fields(self):
        detail = DatasetDetail.model_validate(self.load_example("upload-response.json"))
        raw = (ROOT / "docs/examples/train.jsonl").read_bytes()
        self.assertEqual(detail.sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(detail.size_bytes, len(raw))
        self.assertEqual(detail.row_count, 3)
        self.assertNotIn("storage_path", detail.model_dump())
        self.assertNotIn("user_id", detail.model_dump())
        invalid = detail.model_dump()
        invalid["sha256"] = "not-a-hash"
        with self.assertRaises(ValidationError):
            DatasetDetail.model_validate(invalid)

    def test_timestamp_serialization_and_sqlite_utc_mapping(self):
        data = self.load_example("upload-response.json")
        data["created_at"] = "2026-10-19T16:00:00+08:00"
        self.assertEqual(DatasetDetail.model_validate(data).model_dump(mode="json")["created_at"], "2026-10-19T08:00:00Z")
        data["created_at"] = datetime(2026, 10, 19, 8)
        self.assertEqual(DatasetDetail.model_validate(data).model_dump(mode="json")["created_at"], "2026-10-19T08:00:00Z")
        data["created_at"] = "2026-10-19T08:00:00"
        with self.assertRaises(ValidationError):
            DatasetDetail.model_validate(data)

    def test_pagination_examples_and_consistency(self):
        for name in ("list-response.json", "empty-page.json", "beyond-last-page.json"):
            DatasetPage.model_validate(self.load_example(name))
        data = self.load_example("list-response.json")
        for updates in ({"total_pages": 2}, {"page": 2}, {"total": 0, "total_pages": 0}):
            with self.subTest(updates=updates), self.assertRaises(ValidationError):
                DatasetPage.model_validate({**data, **updates})

    def test_error_shape_does_not_allow_raw_input_or_unbounded_details(self):
        data = self.load_example("error-response.json")
        ErrorResponse.model_validate(data)
        too_many = copy.deepcopy(data)
        too_many["error"]["details"] *= 11
        with self.assertRaises(ValidationError):
            ErrorResponse.model_validate(too_many)
        leaked = copy.deepcopy(data)
        leaked["error"]["details"][0]["input"] = "raw training content"
        with self.assertRaises(ValidationError):
            ErrorResponse.model_validate(leaked)
        missing_structure = copy.deepcopy(data)
        del missing_structure["error"]["details"][0]["column"]
        with self.assertRaises(ValidationError):
            ErrorResponse.model_validate(missing_structure)

    def test_generated_files_and_openapi_references(self):
        for path, expected in generate_outputs().items():
            self.assertEqual(path.read_text(encoding="utf-8"), expected, str(path))
        contract = json.loads((ROOT / "docs/api/datasets.openapi.json").read_text())
        self.assertEqual(contract["x-implementation-status"], "planned")
        self.assertEqual(set(contract["paths"]), {"/datasets", "/datasets/{dataset_id}"})
        def walk(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    target = contract
                    for part in value["$ref"].removeprefix("#/").split("/"):
                        target = target[part]
                for item in value.values():
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
        walk(contract)
        self.assertEqual(MAX_DATASET_BYTES, 52_428_800)
        self.assertEqual(MAX_MULTIPART_BYTES, 52_494_336)


if __name__ == "__main__":
    unittest.main()
