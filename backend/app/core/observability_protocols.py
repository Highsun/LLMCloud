"""Detached completed-artifact contract; M4-03 will implement its SQL projection."""

from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator, model_validator

from backend.app.core.observability_contract import OBSERVABILITY_CONTRACT_VERSION
from backend.app.core.task_protocols import TaskExecutionSpec
from trainer.contracts import ContractModel, Sha256, TrainingSummary


class CompletedArtifactSpec(ContractModel):
    """No filesystem/authorization/SQL checks; the repository must gate COMPLETED."""

    model_config = ConfigDict(revalidate_instances="always")
    contract_version: Literal["1.0.0"] = OBSERVABILITY_CONTRACT_VERSION
    spec: TaskExecutionSpec
    output_key: str = Field(strict=True)
    manifest_sha256: Sha256
    training_summary: TrainingSummary

    @field_validator("spec", "training_summary", mode="before")
    @classmethod
    def detached_snapshots(cls, value):
        return value.model_dump() if isinstance(value, ContractModel) else value

    @model_validator(mode="after")
    def controlled_output(self):
        if self.output_key != f"outputs/{self.spec.task_id}":
            raise ValueError("Output key must match the task UUID")
        if (self.spec.runtime.max_steps is not None
                and self.training_summary.total_steps != self.spec.runtime.max_steps):
            raise ValueError("Completion summary differs from the fixed runtime step limit")
        return self


class CompletedArtifactNotFound(LookupError):
    """M4-03 maps this to 404/TASK_NOT_FOUND without driver or path text."""


class CompletedArtifactNotReady(ValueError):
    """M4-03 maps any existing non-COMPLETED task to 409/ARTIFACT_NOT_READY."""


@runtime_checkable
class CompletedArtifactRepository(Protocol):
    def get_completed_artifact(self, task_id: UUID) -> CompletedArtifactSpec:
        """One short read; missing/not-ready errors above, corruption -> TaskStoreError.

        This is an additional interface, not a change to the five Worker methods.
        No artifact files are opened here. M4-03 adds the concrete SQL method.
        """
        ...
