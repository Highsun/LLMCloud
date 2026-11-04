"""CPU-only M4 wire contracts. No files, routes or GPU operations are implied."""

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, TypeAdapter, UUID4, field_validator, model_validator

from backend.app.core.observability_contract import (
    DEFAULT_LOG_TAIL, DEFAULT_METRICS_LIMIT, DOWNLOAD_CACHE_CONTROL,
    DOWNLOAD_MEDIA_TYPE, DOWNLOAD_RETRY_AFTER_SECONDS, MAX_LOG_READ_BYTES,
    MAX_LOG_RESPONSE_BYTES, MAX_LOG_TAIL, MAX_METRICS_LIMIT, MAX_SAFE_INTEGER,
    OBSERVABILITY_CONTRACT_VERSION, SourceState,
)
from backend.app.core.task_contract import TaskStatus
from trainer.contracts import ContractModel, Sha256, TrainingProgress

SafeOffset = Annotated[int, Field(strict=True, ge=0, le=MAX_SAFE_INTEGER)]


def query_integer(value):
    """HTTP decimal text is allowed; Python bool/float and loose spellings aren't."""
    if isinstance(value, str):
        if not value or not value.isascii() or not value.isdecimal():
            raise ValueError("Expected ASCII decimal integer query text")
        try:
            return int(value)
        except ValueError:
            raise ValueError("Integer query text is too large") from None
    return value


class ObservabilityModel(ContractModel):
    model_config = ConfigDict(revalidate_instances="always")


class MetricsQuery(ObservabilityModel):
    cursor: SafeOffset = 0
    source_id: Sha256 | None = None
    limit: Annotated[int, Field(strict=True, ge=1, le=MAX_METRICS_LIMIT)] = DEFAULT_METRICS_LIMIT

    _query_integers = field_validator("cursor", "limit", mode="before")(query_integer)

    @model_validator(mode="after")
    def continued_source(self):
        if self.cursor > 0 and self.source_id is None:
            raise ValueError("A nonzero cursor requires source_id")
        return self


class LogsQuery(ObservabilityModel):
    tail: Annotated[int, Field(strict=True, ge=1, le=MAX_LOG_TAIL)] = DEFAULT_LOG_TAIL

    _query_integer = field_validator("tail", mode="before")(query_integer)


class AdapterQuery(ObservabilityModel):
    """Download has no query parameters; unknown parameters are forbidden."""


class MetricRecord(TrainingProgress):
    """TrainingProgress unchanged, with a response-only physical line identity."""

    model_config = ConfigDict(revalidate_instances="always")
    offset: SafeOffset


class MetricsPage(ObservabilityModel):
    contract_version: Literal["1.0.0"] = OBSERVABILITY_CONTRACT_VERSION
    task_id: UUID4
    task_status: TaskStatus
    source_state: SourceState
    source_id: Sha256 | None
    items: list[MetricRecord] = Field(max_length=MAX_METRICS_LIMIT)
    next_cursor: SafeOffset
    has_more: bool = Field(strict=True)
    tail_incomplete: bool = Field(strict=True)

    @model_validator(mode="after")
    def consistent_page(self):
        if self.source_state == SourceState.NOT_CREATED:
            if (self.task_status == TaskStatus.COMPLETED or self.source_id is not None
                    or self.items or self.next_cursor or self.has_more or self.tail_incomplete):
                raise ValueError("not_created requires an unfinished empty source at cursor zero")
            return self
        if self.source_id is None:
            raise ValueError("A ready source requires source_id")
        if not self.items and self.has_more:
            raise ValueError("An empty page must not cause a same-cursor has_more loop")
        if self.task_status == TaskStatus.COMPLETED and self.tail_incomplete:
            raise ValueError("Completed metrics must not have an incomplete tail")
        previous_offset = previous_order = total = None
        for record in self.items:
            order = (record.step, record.kind == "eval")
            if previous_offset is not None and (record.offset <= previous_offset or order <= previous_order):
                raise ValueError("Offsets and train/eval optimizer order must advance")
            if total is not None and record.total_steps != total:
                raise ValueError("Metric page has inconsistent total_steps")
            previous_offset, previous_order, total = record.offset, order, record.total_steps
        if self.items and self.next_cursor <= self.items[-1].offset:
            raise ValueError("next_cursor must be after the last returned line start")
        return self


class LogsPage(ObservabilityModel):
    contract_version: Literal["1.0.0"] = OBSERVABILITY_CONTRACT_VERSION
    task_id: UUID4
    task_status: TaskStatus
    source_state: SourceState
    lines: list[Annotated[str, Field(strict=True, max_length=MAX_LOG_READ_BYTES)]] = Field(max_length=MAX_LOG_TAIL)
    truncated: bool = Field(strict=True)
    tail_incomplete: bool = Field(strict=True)
    filtered_lines: Annotated[int, Field(strict=True, ge=0, le=MAX_LOG_TAIL)]

    @field_validator("lines")
    @classmethod
    def single_lines(cls, values):
        if any(any(char in line for char in ("\n", "\r", "\0")) for line in values):
            raise ValueError("Each log entry must be one line without NUL")
        try:
            for line in values:
                line.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Log response must contain valid UTF-8 text") from None
        return values

    @model_validator(mode="after")
    def consistent_page(self):
        if self.source_state == SourceState.NOT_CREATED:
            if (self.task_status == TaskStatus.COMPLETED or self.lines or self.truncated
                    or self.tail_incomplete or self.filtered_lines):
                raise ValueError("not_created requires no log records or truncation/filter flags")
        if len(self.model_dump_json().encode("utf-8")) > MAX_LOG_RESPONSE_BYTES:
            raise ValueError("Serialized log response exceeds its byte limit")
        return self


class AdapterDownloadHeaders(ObservabilityModel):
    """Header description with task context, NOT a JSON download response body."""

    model_config = ConfigDict(populate_by_name=True)
    task_id: UUID4
    content_type: Literal["application/zip"] = Field(default=DOWNLOAD_MEDIA_TYPE, alias="Content-Type")
    content_disposition: str = Field(strict=True, alias="Content-Disposition")
    cache_control: Literal["no-store"] = Field(default=DOWNLOAD_CACHE_CONTROL, alias="Cache-Control")

    @property
    def filename(self):
        return f"llmcloud-adapter-{self.task_id}.zip"

    @property
    def archive_root(self):
        return f"{self.task_id}/"

    @model_validator(mode="after")
    def controlled_filename(self):
        if self.content_disposition != f'attachment; filename="{self.filename}"':
            raise ValueError("Content-Disposition must use the canonical server task filename")
        return self

    @classmethod
    def for_task(cls, task_id):
        parsed = TypeAdapter(UUID4).validate_python(task_id)
        return cls(task_id=parsed, content_disposition=f'attachment; filename="llmcloud-adapter-{parsed}.zip"')

    def as_headers(self):
        return self.model_dump(mode="json", by_alias=True, exclude={"task_id"})


class DownloadBusyHeaders(ObservabilityModel):
    model_config = ConfigDict(populate_by_name=True)
    retry_after: Literal["2"] = Field(default=str(DOWNLOAD_RETRY_AFTER_SECONDS), alias="Retry-After")
