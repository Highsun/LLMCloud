"""HTTP adapters; file persistence and transactions belong to DatasetService."""

from typing import Annotated
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from backend.app.api.dataset_openapi import (
    COMMON_ERRORS, LIST_PARAMETERS, UPLOAD_BODY, error_responses, response_headers,
)
from backend.app.api.errors import detail, safe_validation_details, validation_error
from backend.app.api.multipart import dataset_form_fields, parse_dataset_form
from backend.app.models.dataset_schemas import DatasetDetail, DatasetListQuery, DatasetPage
from backend.app.services.datasets import DatasetService

router = APIRouter(prefix="/datasets", tags=["datasets"])


def get_dataset_service(request: Request) -> DatasetService:
    return request.app.state.dataset_service


Service = Annotated[DatasetService, Depends(get_dataset_service)]


async def persist_upload(service, upload, name):
    # A task group joins the shielded AnyIO worker even when the ASGI task is
    # cancelled directly by the server. The caller may close the upload afterward.
    outcome = None

    async def persist():
        nonlocal outcome
        try:
            outcome = await run_in_threadpool(service.create, upload.file, filename=upload.filename or "", name=name)
        except Exception as error:
            outcome = error

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(persist)
    if isinstance(outcome, Exception):
        raise outcome
    return outcome


def parse_list_query(request: Request) -> DatasetListQuery:
    values, errors = {}, []
    for key, value in request.query_params.multi_items():
        if key not in DatasetListQuery.model_fields:
            errors.append(detail(["query", key], "extra_field", "不支持此查询参数。"))
        elif key in values:
            errors.append(detail(["query", key], "duplicate_field", "查询参数不能重复。"))
        else:
            # Pydantic's int coercion accepts 1.0; the HTTP contract accepts integer text.
            numeric = value.removeprefix("-").removeprefix("+")
            if not numeric or not numeric.isascii() or not numeric.isdigit():
                errors.append(detail(["query", key], "invalid_type", "查询参数必须是整数。"))
            values[key] = value
    if errors:
        raise validation_error(errors)
    try:
        return DatasetListQuery.model_validate(values)
    except ValidationError as error:
        raise validation_error(safe_validation_details(error.errors(), ("query",))) from None


@router.post(
    "", status_code=201, response_model=DatasetDetail, operation_id="upload_dataset",
    summary="Upload and validate one immutable dataset", openapi_extra=UPLOAD_BODY,
    responses={201: {"description": "Dataset committed", **response_headers(location=True)},
               **error_responses({400: "INVALID_MULTIPART", 413: "UPLOAD_TOO_LARGE",
                                  415: "UNSUPPORTED_MEDIA_TYPE", 422: "VALIDATION_ERROR or INVALID_DATASET",
                                  **COMMON_ERRORS})},
)
async def upload_dataset(request: Request, response: Response, service: Service) -> DatasetDetail:
    form = await parse_dataset_form(request)
    try:
        upload, name = dataset_form_fields(form)
        await upload.seek(0)
        result = await persist_upload(service, upload, name)
        response.headers["Location"] = f"{request.app.state.settings.api_prefix}/datasets/{result.id}"
        return result
    finally:
        # Disk-backed UploadFile.close uses a worker too; allow cleanup when an
        # enclosing AnyIO cancel scope is already cancelled.
        with anyio.CancelScope(shield=True):
            await form.close()


@router.get(
    "", response_model=DatasetPage, operation_id="list_datasets",
    summary="List datasets ordered by created_at DESC, id DESC",
    description="Reject unknown and duplicate query parameters. Beyond-last pages return 200 with empty items.",
    openapi_extra=LIST_PARAMETERS,
    responses={200: response_headers(), **error_responses({422: "VALIDATION_ERROR", **COMMON_ERRORS})},
)
async def list_datasets(request: Request, service: Service) -> DatasetPage:
    query = parse_list_query(request)
    return await run_in_threadpool(service.list, query)


@router.get(
    "/{dataset_id}", response_model=DatasetDetail, operation_id="get_dataset",
    summary="Get metadata without reading the raw training file",
    responses={200: response_headers(), **error_responses({404: "DATASET_NOT_FOUND", 422: "VALIDATION_ERROR", **COMMON_ERRORS})},
)
async def get_dataset(dataset_id: UUID, service: Service) -> DatasetDetail:
    return await run_in_threadpool(service.get, dataset_id)
