"""Version 1 task DTOs. Types only; HTTP routes are delivered in M3-03."""

from datetime import datetime, timezone
import math
import re
from typing import Literal

from pydantic import (
    AwareDatetime, BaseModel, ConfigDict, Field, UUID4,
    field_serializer, field_validator, model_validator,
)

from backend.app.core.task_contract import (
    DEFAULT_TASK_PAGE_SIZE, MAX_TASK_PAGE_SIZE, TaskErrorCode, TaskStatus,
)
from backend.app.models.error_schemas import ApiError, ApiErrorCode, ErrorResponse
from trainer.contracts import BaseModelId, ContractModel, NonNegativeInt, PositiveInt, Revision
from trainer.lora_config import TrainingConfig


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: UUID4
    base_model: BaseModelId = "Qwen/Qwen2.5-0.5B-Instruct"
    config: TrainingConfig = Field(default_factory=TrainingConfig)


class TaskListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=DEFAULT_TASK_PAGE_SIZE, ge=1, le=MAX_TASK_PAGE_SIZE)
    status: TaskStatus | None = None

    @field_validator("page", "page_size", mode="before")
    @classmethod
    def reject_boolean(cls, value):
        if isinstance(value, bool):
            raise ValueError("Pagination must use integers")
        return value


class TaskSubmissionHeaders(BaseModel):
    """An extracted header DTO, not the full browser header collection."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    idempotency_key: UUID4 | None = Field(default=None, alias="Idempotency-Key")


class TaskSummary(ContractModel):
    id: UUID4
    dataset_id: UUID4
    base_model: BaseModelId
    model_revision: Revision
    status: TaskStatus
    current_step: NonNegativeInt
    total_steps: PositiveInt | None
    progress: float | None = Field(ge=0, le=1, strict=True)
    error_code: TaskErrorCode | None
    error_message: str | None = Field(min_length=1, max_length=1000)
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    finished_at: AwareDatetime | None

    @field_validator("created_at", "started_at", "finished_at", mode="before")
    @classmethod
    def sqlite_utc(cls, value):
        if value is None:
            return value
        if isinstance(value, datetime):
            # SQLite datetimes are UTC even though the driver drops tzinfo.
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        if not isinstance(value, str):
            raise ValueError("Expected an RFC 3339 timestamp")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value):
            raise ValueError("Expected an RFC 3339 timestamp with timezone")
        return value

    @field_serializer("created_at", "started_at", "finished_at", when_used="json")
    def utc_json(self, value: datetime | None) -> str | None:
        return None if value is None else value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @model_validator(mode="after")
    def consistent_state(self):
        if self.total_steps is None:
            if self.progress is not None or self.current_step != 0:
                raise ValueError("Unknown total_steps requires null progress and zero current_step")
        elif (self.current_step > self.total_steps or self.progress is None
              or not math.isclose(self.progress, self.current_step / self.total_steps, abs_tol=1e-9)):
            raise ValueError("Progress must match actual optimizer steps")
        if (self.error_code is None) != (self.error_message is None):
            raise ValueError("Error code and safe message must be supplied together")
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("started_at precedes created_at")
        if self.finished_at is not None and self.finished_at < (self.started_at or self.created_at):
            raise ValueError("finished_at precedes task start/creation")
        if self.status in (TaskStatus.PENDING, TaskStatus.QUEUED):
            if self.started_at is not None or self.finished_at is not None or self.total_steps is not None:
                raise ValueError("Unclaimed tasks have no execution times or steps")
        if self.status == TaskStatus.RUNNING and (self.started_at is None or self.finished_at is not None):
            raise ValueError("RUNNING requires start time without finish time")
        if self.status in (TaskStatus.COMPLETED, TaskStatus.FAILED) and self.finished_at is None:
            raise ValueError("Terminal tasks require finish time")
        if self.status == TaskStatus.FAILED and self.error_code is None:
            raise ValueError("FAILED requires a safe diagnostic")
        if self.status == TaskStatus.COMPLETED:
            if (self.started_at is None or self.total_steps is None
                    or self.current_step != self.total_steps or self.error_code is not None):
                raise ValueError("COMPLETED requires completed steps, start time and no error")
        return self


class TaskDetail(TaskSummary):
    config: TrainingConfig


class TaskPage(ContractModel):
    items: list[TaskSummary]
    total: NonNegativeInt
    page: PositiveInt
    page_size: PositiveInt = Field(le=MAX_TASK_PAGE_SIZE)
    total_pages: NonNegativeInt

    @model_validator(mode="after")
    def consistent_pagination(self):
        if self.total_pages != (self.total + self.page_size - 1) // self.page_size:
            raise ValueError("total_pages must match total/page_size")
        if len(self.items) > min(self.page_size, self.total):
            raise ValueError("Too many items for total/page_size")
        if self.page > self.total_pages and self.items:
            raise ValueError("Pages beyond the end must have no items")
        return self


class TaskSubmissionError(ApiError):
    code: Literal[ApiErrorCode.DISPATCH_FAILED, ApiErrorCode.DISPATCH_UNCERTAIN]
    task_id: UUID4


class TaskSubmissionErrorResponse(ErrorResponse):
    error: TaskSubmissionError
