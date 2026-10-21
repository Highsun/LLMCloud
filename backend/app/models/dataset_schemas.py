"""Shared dataset DTOs for service results and the public HTTP contract."""

from datetime import datetime, timezone
from typing import Literal

from pydantic import (
    AwareDatetime, BaseModel, ConfigDict, Field, UUID4,
    field_serializer, field_validator, model_validator,
)

from backend.app.core.dataset_contract import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


class DatasetUploadMetadata(BaseModel):
    """The text fields of a multipart request; file is a separate binary part."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, value):
        if isinstance(value, str):
            if any(ord(character) < 32 or ord(character) == 127 for character in value):
                raise ValueError("名称不能包含控制字符")
            return value.strip()
        return value


class DatasetListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)


class DatasetSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID4
    name: str = Field(min_length=1, max_length=255)
    format: Literal["alpaca_jsonl"]
    size_bytes: int = Field(ge=1)
    row_count: int = Field(ge=1)
    created_at: AwareDatetime = Field(json_schema_extra={"format": "date-time"})

    @field_validator("created_at", mode="before")
    @classmethod
    def interpret_sqlite_datetime(cls, value):
        # SQLite drops timezone information. Database datetimes are stored as UTC.
        # External naive timestamp strings remain invalid.
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    @field_serializer("created_at", when_used="json")
    def serialize_created_at(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class DatasetDetail(DatasetSummary):
    original_filename: str = Field(min_length=1, max_length=255)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DatasetPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DatasetSummary]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=MAX_PAGE_SIZE)
    total_pages: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_pagination(self):
        expected_pages = (self.total + self.page_size - 1) // self.page_size
        if self.total_pages != expected_pages:
            raise ValueError("total_pages 与 total/page_size 不一致")
        if len(self.items) > min(self.page_size, self.total):
            raise ValueError("items 数量超过 page_size 或 total")
        if self.page > self.total_pages and self.items:
            raise ValueError("超出总页数时 items 必须为空")
        return self
