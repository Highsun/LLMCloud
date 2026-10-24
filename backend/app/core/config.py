"""Configuration shared by the API and the local worker."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.app.core.task_contract import DEFAULT_MODEL_REVISION
from trainer.contracts import PositiveInt, Revision

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "LLMCloud"
    app_env: str = "development"
    api_prefix: str = "/api/v1"
    data_dir: Path = PROJECT_ROOT / "data"
    log_dir: Path = PROJECT_ROOT / "logs"
    database_url: str = ""
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    redis_url: str = "redis://127.0.0.1:6379/0"
    celery_result_backend: str = "redis://127.0.0.1:6379/1"
    training_queue: str = "gpu"
    default_model: Literal["Qwen/Qwen2.5-0.5B-Instruct"] = "Qwen/Qwen2.5-0.5B-Instruct"
    default_model_revision: Revision = DEFAULT_MODEL_REVISION
    training_precision: Literal["bf16", "fp32"] = "bf16"
    training_max_steps: PositiveInt | None = None

    @field_validator("training_max_steps", mode="before")
    @classmethod
    def parse_internal_step_limit(cls, value):
        # Environment variables are text; direct bool/float values stay invalid.
        if isinstance(value, str) and value.isascii() and value.isdecimal():
            return int(value)
        return value

    @field_validator("data_dir", "log_dir", mode="before")
    @classmethod
    def resolve_path(cls, value: str | Path) -> Path:
        path = Path(value).expanduser()
        return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()

    @property
    def resolved_database_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'llmcloud.db'}"

    def ensure_directories(self) -> None:
        for path in (
            self.data_dir / "datasets",
            self.data_dir / "models",
            self.data_dir / "outputs",
            self.log_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
