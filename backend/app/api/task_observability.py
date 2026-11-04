"""HTTP read adapters; SQL/file operations run outside the event loop."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import UUID4
from starlette.concurrency import run_in_threadpool

from backend.app.api.task_openapi import error_responses, response_headers
from backend.app.api.tasks import parse_query
from backend.app.models.observability_schemas import LogsPage, LogsQuery, MetricsPage, MetricsQuery
from backend.app.services.task_observability import TaskObservabilityService

router = APIRouter(prefix="/tasks", tags=["task-observability"])


def get_observability_service(request: Request) -> TaskObservabilityService:
    return request.app.state.task_observability_service


Service = Annotated[TaskObservabilityService, Depends(get_observability_service)]


def query_metadata(model):
    return {"parameters": [{"name": name, "in": "query", "required": False, "schema": schema}
        for name, schema in model.model_json_schema()["properties"].items()],
        "x-observability-contract-version": "1.0.0", "x-duplicate-query-parameters": "rejected"}


@router.get("/{task_id}/metrics", response_model=MetricsPage, operation_id="get_task_metrics",
    summary="Read bounded metrics using source identity and byte cursor",
    openapi_extra=query_metadata(MetricsQuery),
    responses={200: response_headers(), **error_responses({404: "TASK_NOT_FOUND", 409: "METRICS_CURSOR_INVALID",
        422: "VALIDATION_ERROR", 500: "METRICS_CORRUPTED / METRICS_UNAVAILABLE / INTERNAL_ERROR",
        503: "DATABASE_UNAVAILABLE"})})
async def metrics(task_id: UUID4, request: Request, response: Response, service: Service) -> MetricsPage:
    query = parse_query(request, MetricsQuery)
    response.headers["Cache-Control"] = "no-store"
    return await run_in_threadpool(service.metrics, task_id, query)


@router.get("/{task_id}/logs", response_model=LogsPage, operation_id="get_task_logs",
    summary="Read a bounded value-filtered task-local log tail",
    openapi_extra=query_metadata(LogsQuery),
    responses={200: response_headers(), **error_responses({404: "TASK_NOT_FOUND", 422: "VALIDATION_ERROR",
        500: "LOGS_UNAVAILABLE / INTERNAL_ERROR", 503: "DATABASE_UNAVAILABLE"})})
async def logs(task_id: UUID4, request: Request, response: Response, service: Service) -> LogsPage:
    query = parse_query(request, LogsQuery)
    response.headers["Cache-Control"] = "no-store"
    return await run_in_threadpool(service.logs, task_id, query)
