"""Transport-neutral service failures translated into ErrorResponse by the API."""

from backend.app.models.error_schemas import ApiErrorCode, ErrorDetail
from trainer.dataset import DatasetValidationError


class DatasetServiceError(Exception):
    def __init__(self, code: ApiErrorCode, message: str, status_code: int, details=None):
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code
        self.details = details or []


def validation_failure(error: DatasetValidationError) -> DatasetServiceError:
    large = error.code in ("file_too_large", "line_too_large")
    loc = ["body", "file"] + ([error.field] if error.field else [])
    return DatasetServiceError(
        ApiErrorCode.UPLOAD_TOO_LARGE if large else ApiErrorCode.INVALID_DATASET,
        error.message, 413 if large else 422,
        [ErrorDetail(loc=loc, code=error.code, message=error.message, line=error.line, column=error.column)],
    )
