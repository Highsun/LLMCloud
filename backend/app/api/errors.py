"""Safe, transport-level translation into the public error contract."""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from backend.app.core.dataset_contract import MAX_ERROR_DETAILS
from backend.app.core.request_context import request_id_context
from backend.app.models.error_schemas import ApiError, ApiErrorCode, ErrorDetail, ErrorResponse
from backend.app.services.errors import DatasetServiceError


def detail(loc, code: str, message: str) -> ErrorDetail:
    return ErrorDetail(loc=loc, code=code, message=message, line=None, column=None)


def validation_error(details: list[ErrorDetail]) -> DatasetServiceError:
    return DatasetServiceError(ApiErrorCode.VALIDATION_ERROR, "请求字段不符合要求。", 422, details)


def safe_validation_details(errors, prefix=()) -> list[ErrorDetail]:
    # Never copy input, ctx, or Pydantic's message (which can embed user input).
    result = []
    for error in errors:
        kind = error["type"]
        if kind == "missing":
            code, message = "missing", "缺少必填字段。"
        elif kind == "extra_forbidden":
            code, message = "extra_field", "不支持此字段。"
        elif kind in ("greater_than_equal", "less_than_equal", "string_too_long", "string_too_short"):
            code, message = "out_of_range", "字段超出允许范围。"
        elif kind == "value_error":
            code, message = "invalid_type", "字段值不符合要求。"
        else:
            code, message = "invalid_type", "字段类型或格式不正确。"
        # Only field names and indexes, never error input values, are exposed.
        result.append(detail([*prefix, *error["loc"]], code, message))
    return result


def error_response(error: DatasetServiceError, *, headers=None) -> JSONResponse:
    payload = ErrorResponse(error=ApiError(
        code=error.code, message=error.message,
        details=error.details[:MAX_ERROR_DETAILS],
        details_truncated=len(error.details) > MAX_ERROR_DETAILS,
        request_id=request_id_context.get(),
    ))
    return JSONResponse(payload.model_dump(mode="json"), status_code=error.status_code, headers=headers)


async def service_error_handler(_request: Request, error: DatasetServiceError):
    return error_response(error)


async def request_validation_handler(_request: Request, error: RequestValidationError):
    return error_response(validation_error(safe_validation_details(error.errors())))


async def http_error_handler(_request: Request, error: HTTPException):
    code, message = {
        404: (ApiErrorCode.NOT_FOUND, "请求的接口不存在。"),
        405: (ApiErrorCode.METHOD_NOT_ALLOWED, "此接口不支持该请求方法。"),
    }.get(error.status_code, (ApiErrorCode.HTTP_ERROR, "请求无法处理。"))
    return error_response(DatasetServiceError(code, message, error.status_code), headers=error.headers)
