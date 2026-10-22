"""CPU-only v1 contracts. Validation performs no filesystem or GPU operations."""

from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trainer.lora_config import TrainingConfig

TRAINING_CONTRACT_VERSION = "1.0.0"
BaseModelId = Literal["Qwen/Qwen2.5-0.5B-Instruct"]
Revision = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
NonNegativeFloat = Annotated[float, Field(strict=True, ge=0)]
ReviewStatus = Literal["reviewed", "draft_unreviewed", "unknown"]
FailureCode = Literal[
    "INVALID_REQUEST", "INVALID_DATASET", "MODEL_NOT_CACHED", "MODEL_LOAD_FAILED",
    "NO_SUPERVISED_TOKENS", "CUDA_OUT_OF_MEMORY", "TRAINING_FAILED",
    "ARTIFACT_WRITE_FAILED", "INVALID_ARTIFACT", "PROGRESS_CALLBACK_FAILED",
]
FailureStage = Literal[
    "preflight", "model_loading", "data_preparation", "training", "saving",
    "callback", "reloading",
]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True, frozen=True)


def _absolute_path(value: Path) -> Path:
    if not value.is_absolute() or ".." in value.parts:
        raise ValueError("Expected an absolute path without parent traversal")
    return value


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value):
            raise ValueError("Expected an RFC 3339 timestamp with timezone")
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone")
    return value.astimezone(timezone.utc)


class RuntimeOptions(ContractModel):
    """Internal execution choices; these are not public LoRA form fields."""

    precision: Literal["bf16", "fp32"] = "bf16"
    max_steps: PositiveInt | None = None
    local_files_only: bool = Field(default=True, strict=True)


class TrainRequest(ContractModel):
    contract_version: Literal["1.0.0"] = TRAINING_CONTRACT_VERSION
    task_id: UUID
    dataset_path: Path
    output_dir: Path
    base_model: BaseModelId
    config: TrainingConfig
    model_revision: Revision
    cache_dir: Path
    log_path: Path
    validation_dataset_path: Path | None = None
    dataset_manifest_path: Path | None = None
    runtime: RuntimeOptions = Field(default_factory=RuntimeOptions)

    @field_validator(
        "dataset_path", "output_dir", "cache_dir", "log_path",
        "validation_dataset_path", "dataset_manifest_path",
    )
    @classmethod
    def absolute_paths(cls, value: Path | None) -> Path | None:
        return None if value is None else _absolute_path(value)

    @model_validator(mode="after")
    def isolated_paths(self) -> "TrainRequest":
        if self.output_dir.name != str(self.task_id):
            raise ValueError("output_dir basename must equal task_id")
        if self.log_path.name != f"{self.task_id}.log":
            raise ValueError("log_path basename must equal task_id.log")
        if self.dataset_path == self.validation_dataset_path:
            raise ValueError("Training and validation paths must differ")
        for path in (self.dataset_path, self.validation_dataset_path,
                     self.dataset_manifest_path, self.cache_dir, self.log_path):
            if path is not None and (path == self.output_dir or self.output_dir in path.parents):
                raise ValueError("Inputs, cache and log must be outside output_dir")
        if self.cache_dir in self.output_dir.parents:
            raise ValueError("output_dir must be outside model cache")
        return self


class TrainingProgress(ContractModel):
    contract_version: Literal["1.0.0"] = TRAINING_CONTRACT_VERSION
    kind: Literal["train", "eval"] = "train"
    step: PositiveInt
    total_steps: PositiveInt
    loss: NonNegativeFloat
    learning_rate: NonNegativeFloat
    epoch: NonNegativeFloat
    recorded_at: datetime

    _normalize_time = field_validator("recorded_at", mode="before")(_utc)

    @model_validator(mode="after")
    def bounded_step(self) -> "TrainingProgress":
        if self.step > self.total_steps:
            raise ValueError("step exceeds total_steps")
        return self


class TrainResult(ContractModel):
    contract_version: Literal["1.0.0"] = TRAINING_CONTRACT_VERSION
    adapter_dir: Path
    metrics_path: Path
    tokenizer_dir: Path
    config_path: Path
    manifest_path: Path

    @field_validator("adapter_dir", "metrics_path", "tokenizer_dir", "config_path", "manifest_path")
    @classmethod
    def absolute_paths(cls, value: Path) -> Path:
        return _absolute_path(value)

    @model_validator(mode="after")
    def same_task_directory(self) -> "TrainResult":
        root = self.manifest_path.parent
        expected = {"adapter_dir": "adapter", "metrics_path": "metrics.jsonl",
                    "tokenizer_dir": "tokenizer", "config_path": "training_config.json",
                    "manifest_path": "manifest.json"}
        if any(getattr(self, field) != root / name for field, name in expected.items()):
            raise ValueError("Result paths must use one task directory and canonical names")
        return self


