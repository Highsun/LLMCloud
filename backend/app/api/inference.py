"""M5 HTTP admission and bounded wait. GPU execution stays in the worker."""

import logging
from time import monotonic, time

from anyio import CancelScope, create_task_group, move_on_after, sleep
from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from backend.app.api.errors import detail, validation_error
from backend.app.api.task_openapi import response_headers
from backend.app.api.tasks import parse_json_body, parse_query
from backend.app.core.task_contract import PublishOutcome
from backend.app.core.task_protocols import TaskStoreError
from backend.app.models.error_schemas import ApiErrorCode
from backend.app.models.inference_schemas import (
    INFERENCE_CLAIM_SECONDS, INFERENCE_WAIT_SECONDS, MAX_INFERENCE_BODY_BYTES,
    InferenceErrorCode, InferenceErrorResponse, InferenceRequest, InferenceResponse,
)
from backend.app.services.errors import DatasetServiceError
from backend.app.services.inference_repository import FINISHED, WAITING
from backend.app.services.tasks import database_error

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/inference", tags=["inference"])

FAILURES = {
    ApiErrorCode.TASK_NOT_FOUND: (404, "训练任务不存在。"),
    ApiErrorCode.ARTIFACT_NOT_READY: (409, "训练任务尚未完成，请选择已完成任务。"),
    InferenceErrorCode.GPU_BUSY: (409, "GPU 正在处理训练或推理，请稍后重试。"),
    ApiErrorCode.INVALID_ARTIFACT: (500, "训练产物不完整或与完成记录不一致。"),
    InferenceErrorCode.INFERENCE_FAILED: (500, "模型加载或生成失败。"),
    InferenceErrorCode.MODEL_NOT_CACHED: (503, "该版本的模型缓存尚未就绪。"),
    ApiErrorCode.DATABASE_UNAVAILABLE: (503, "推理状态存储暂不可用。"),
    InferenceErrorCode.INFERENCE_UNAVAILABLE: (503, "推理暂不可用，请稍后手动重试。"),
    InferenceErrorCode.INFERENCE_TIMEOUT: (504, "推理等待超时，GPU 可能仍在清理。"),
}

RESPONSE_HEADERS = response_headers()
RESPONSE_HEADERS["headers"]["Cache-Control"] = {"schema": {"type": "string", "const": "no-store"}}


def _failure(code):
    if code == ApiErrorCode.VALIDATION_ERROR:
        return validation_error([detail(["body", "prompt"], "out_of_range", "模板化后的提示词不能超过 2048 token。")])
    try:
        parsed = InferenceErrorCode(code)
    except ValueError:
        parsed = ApiErrorCode(code)
    status, message = FAILURES[parsed]
    return DatasetServiceError(parsed, message, status)


def add_inference_schema(openapi):
    schema = InferenceRequest.model_json_schema(ref_template="#/components/schemas/{model}")
    schema["x-max-body-bytes"] = MAX_INFERENCE_BODY_BYTES
    schema["x-duplicate-json-keys"] = "rejected"
    openapi.setdefault("components", {}).setdefault("schemas", {})["InferenceRequest"] = schema
    return openapi


async def _watch_disconnect(request, cancel_scope):
    while (await request.receive())["type"] != "http.disconnect":
        pass
    cancel_scope.cancel()


async def _wait_for_result(repository, job_id, published, claim_deadline, deadline):
    while True:
        job = await run_in_threadpool(repository.get_inference, job_id)
        if job is None:
            raise _failure(InferenceErrorCode.INFERENCE_UNAVAILABLE)
        status, error, result = job
        if status == FINISHED:
            if error is not None:
                raise _failure(error)
            return InferenceResponse.model_validate(result)
        now = monotonic()
        if status == WAITING and (published != PublishOutcome.ACCEPTED or now >= claim_deadline):
            if await run_in_threadpool(repository.stop_waiting, job_id):
                raise _failure(InferenceErrorCode.INFERENCE_UNAVAILABLE)
            continue  # The worker or training changed the state before our update.
        if now >= deadline:
            raise _failure(InferenceErrorCode.INFERENCE_TIMEOUT)
        await sleep(min(0.2, deadline - now))


