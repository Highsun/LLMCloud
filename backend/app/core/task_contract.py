"""CPU-only task vocabulary; no ORM, transport, settings or GPU imports."""

from enum import StrEnum
from typing import Literal

from trainer.contracts import FailureCode

TASK_CONTRACT_VERSION = "1.0.0"
DEFAULT_MODEL_REVISION = "7ae557604adf67be50417f59c2c2f167def9a775"
MAX_TASK_BODY_BYTES = 64 * 1024
DEFAULT_TASK_PAGE_SIZE = 20
MAX_TASK_PAGE_SIZE = 100


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# Trainer failures retain their original codes. Recovery/dispatch belong to tasks.
TaskErrorCode = FailureCode | Literal[
    "DISPATCH_FAILED", "DISPATCH_UNCERTAIN", "WORKER_INTERRUPTED", "TASK_ABANDONED",
]


class PublishOutcome(StrEnum):
    ACCEPTED = "accepted"
    NOT_SENT = "not_sent"
    UNKNOWN = "unknown"


class ExecutionOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    OWNERSHIP_LOST = "ownership_lost"
    RECONCILIATION_REQUIRED = "reconciliation_required"
