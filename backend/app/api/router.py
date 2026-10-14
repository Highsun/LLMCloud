from fastapi import APIRouter

from backend.app.core.config import get_settings
from backend.app.models.schemas import HealthResponse, ModelInfo, SUPPORTED_MODELS

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    """Liveness only; this endpoint does not probe Redis, GPU or model weights."""
    return HealthResponse(service=get_settings().app_name, version="0.1.0")


@router.get("/models", response_model=list[ModelInfo], tags=["models"])
def models() -> list[ModelInfo]:
    """A model allowlist, not a claim that weights have already been downloaded."""
    return [
        ModelInfo(
            id=model_id,
            name=model_id.split("/")[-1],
            description="MVP 基础模型；权重将在训练环境准备阶段下载。",
        )
        for model_id in SUPPORTED_MODELS
    ]
