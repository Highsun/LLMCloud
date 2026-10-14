"""Initial API contracts; task creation routes are not exposed yet."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from trainer.lora_config import TrainingConfig

SUPPORTED_MODELS = ("Qwen/Qwen2.5-0.5B-Instruct",)


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str
    version: str


class ModelInfo(BaseModel):
    id: str
    name: str
    description: str


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: UUID
    base_model: Literal["Qwen/Qwen2.5-0.5B-Instruct"] = SUPPORTED_MODELS[0]
    config: TrainingConfig = Field(default_factory=TrainingConfig)
