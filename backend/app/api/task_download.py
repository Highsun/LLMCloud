"""Binary response owns its file/slot until success, disconnect or cancellation."""

from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, Request
from pydantic import UUID4
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from backend.app.api.errors import error_response
from backend.app.api.task_openapi import error_responses, response_headers
from backend.app.api.tasks import parse_query
from backend.app.core.observability_contract import DOWNLOAD_CHUNK_BYTES
from backend.app.models.error_schemas import ApiErrorCode
from backend.app.models.observability_schemas import AdapterDownloadHeaders, AdapterQuery, DownloadBusyHeaders
from backend.app.services.errors import DatasetServiceError
from backend.app.services.task_download import PreparationTicket, TaskDownloadService

router = APIRouter(prefix="/tasks", tags=["task-observability"])


class AdapterResponse(Response):
    def __init__(self, prepared, task_id):
        super().__init__(content=b"", headers=AdapterDownloadHeaders.for_task(task_id).as_headers())
        self.headers["Content-Length"] = str(prepared.size)
        self.prepared = prepared

    async def __call__(self, scope, receive, send):
        try:
            async with anyio.create_task_group() as group:
                async def stream():
                    await send({"type": "http.response.start", "status": 200, "headers": self.raw_headers})
                    while chunk := await run_in_threadpool(self.prepared.stream.read, DOWNLOAD_CHUNK_BYTES):
                        await send({"type": "http.response.body", "body": chunk, "more_body": True})
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
                    group.cancel_scope.cancel()

                async def disconnected():
                    while True:
                        if (await receive())["type"] == "http.disconnect":
                            group.cancel_scope.cancel()
                            return

                group.start_soon(disconnected)
                await stream()
        finally:
            # Cleanup cannot depend on BackgroundTask reaching normal EOF.
            with anyio.CancelScope(shield=True):
                await run_in_threadpool(self.prepared.close)


async def prepare_response(service, task_id):
    ticket = PreparationTicket(service, task_id)
    try:
        prepared = await run_in_threadpool(ticket.run)
        return AdapterResponse(prepared, task_id)
    except BaseException:
        leftover = ticket.abandon()
        if leftover is not None:
            with anyio.CancelScope(shield=True):
                await run_in_threadpool(leftover.close)
        raise


def get_download_service(request: Request) -> TaskDownloadService:
    return request.app.state.task_download_service


Service = Annotated[TaskDownloadService, Depends(get_download_service)]
SUCCESS = {**response_headers(), "description": "Verified binary ZIP, not a JSON header-description object",
    "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
    "headers": {**response_headers()["headers"],
        "Content-Disposition": {"schema": {"type": "string"}, "description": 'attachment; filename="llmcloud-adapter-{task_id}.zip"'},
        "Cache-Control": {"schema": {"type": "string", "const": "no-store"}},
        "Content-Length": {"schema": {"type": "string", "pattern": "^[0-9]+$"}}}}
ERRORS = error_responses({404: "TASK_NOT_FOUND", 409: "ARTIFACT_NOT_READY", 413: "ARTIFACT_TOO_LARGE",
    422: "VALIDATION_ERROR", 429: "DOWNLOAD_BUSY", 500: "INVALID_ARTIFACT / STORAGE_UNAVAILABLE / INTERNAL_ERROR",
    503: "DATABASE_UNAVAILABLE"})
ERRORS[429]["headers"]["Retry-After"] = {"schema": {"type": "string", "const": "2"}}


@router.get("/{task_id}/adapter", operation_id="download_task_adapter", response_class=Response,
    summary="Download a completed task's verified Adapter bundle", responses={200: SUCCESS, **ERRORS},
    openapi_extra={"x-observability-contract-version": "1.0.0", "x-query-parameters": "none; extras/duplicates rejected"})
async def adapter(task_id: UUID4, request: Request, service: Service):
    parse_query(request, AdapterQuery)
    try:
        return await prepare_response(service, task_id)
    except DatasetServiceError as error:
        if error.code == ApiErrorCode.DOWNLOAD_BUSY:
            return error_response(error, headers=DownloadBusyHeaders().model_dump(mode="json", by_alias=True))
        raise
