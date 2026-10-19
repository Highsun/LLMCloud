"""Generate the offline M1 design contract and examples without mounting routes."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.dataset_contract import (  # noqa: E402
    DATASET_CONTRACT_VERSION, MAX_DATASET_BYTES, MAX_JSONL_LINE_BYTES,
    MAX_MULTIPART_BYTES, MAX_MULTIPART_FIELDS, MAX_MULTIPART_FILES,
    MAX_MULTIPART_TEXT_PART_BYTES, MAX_UPLOAD_NAME_BYTES,
)
from backend.app.models.dataset_schemas import (  # noqa: E402
    DatasetDetail, DatasetListQuery, DatasetPage, DatasetSummary, DatasetUploadMetadata,
)
from backend.app.models.error_schemas import ErrorResponse  # noqa: E402
from trainer.dataset_schema import InstructionRecord  # noqa: E402

REF_PREFIX = "#/components/schemas/"


def ref(name: str) -> dict:
    return {"$ref": REF_PREFIX + name}


def collect_schema(model, components: dict, *, mode: str = "serialization") -> dict:
    schema = model.model_json_schema(ref_template=REF_PREFIX + "{model}", mode=mode)
    for name, definition in schema.pop("$defs", {}).items():
        if name in components and components[name] != definition:
            raise ValueError(f"Conflicting schema: {name}")
        components[name] = definition
    name = model.__name__
    if name in components and components[name] != schema:
        raise ValueError(f"Conflicting schema: {name}")
    components[name] = schema
    return ref(name)


def build_examples() -> dict[str, dict]:
    source = PROJECT_ROOT / "docs/examples/train.jsonl"
    raw = source.read_bytes()
    records = [InstructionRecord.model_validate_json(line) for line in raw.decode("utf-8-sig").split("\n") if line.strip()]
    detail = DatasetDetail(
        id="03a853e2-1bf1-45da-92fb-5a1548499fc4",
        name="云计算课程样例", format="alpaca_jsonl",
        original_filename="train.jsonl", sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw), row_count=len(records), created_at="2026-10-19T08:00:00Z",
    ).model_dump(mode="json")
    summary = DatasetSummary.model_validate({key: detail[key] for key in DatasetSummary.model_fields}).model_dump(mode="json")
    page = DatasetPage(items=[summary], total=1, page=1, page_size=20, total_pages=1).model_dump(mode="json")
    empty = DatasetPage(items=[], total=0, page=1, page_size=20, total_pages=0).model_dump(mode="json")
    beyond = DatasetPage(items=[], total=1, page=2, page_size=20, total_pages=1).model_dump(mode="json")
    error = ErrorResponse.model_validate({
        "error": {
            "code": "INVALID_DATASET", "message": "数据集第 2 行缺少 output 字段。",
            "details": [{"loc": ["body", "file", "output"], "code": "missing", "message": "output 为必填字符串。", "line": 2, "column": None}],
            "details_truncated": False, "request_id": "f63b14e1-7748-4e24-9db8-6d24810dd6df",
        },
    }).model_dump(mode="json")
    return {
        "upload-response.json": detail, "list-response.json": page,
        "empty-page.json": empty, "beyond-last-page.json": beyond,
        "error-response.json": error,
    }


def build_contract(examples: dict[str, dict]) -> dict:
    components = {}
    for model in (DatasetSummary, DatasetDetail, DatasetPage, ErrorResponse):
        collect_schema(model, components)
    collect_schema(InstructionRecord, components, mode="validation")
    query = DatasetListQuery.model_json_schema()
    name_schema = DatasetUploadMetadata.model_json_schema()["properties"]["name"]
    name_schema = next(option for option in name_schema["anyOf"] if option.get("type") != "null")
    components["DatasetUpload"] = {
        "type": "object", "additionalProperties": False, "required": ["file"],
        "properties": {
            "file": {"type": "string", "format": "binary", "description": "UTF-8 instruction/input/output JSONL; .jsonl extension required", "x-max-bytes": MAX_DATASET_BYTES, "x-record-schema": ref("InstructionRecord")},
            "name": {**name_schema, "description": "Optional display name, trimmed; omission uses sanitized original filename", "x-max-bytes": MAX_UPLOAD_NAME_BYTES},
        },
        "x-max-body-bytes": MAX_MULTIPART_BYTES,
        "x-max-line-bytes": MAX_JSONL_LINE_BYTES,
        "x-parser-max-files": MAX_MULTIPART_FILES,
        "x-parser-max-fields": MAX_MULTIPART_FIELDS,
        "x-parser-max-text-part-bytes": MAX_MULTIPART_TEXT_PART_BYTES,
        "x-duplicate-parts": "rejected",
    }
    request_id_header = {"description": "Server-generated request UUID; matches error.request_id", "schema": {"type": "string", "format": "uuid"}}

    def response(schema: str, description: str, example: dict | None = None, *, location: bool = False) -> dict:
        media = {"schema": ref(schema)}
        if example is not None:
            media["example"] = example
        headers = {"X-Request-ID": request_id_header}
        if location:
            headers["Location"] = {"description": "/api/v1/datasets/{id}", "schema": {"type": "string"}}
        return {"description": description, "headers": headers, "content": {"application/json": media}}

    def errors(statuses: dict[int, str]) -> dict:
        return {str(status): response("ErrorResponse", description) for status, description in statuses.items()}

    common_errors = {500: "INTERNAL_ERROR", 503: "STORAGE_UNAVAILABLE or DATABASE_UNAVAILABLE"}
    return {
        "openapi": "3.1.0",
        "info": {"title": "LLMCloud M1 dataset API design", "version": DATASET_CONTRACT_VERSION,
                 "description": "PLANNED M1-01 contract; routes and global error handlers are not implemented yet. Generated from Pydantic schemas; see docs/api/datasets.md."},
        "servers": [{"url": "/api/v1"}],
        "x-implementation-status": "planned",
        "x-generated-by": "scripts/export_dataset_contract.py",
        "paths": {
            "/datasets": {
                "post": {
                    "operationId": "upload_dataset", "tags": ["datasets"],
                    "summary": "Upload and synchronously validate one immutable dataset",
                    "requestBody": {"required": True, "content": {"multipart/form-data": {"schema": ref("DatasetUpload")}}},
                    "responses": {
                        "201": response("DatasetDetail", "Dataset committed", examples["upload-response.json"], location=True),
                        **errors({400: "INVALID_MULTIPART", 413: "UPLOAD_TOO_LARGE", 415: "UNSUPPORTED_MEDIA_TYPE", 422: "VALIDATION_ERROR or INVALID_DATASET", **common_errors}),
                    },
                },
                "get": {
                    "operationId": "list_datasets", "tags": ["datasets"],
                    "summary": "List datasets ordered by created_at DESC, id DESC",
                    "description": "Reject unknown/duplicate query parameters. Empty or beyond-last pages return 200. Offset pagination does not guarantee snapshots across requests.",
                    "parameters": [{"name": name, "in": "query", "required": False, "schema": schema} for name, schema in query["properties"].items()],
                    "responses": {"200": response("DatasetPage", "Dataset page", examples["list-response.json"]), **errors({422: "VALIDATION_ERROR", **common_errors})},
                },
            },
            "/datasets/{dataset_id}": {
                "get": {
                    "operationId": "get_dataset", "tags": ["datasets"],
                    "summary": "Get dataset metadata without reading the raw training file",
                    "parameters": [{"name": "dataset_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}}],
                    "responses": {"200": response("DatasetDetail", "Dataset metadata", examples["upload-response.json"]), **errors({404: "DATASET_NOT_FOUND", 422: "VALIDATION_ERROR", **common_errors})},
                },
            },
        },
        "components": {"schemas": components},
    }


def generate_outputs() -> dict[Path, str]:
    examples = build_examples()
    values = {PROJECT_ROOT / "docs/api/datasets.openapi.json": build_contract(examples)}
    values.update({PROJECT_ROOT / "docs/examples/datasets" / name: data for name, data in examples.items()})
    return {path: json.dumps(value, ensure_ascii=False, indent=2) + "\n" for path, value in values.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail when generated files differ; never rewrite")
    args = parser.parse_args()
    stale = []
    for path, content in generate_outputs().items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(str(path.relative_to(PROJECT_ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    if stale:
        print("Stale contract files: " + ", ".join(stale), file=sys.stderr)
        return 1
    print("PASS: generated dataset contract is current" if args.check else "Generated dataset OpenAPI design and five response examples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
