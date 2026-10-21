"""OpenAPI metadata for the custom multipart/query parsers, shared with export."""

from backend.app.core.dataset_contract import (
    DATASET_CONTRACT_VERSION, MAX_DATASET_BYTES, MAX_JSONL_LINE_BYTES,
    MAX_MULTIPART_BYTES, MAX_MULTIPART_FIELDS, MAX_MULTIPART_FILES,
    MAX_MULTIPART_TEXT_PART_BYTES, MAX_UPLOAD_NAME_BYTES,
)
from backend.app.models.dataset_schemas import DatasetListQuery, DatasetUploadMetadata
from backend.app.models.error_schemas import ErrorResponse
from trainer.dataset_schema import InstructionRecord

REQUEST_ID_HEADER = {
    "description": "Server-generated UUID; matches error.request_id",
    "schema": {"type": "string", "format": "uuid"},
}


def response_headers(*, location=False):
    headers = {"X-Request-ID": REQUEST_ID_HEADER}
    if location:
        headers["Location"] = {"description": "Dataset detail URL", "schema": {"type": "string"}}
    return {"headers": headers}


def error_responses(statuses: dict[int, str]):
    return {status: {"model": ErrorResponse, "description": description, **response_headers()}
            for status, description in statuses.items()}


COMMON_ERRORS = {500: "INTERNAL_ERROR", 503: "STORAGE_UNAVAILABLE or DATABASE_UNAVAILABLE"}
UPLOAD_BODY = {"requestBody": {
    "required": True,
    "content": {"multipart/form-data": {"schema": {"$ref": "#/components/schemas/DatasetUpload"}}},
}}
LIST_PARAMETERS = {"parameters": [
    {"name": name, "in": "query", "required": False, "schema": schema}
    for name, schema in DatasetListQuery.model_json_schema()["properties"].items()
]}


def add_dataset_schemas(openapi: dict) -> dict:
    """Only the binary upload needs augmentation; response models come from routes."""
    schemas = openapi.setdefault("components", {}).setdefault("schemas", {})
    record = InstructionRecord.model_json_schema()
    schemas.update(record.pop("$defs", {}))
    schemas["InstructionRecord"] = record
    name = DatasetUploadMetadata.model_json_schema()["properties"]["name"]
    name = next(item for item in name["anyOf"] if item.get("type") != "null")
    schemas["DatasetUpload"] = {
        "type": "object", "additionalProperties": False, "required": ["file"],
        "properties": {
            "file": {"type": "string", "format": "binary", "x-max-bytes": MAX_DATASET_BYTES,
                     "description": "UTF-8 .jsonl file, instruction/input/output records",
                     "x-record-schema": {"$ref": "#/components/schemas/InstructionRecord"}},
            "name": {**name, "description": "Optional display name; omission uses sanitized filename",
                     "x-max-bytes": MAX_UPLOAD_NAME_BYTES},
        },
        "x-max-body-bytes": MAX_MULTIPART_BYTES,
        "x-max-line-bytes": MAX_JSONL_LINE_BYTES,
        "x-parser-max-files": MAX_MULTIPART_FILES,
        "x-parser-max-fields": MAX_MULTIPART_FIELDS,
        "x-parser-max-text-part-bytes": MAX_MULTIPART_TEXT_PART_BYTES,
        "x-duplicate-parts": "rejected",
    }
    openapi["x-dataset-contract-version"] = DATASET_CONTRACT_VERSION
    return openapi
