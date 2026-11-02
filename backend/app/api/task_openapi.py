"""Runtime OpenAPI metadata for the strict task body/query/header parsers."""

from backend.app.api.dataset_openapi import REQUEST_ID_HEADER
from backend.app.core.task_contract import MAX_TASK_BODY_BYTES, TASK_CONTRACT_VERSION
from backend.app.models.error_schemas import ErrorResponse
from backend.app.models.task_schemas import (
    TaskCreate, TaskListQuery, TaskSubmissionErrorResponse, TaskSubmissionHeaders,
)


def response_headers(location=False):
    headers = {"X-Request-ID": REQUEST_ID_HEADER}
    if location:
        headers["Location"] = {"description": "Task detail URL", "schema": {"type": "string"}}
    return {"headers": headers}


def error_responses(statuses):
    return {status: {"model": ErrorResponse, "description": description, **response_headers()}
            for status, description in statuses.items()}


POST_EXTRA = {"requestBody": {"required": True, "content": {
    "application/json": {"schema": {"$ref": "#/components/schemas/TaskCreate"}}
}}, "parameters": [{"name": "Idempotency-Key", "in": "header", "required": False,
    "description": "UUIDv4; the same key/request returns its original task without republishing.",
    "schema": TaskSubmissionHeaders.model_json_schema()["properties"]["Idempotency-Key"]}]}
LIST_EXTRA = {"parameters": [{"name": name, "in": "query", "required": False, "schema": schema}
    for name, schema in TaskListQuery.model_json_schema(ref_template="#/components/schemas/{model}")["properties"].items()]}
SUBMISSION_UNAVAILABLE = {
    "description": "DATABASE_UNAVAILABLE before a known task ID, or DISPATCH_FAILED/DISPATCH_UNCERTAIN with task_id",
    "content": {"application/json": {"schema": {"anyOf": [
        {"$ref": "#/components/schemas/ErrorResponse"},
        {"$ref": "#/components/schemas/TaskSubmissionErrorResponse"},
    ]}}}, **response_headers(location=True)}


def add_task_schemas(openapi):
    schemas = openapi.setdefault("components", {}).setdefault("schemas", {})
    for model in (TaskCreate, TaskSubmissionErrorResponse):
        schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
        for name, definition in schema.pop("$defs", {}).items():
            # Preserve schemas already generated from registered response models.
            schemas.setdefault(name, definition)
        schemas[model.__name__] = schema
    schemas["TaskCreate"]["x-max-body-bytes"] = MAX_TASK_BODY_BYTES
    schemas["TaskCreate"]["x-duplicate-json-keys"] = "rejected"
    openapi["x-task-contract-version"] = TASK_CONTRACT_VERSION
    return openapi
