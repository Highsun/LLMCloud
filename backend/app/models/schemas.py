"""Initial API contracts; task creation routes are not exposed yet."""

from pydantic import BaseModel

# Preserve the original import used by integrations before task routes exist.
from backend.app.models.task_schemas import TaskCreate  # noqa: F401

SUPPORTED_MODELS = ("Qwen/Qwen2.5-0.5B-Instruct",)


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str
    version: str


class ModelInfo(BaseModel):
    id: str
    name: str
    description: str