@router.post("", response_model=InferenceResponse, operation_id="run_inference",
    openapi_extra={
        "x-wait-budget-seconds": INFERENCE_WAIT_SECONDS,
        "x-claim-budget-seconds": INFERENCE_CLAIM_SECONDS,
        "requestBody": {"required": True, "content": {"application/json": {
            "schema": {"$ref": "#/components/schemas/InferenceRequest"},
        }}},
    },
    responses={
        200: RESPONSE_HEADERS,
        **{status: {"model": InferenceErrorResponse, "description": description, **RESPONSE_HEADERS}
           for status, description in {
               400: "HTTP_ERROR", 404: "TASK_NOT_FOUND", 409: "GPU_BUSY or ARTIFACT_NOT_READY",
               413: "REQUEST_TOO_LARGE", 415: "UNSUPPORTED_MEDIA_TYPE", 422: "VALIDATION_ERROR",
               500: "INVALID_ARTIFACT, INFERENCE_FAILED or INTERNAL_ERROR",
               503: "DATABASE_UNAVAILABLE, MODEL_NOT_CACHED or INFERENCE_UNAVAILABLE",
               504: "INFERENCE_TIMEOUT",
           }.items()},
    })
async def infer(request: Request) -> InferenceResponse:
    started, wall_start = monotonic(), time()
    claim_deadline = started + INFERENCE_CLAIM_SECONDS
    deadline = started + INFERENCE_WAIT_SECONDS
    parse_query(request)
    with move_on_after(INFERENCE_WAIT_SECONDS) as reading:
        body = await parse_json_body(request, InferenceRequest)
    if reading.cancelled_caught:
        raise _failure(InferenceErrorCode.INFERENCE_UNAVAILABLE)
    if await request.is_disconnected():
        raise ClientDisconnect()

    state = request.app.state
    job_id = request.state.request_id
    # Use the server-generated id even if admission commits just as this
    # coroutine is cancelled. Cleanup is harmless for a denied reservation.
    cleanup = True
    try:
        denied = await run_in_threadpool(state.inference_repository.reserve, job_id, body,
            wall_start + INFERENCE_CLAIM_SECONDS, wall_start + INFERENCE_WAIT_SECONDS)
        if denied is not None:
            cleanup = False
            raise _failure(denied)
        if await request.is_disconnected():
            raise ClientDisconnect()
        published = PublishOutcome.NOT_SENT
        if monotonic() < claim_deadline:
            try:
                published = await run_in_threadpool(state.inference_publisher.publish_inference, job_id)
            except Exception as exc:
                logger.warning("inference_publish_unconfirmed request_id=%s reason=%s",
                               job_id, type(exc).__name__)
                published = PublishOutcome.UNKNOWN
        failure = result = None
        async with create_task_group() as waiting:
            waiting.start_soon(_watch_disconnect, request, waiting.cancel_scope)
            try:
                result = await _wait_for_result(state.inference_repository, job_id, published,
                                                claim_deadline, deadline)
            except (DatasetServiceError, TaskStoreError) as exc:
                # Raise outside the task group so the HTTP error keeps its shape.
                failure = exc
            finally:
                waiting.cancel_scope.cancel()
        if failure is not None:
            raise failure
        if result is None:
            raise ClientDisconnect()
        return result
    except TaskStoreError:
        raise database_error() from None
    finally:
        if cleanup:
            with CancelScope(shield=True):
                try:
                    await run_in_threadpool(state.inference_repository.cancel_inference, job_id)
                except TaskStoreError:
                    logger.warning("inference_cleanup_unconfirmed request_id=%s", job_id)
