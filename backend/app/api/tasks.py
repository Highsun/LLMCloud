"""Strict HTTP adapters for persisted task use cases; no GPU or queue code here."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import UUID4, ValidationError
from starlette.concurrency import run_in_threadpool

from backend.app.api.errors import detail, safe_validation_details, validation_error
from backend.app.api.task_openapi import (
    LIST_EXTRA, POST_EXTRA, SUBMISSION_UNAVAILABLE, error_responses, response_headers,
)
from backend.app.models.error_schemas import ApiErrorCode
from backend.app.models.task_schemas import TaskCreate, TaskDetail, TaskListQuery, TaskPage, TaskSubmissionHeaders
from backend.app.services.errors import DatasetServiceError
from backend.app.services.tasks import TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])


def get_task_service(request: Request) -> TaskService:
    return request.app.state.task_service


Service = Annotated[TaskService, Depends(get_task_service)]


def parse_query(request, model=None):
    values, errors = {}, []
    fields = model.model_fields if model is not None else {}
    for key, value in request.query_params.multi_items():
        if key not in fields:
            errors.append(detail(["query", key], "extra_field", "不支持此查询参数。"))
        elif key in values:
            errors.append(detail(["query", key], "duplicate_field", "查询参数不能重复。"))
        else:
            if key in ("page", "page_size"):
                numeric = value.removeprefix("-").removeprefix("+")
                if not numeric or not numeric.isascii() or not numeric.isdigit():
                    errors.append(detail(["query", key], "invalid_type", "查询参数必须是整数。"))
            values[key] = value
    if errors:
        raise validation_error(errors)
    if model is not None:
        try:
            return model.model_validate(values)
        except ValidationError as error:
            raise validation_error(safe_validation_details(error.errors(), ("query",))) from None


def submission_headers(request):
    values = request.headers.getlist("idempotency-key")
    if len(values) > 1:
        raise validation_error([detail(["header", "Idempotency-Key"], "duplicate_field", "去重请求头不能重复。")])
    try:
        return TaskSubmissionHeaders.model_validate({"Idempotency-Key": values[0]} if values else {})
    except ValidationError as error:
        raise validation_error(safe_validation_details(error.errors(), ("header",))) from None


class DuplicateJSONKey(ValueError):
    pass


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJSONKey()
        result[key] = value
    return result


def reject_constant(_value):
    raise ValueError("Non-finite number")


async def task_body(request):
    types = request.headers.getlist("content-type")
    encodings = request.headers.getlist("content-encoding")
    bad_charset = any(part.partition("=")[0].strip().lower() == "charset"
        and part.partition("=")[2].strip().strip('"').lower().replace("-", "") != "utf8"
        for part in types[0].split(";")[1:]) if len(types) == 1 else False
    if (len(types) != 1 or types[0].split(";", 1)[0].strip().lower() != "application/json"
            or bad_charset or (encodings and (len(encodings) != 1 or encodings[0].strip().lower() != "identity"))):
        raise DatasetServiceError(ApiErrorCode.UNSUPPORTED_MEDIA_TYPE, "请使用未压缩的 UTF-8 application/json。", 415)
    raw = await request.body()  # ASGI middleware bounds real received bytes, including chunked requests.
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=reject_constant)
    except DuplicateJSONKey:
        raise validation_error([detail(["body"], "duplicate_field", "JSON 字段不能重复。")]) from None
    except (ValueError, UnicodeError, RecursionError):
        raise validation_error([detail(["body"], "invalid_json", "请求正文必须是有效的 UTF-8 JSON。")]) from None
    try:
        return TaskCreate.model_validate(value)
    except ValidationError as error:
        raise validation_error(safe_validation_details(error.errors(), ("body",))) from None


@router.post("", status_code=202, response_model=TaskDetail, operation_id="create_task",
    summary="Persist and dispatch a training task without waiting for execution", openapi_extra=POST_EXTRA,
    responses={202: {"description": "New task accepted; actual state may already be RUNNING", **response_headers(True)},
        200: {"model": TaskDetail, "description": "Idempotent replay; no republish", **response_headers(True)},
        503: SUBMISSION_UNAVAILABLE,
        **error_responses({400: "HTTP_ERROR", 404: "DATASET_NOT_FOUND", 409: "IDEMPOTENCY_CONFLICT",
                          413: "REQUEST_TOO_LARGE", 415: "UNSUPPORTED_MEDIA_TYPE", 422: "VALIDATION_ERROR", 500: "INTERNAL_ERROR"})})
async def create_task(request: Request, response: Response, service: Service) -> TaskDetail:
    parse_query(request)
    headers = submission_headers(request)
    body = await task_body(request)
    result = await run_in_threadpool(service.create, body, headers.idempotency_key)
    response.status_code = 200 if result.replayed else 202
    response.headers["Location"] = f"{request.app.state.settings.api_prefix}/tasks/{result.task.id}"
    return result.task


@router.get("", response_model=TaskPage, operation_id="list_tasks",
    summary="Filter tasks by status before stable pagination", openapi_extra=LIST_EXTRA,
    responses={200: response_headers(), **error_responses({422: "VALIDATION_ERROR", 500: "INTERNAL_ERROR", 503: "DATABASE_UNAVAILABLE"})})
async def list_tasks(request: Request, service: Service) -> TaskPage:
    return await run_in_threadpool(service.list, parse_query(request, TaskListQuery))


@router.get("/{task_id}", response_model=TaskDetail, operation_id="get_task",
    summary="Get persisted task state and configuration",
    responses={200: response_headers(), **error_responses({404: "TASK_NOT_FOUND", 422: "VALIDATION_ERROR", 500: "INTERNAL_ERROR", 503: "DATABASE_UNAVAILABLE"})})
async def get_task(task_id: UUID4, request: Request, service: Service) -> TaskDetail:
    parse_query(request)
    return await run_in_threadpool(service.get, task_id)