class DatasetSummary(ContractModel):
    sha256: Sha256
    size_bytes: PositiveInt
    row_count: PositiveInt
    review_status: ReviewStatus = "unknown"
    build_id: Annotated[str, Field(pattern=r"^[0-9a-f]{16}$")] | None = None


class TrainingSnapshot(ContractModel):
    contract_version: Literal["1.0.0"] = TRAINING_CONTRACT_VERSION
    task_id: UUID
    base_model: BaseModelId
    model_revision: Revision
    config: TrainingConfig
    runtime: RuntimeOptions


class RunEnvironment(ContractModel):
    code_commit: Revision
    working_tree_dirty: bool = Field(strict=True)
    uv_lock_sha256: Sha256
    python_version: Annotated[str, Field(min_length=1, max_length=64)]
    cuda_runtime: Annotated[str, Field(min_length=1, max_length=64)]
    gpu_name: Annotated[str, Field(min_length=1, max_length=128)]
    packages: dict[str, Annotated[str, Field(min_length=1, max_length=64)]]

    @field_validator("packages")
    @classmethod
    def required_versions(cls, value: dict[str, str]) -> dict[str, str]:
        required = {"torch", "transformers", "datasets", "peft", "trl", "accelerate"}
        if not required.issubset(value) or any(not version.strip() for version in value.values()):
            raise ValueError("Record actual versions of all six training packages")
        return value


class TrainingSummary(ContractModel):
    completed_steps: PositiveInt
    total_steps: PositiveInt
    elapsed_seconds: NonNegativeFloat
    peak_memory_allocated_bytes: NonNegativeInt
    trainable_parameters: PositiveInt
    total_parameters: PositiveInt
    final_loss: NonNegativeFloat
    eval_loss: NonNegativeFloat | None = None

    @model_validator(mode="after")
    def successful_lora_run(self) -> "TrainingSummary":
        if self.completed_steps != self.total_steps:
            raise ValueError("Successful run must reach its planned optimizer steps")
        if self.trainable_parameters >= self.total_parameters:
            raise ValueError("LoRA must leave base parameters frozen")
        return self


class ArtifactFile(ContractModel):
    path: str
    sha256: Sha256
    size_bytes: PositiveInt

    @field_validator("path")
    @classmethod
    def relative_artifact_key(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (not value or path.is_absolute() or ".." in path.parts or ":" in value
                or "\\" in value or not value.isprintable() or path.as_posix() != value):
            raise ValueError("Expected a canonical relative POSIX artifact key")
        if not (value.startswith("adapter/") or value.startswith("tokenizer/")
                or value in {"metrics.jsonl", "training_config.json"}):
            raise ValueError("Unexpected deliverable artifact")
        return value


class TrainingManifest(TrainingSnapshot):
    status: Literal["completed"] = "completed"
    tokenizer_revision: Revision
    chat_template_sha256: Sha256
    train_dataset: DatasetSummary
    validation_dataset: DatasetSummary | None = None
    environment: RunEnvironment
    started_at: datetime
    finished_at: datetime
    summary: TrainingSummary
    artifacts: list[ArtifactFile] = Field(min_length=5, max_length=256)

    _normalize_times = field_validator("started_at", "finished_at", mode="before")(_utc)

    @model_validator(mode="after")
    def consistent_success(self) -> "TrainingManifest":
        if self.tokenizer_revision != self.model_revision:
            raise ValueError("Tokenizer revision must match the base model")
        if self.finished_at < self.started_at:
            raise ValueError("finished_at precedes started_at")
        if self.validation_dataset is None and self.summary.eval_loss is not None:
            raise ValueError("eval_loss requires a validation dataset")
        if self.runtime.max_steps is not None and self.summary.total_steps != self.runtime.max_steps:
            raise ValueError("Explicit max_steps must match planned optimizer steps")
        keys = [artifact.path for artifact in self.artifacts]
        required = {"adapter/adapter_model.safetensors", "adapter/adapter_config.json",
                    "tokenizer/tokenizer_config.json", "metrics.jsonl", "training_config.json"}
        if len(set(keys)) != len(keys) or not required.issubset(keys):
            raise ValueError("Artifact inventory must be unique and include required files")
        return self


class TrainingFailure(ContractModel):
    contract_version: Literal["1.0.0"] = TRAINING_CONTRACT_VERSION
    task_id: UUID | None = None
    code: FailureCode
    stage: FailureStage
    message: Annotated[str, Field(min_length=1, max_length=1000)]


class TrainingError(Exception):
    """Future execution code raises this with a safe, structured failure."""

    def __init__(self, failure: TrainingFailure):
        self.failure = failure
        super().__init__(failure.message)
