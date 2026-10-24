"""CPU-only interfaces for independently implemented SQL, Publisher and Worker."""

from collections.abc import Callable
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import Field, UUID4, field_validator, model_validator

from backend.app.core.task_contract import ExecutionOutcome, PublishOutcome, TASK_CONTRACT_VERSION, TaskStatus
from trainer.contracts import (
    BaseModelId, ContractModel, PositiveInt, Revision, RuntimeOptions, Sha256,
    TrainRequest, TrainResult, TrainingFailure, TrainingProgress, TrainingSummary,
)
from trainer.lora_config import TrainingConfig


class TaskExecutionSpec(ContractModel):
    """Detached claim snapshot. Key validation performs no filesystem checks."""

    contract_version: Literal["1.0.0"] = TASK_CONTRACT_VERSION
    task_id: UUID4
    dataset_id: UUID4
    dataset_key: str
    dataset_sha256: Sha256
    dataset_size_bytes: PositiveInt
    dataset_row_count: PositiveInt
    base_model: BaseModelId
    model_revision: Revision
    config: TrainingConfig
    runtime: RuntimeOptions = Field(default_factory=RuntimeOptions)

    @field_validator("config", mode="before")
    @classmethod
    def detached_config(cls, value):
        # Revalidate mutated model instances and detach their mutable nested list.
        return TrainingConfig.model_validate(value.model_dump() if isinstance(value, TrainingConfig) else value)

    @model_validator(mode="after")
    def controlled_input(self):
        if self.dataset_key != f"datasets/{self.dataset_id}/train.jsonl":
            raise ValueError("Dataset key must match the server-owned dataset UUID")
        if not self.runtime.local_files_only:
            raise ValueError("Service tasks must use the prepared offline model cache")
        return self


class TaskStoreError(Exception):
    """SQL implementations hide driver text and preserve any valid artifacts."""

    def __init__(self):
        super().__init__("任务存储暂时不可用。")


@runtime_checkable
class TaskRepository(Protocol):
    def get_status(self, task_id: UUID) -> TaskStatus | None:
        """Fresh committed state after an uncertain write; None means missing."""
        ...

    def claim(self, task_id: UUID, claim_token: UUID, worker_id: str) -> TaskExecutionSpec | None:
        """CAS PENDING/QUEUED -> RUNNING; None skips, storage errors raise."""
        ...

    def record_progress(self, task_id: UUID, claim_token: UUID, event: TrainingProgress) -> bool:
        """Token-guarded RUNNING update. Eval does not advance steps; never writes metrics."""
        ...

    def complete(self, task_id: UUID, claim_token: UUID, output_key: str,
                 manifest_sha256: Sha256, summary: TrainingSummary) -> bool:
        """Token CAS after auditing; output_key must equal outputs/{task_id}."""
        ...

    def fail(self, task_id: UUID, claim_token: UUID, failure: TrainingFailure) -> bool:
        """Token CAS; failure.task_id must be absent or equal task_id."""
        ...


@runtime_checkable
class Publisher(Protocol):
    def publish(self, task_id: UUID, celery_task_id: UUID) -> PublishOutcome:
        """Bounded, single publish attempt. Unknown must never cause auto-resend."""
        ...


class ExecutionSettings(Protocol):
    """Structural view of backend Settings; this module never imports Settings."""

    @property
    def data_dir(self) -> Path: ...

    @property
    def log_dir(self) -> Path: ...


class TrainFunction(Protocol):
    def __call__(self, request: TrainRequest,
                 on_progress: Callable[[TrainingProgress], None] | None = None) -> TrainResult: ...


class TaskExecutor(Protocol):
    def __call__(self, task_id: UUID, repository: TaskRepository,
                 settings: ExecutionSettings, train_fn: TrainFunction) -> ExecutionOutcome: ...
