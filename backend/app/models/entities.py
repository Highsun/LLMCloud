"""Metadata schema; existing tables are upgraded only by explicit migrations."""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Enum, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base
from backend.app.core.task_contract import TaskStatus


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer)
    row_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TrainingTask(Base):
    __tablename__ = "training_tasks"
    __table_args__ = (
        CheckConstraint("length(model_revision)=40 AND length(dataset_sha256)=64", name="task_snapshot_hashes"),
        CheckConstraint("dataset_size_bytes>0 AND dataset_row_count>0", name="task_dataset_statistics"),
        CheckConstraint("dataset_key='datasets/' || dataset_id || '/train.jsonl'", name="task_dataset_key"),
        CheckConstraint("current_step>=0 AND total_steps>=0 AND current_step<=total_steps AND progress>=0 AND progress<=1", name="task_steps"),
        CheckConstraint("(total_steps=0 AND current_step=0 AND progress=0) OR (total_steps>0 AND abs(progress-1.0*current_step/total_steps)<0.000000001)", name="task_progress"),
        CheckConstraint("(claim_token IS NULL AND worker_id IS NULL) OR (claim_token IS NOT NULL AND length(claim_token)=36 AND worker_id IS NOT NULL AND length(worker_id) BETWEEN 1 AND 255)", name="task_claim_pair"),
        CheckConstraint("(idempotency_key IS NULL AND request_sha256 IS NULL) OR (idempotency_key IS NOT NULL AND request_sha256 IS NOT NULL AND length(idempotency_key)=36 AND length(request_sha256)=64)", name="task_request_pair"),
        CheckConstraint("(error_code IS NULL AND error_message IS NULL) OR (error_code IS NOT NULL AND error_message IS NOT NULL AND length(error_message) BETWEEN 1 AND 1000)", name="task_error_pair"),
        CheckConstraint("started_at IS NULL OR started_at>=created_at", name="task_start_time"),
        CheckConstraint("finished_at IS NULL OR finished_at>=coalesce(started_at,created_at)", name="task_finish_time"),
        CheckConstraint("status NOT IN ('PENDING','QUEUED') OR (started_at IS NULL AND finished_at IS NULL AND claim_token IS NULL AND total_steps=0)", name="task_waiting"),
        CheckConstraint("status!='RUNNING' OR (started_at IS NOT NULL AND finished_at IS NULL AND claim_token IS NOT NULL)", name="task_running"),
        CheckConstraint("status NOT IN ('COMPLETED','FAILED') OR finished_at IS NOT NULL", name="task_terminal"),
        CheckConstraint("status!='FAILED' OR error_code IS NOT NULL", name="task_failed"),
        CheckConstraint("status!='COMPLETED' OR (started_at IS NOT NULL AND total_steps>0 AND current_step=total_steps AND progress=1 AND error_code IS NULL AND output_path IS NOT NULL AND output_path='outputs/' || id AND manifest_sha256 IS NOT NULL AND length(manifest_sha256)=64 AND training_summary IS NOT NULL)", name="task_completed"),
        CheckConstraint("status='COMPLETED' OR (output_path IS NULL AND manifest_sha256 IS NULL AND training_summary IS NULL)", name="task_unpublished"),
        Index("uq_training_tasks_idempotency_key", "idempotency_key", unique=True),
        Index("ix_training_tasks_created_id", "created_at", "id"),
        Index("ix_training_tasks_status_created_id", "status", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    base_model: Mapped[str] = mapped_column(String(255))
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, native_enum=False, create_constraint=True),
        default=TaskStatus.PENDING, index=True,
    )
    training_config: Mapped[dict[str, Any]] = mapped_column(JSON)
    model_revision: Mapped[str] = mapped_column(String(40))
    dataset_key: Mapped[str] = mapped_column(Text)
    dataset_sha256: Mapped[str] = mapped_column(String(64))
    dataset_size_bytes: Mapped[int] = mapped_column(Integer)
    dataset_row_count: Mapped[int] = mapped_column(Integer)
    runtime_options: Mapped[dict[str, Any]] = mapped_column(JSON)
    claim_token: Mapped[str | None] = mapped_column(String(36))
    worker_id: Mapped[str | None] = mapped_column(String(255))
    error_code: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(36))
    request_sha256: Mapped[str | None] = mapped_column(String(64))
    manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    training_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    celery_task_id: Mapped[str] = mapped_column(String(255))
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    total_steps: Mapped[int] = mapped_column(Integer, default=0)
    output_path: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
