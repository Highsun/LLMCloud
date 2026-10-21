"""Public error shape shared by the HTTP exception handlers and clients."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, UUID4

from backend.app.core.dataset_contract import MAX_ERROR_DETAILS


class ApiErrorCode(StrEnum):
    INVALID_MULTIPART = "INVALID_MULTIPART"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    UPLOAD_TOO_LARGE = "UPLOAD_TOO_LARGE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_DATASET = "INVALID_DATASET"
    DATASET_NOT_FOUND = "DATASET_NOT_FOUND"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    HTTP_ERROR = "HTTP_ERROR"


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    loc: list[str | int] = Field(min_length=1)
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    line: int | None = Field(ge=1)
    column: int | None = Field(ge=1)


class ApiError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ApiErrorCode
    message: str = Field(min_length=1)
    details: list[ErrorDetail] = Field(max_length=MAX_ERROR_DETAILS)
    details_truncated: bool
    request_id: UUID4


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ApiError
