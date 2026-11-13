"""Public M5 request and response models. Imports no execution dependencies."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, UUID4, field_validator, model_validator

from backend.app.core.task_contract import MAX_TASK_BODY_BYTES
from backend.app.models.error_schemas import ApiError, ApiErrorCode
from trainer.contracts import Revision

MAX_INFERENCE_BODY_BYTES = MAX_TASK_BODY_BYTES
INFERENCE_WAIT_SECONDS = 90
INFERENCE_CLAIM_SECONDS = 10
INFERENCE_RETENTION_SECONDS = 600


class InferenceErrorCode(StrEnum):
    GPU_BUSY = "GPU_BUSY"
    INFERENCE_UNAVAILABLE = "INFERENCE_UNAVAILABLE"
    INFERENCE_TIMEOUT = "INFERENCE_TIMEOUT"
    INFERENCE_FAILED = "INFERENCE_FAILED"
    MODEL_NOT_CACHED = "MODEL_NOT_CACHED"


class InferenceApiError(ApiError):
    code: ApiErrorCode | InferenceErrorCode


class InferenceErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    error: InferenceApiError


class InferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID4
    prompt: str = Field(strict=True, min_length=1, max_length=8192)
    max_new_tokens: int = Field(default=128, strict=True, ge=1, le=256)
    mode: Literal["adapter", "compare"] = "adapter"

    @field_validator("prompt")
    @classmethod
    def valid_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Prompt must have content")
        value.encode("utf-8")  # Reject lone escaped surrogate code points.
        return value


class InferenceAnswer(BaseModel):
    generated_text: str
    generated_tokens: int = Field(ge=1, le=256)


class InferenceResponse(BaseModel):
    task_id: UUID4
    mode: Literal["adapter", "compare"]
    base_model: str
    model_revision: Revision
    input_tokens: int = Field(ge=1, le=2048)
    max_new_tokens: int = Field(ge=1, le=256)
    base: InferenceAnswer | None
    adapter: InferenceAnswer

    @model_validator(mode="after")
    def matching_answers(self):
        if (self.mode == "compare") != (self.base is not None):
            raise ValueError("Base answer must match inference mode")
        if any(answer.generated_tokens > self.max_new_tokens
               for answer in (self.base, self.adapter) if answer is not None):
            raise ValueError("Answer exceeded the requested token limit")
        return self
