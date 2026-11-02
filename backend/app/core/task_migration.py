"""Explicit SQLite task migration, with trusted snapshots and atomic replacement."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from pydantic import Field, UUID4
from sqlalchemy.dialects.sqlite import dialect
from sqlalchemy.schema import CreateIndex, CreateTable

from backend.app.core.task_contract import TaskErrorCode, TaskStatus
from backend.app.models.entities import TrainingTask
from backend.app.services.dataset_paths import dataset_key, resolve_dataset_path
from backend.app.services.task_records import identifier, task_detail
from trainer.artifacts import sha256, verify_training_artifacts
from trainer.contracts import ContractModel, Revision, RuntimeOptions
from trainer.dataset import scan_dataset
from trainer.lora_config import TrainingConfig

STAGE = "training_tasks_m3_new"
JSON_FIELDS = {"training_config", "runtime_options", "training_summary"}
LEGACY_DDL = """CREATE TABLE training_tasks (
 id VARCHAR(36) NOT NULL, dataset_id VARCHAR(36) NOT NULL,
 base_model VARCHAR(255) NOT NULL, status VARCHAR(9) NOT NULL,
 training_config JSON NOT NULL, celery_task_id VARCHAR(255),
 progress FLOAT NOT NULL, current_step INTEGER NOT NULL, total_steps INTEGER NOT NULL,
 output_path TEXT, error_message TEXT, created_at DATETIME NOT NULL,
 started_at DATETIME, finished_at DATETIME,
 PRIMARY KEY (id), FOREIGN KEY(dataset_id) REFERENCES datasets (id),
 CONSTRAINT taskstatus CHECK (status IN ('PENDING', 'QUEUED', 'RUNNING', 'COMPLETED', 'FAILED'))
)"""


class TaskSchemaMigrationRequired(RuntimeError):
    pass


class LegacySnapshot(ContractModel):
    model_revision: Revision
    runtime: RuntimeOptions
    celery_task_id: UUID4 | None = None
    interrupt_running: bool = Field(default=False, strict=True)
    failure_code: TaskErrorCode | None = None
    failure_message: str | None = Field(default=None, min_length=1, max_length=1000)


@dataclass
class TaskMigrationReport:
    state: str
    rows: int = 0
    issues: list[dict] = field(default_factory=list)
    backup_path: str | None = None

    def to_dict(self):
        return asdict(self)


def _normalize(sql):
    # Ignore formatting/identifier quoting, never whitespace inside SQL literals.
    parts = re.split(r"('(?:''|[^'])*')", sql)
    return "".join(part if index % 2 else re.sub(r'\s+|"', "", part)
                   for index, part in enumerate(parts)).rstrip(";")


def _current_ddl():
    return str(CreateTable(TrainingTask.__table__).compile(dialect=dialect()))


def _state(connection):
    row = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='training_tasks'").fetchone()
    if row is None:
        return "not_initialized"
    sql = _normalize(row[0])
    if sql == _normalize(_current_ddl()):
        indexes = {row[1]: row for row in connection.execute("PRAGMA index_list(training_tasks)")}
        for index in TrainingTask.__table__.indexes:
            existing = indexes.get(index.name)
            if existing is None or bool(existing[2]) != index.unique or existing[4]:
                return "unsupported_schema"
            if [row[2] for row in connection.execute(f'PRAGMA index_info("{index.name}")')] != [c.name for c in index.columns]:
                return "unsupported_schema"
        return "current"
    if sql != _normalize(LEGACY_DDL):
        return "unsupported_schema"
    if connection.execute("SELECT 1 FROM sqlite_master WHERE tbl_name='training_tasks' AND type='trigger'").fetchone():
        return "unsupported_schema"
    if any(re.search(r"\btraining_tasks\b", row[0] or "", re.I)
           for row in connection.execute("SELECT sql FROM sqlite_master WHERE type='view'")):
        return "unsupported_schema"
    return "legacy"


def require_task_schema(engine):
    if engine.dialect.name != "sqlite":
        raise TaskSchemaMigrationRequired("当前任务存储只支持 SQLite。")
    with engine.connect() as connection:
        state = _state(connection.connection.driver_connection)
    if state not in ("current", "not_initialized"):
        raise TaskSchemaMigrationRequired(
            "任务表需要显式迁移：uv run --locked python scripts/migrate_tasks.py --check；确认报告后使用 --apply。")


def _decode(row):
    result = dict(row)
    for name in JSON_FIELDS & result.keys():
        if isinstance(result[name], str):
            result[name] = json.loads(result[name])
    return result


def _legacy_row(connection, old, snapshot, data_dir, now):
    row = _decode(old)
    task_id, dataset_id = identifier(row["id"]), identifier(row["dataset_id"])
    dataset = connection.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
    if dataset is None or "sha256" not in dataset.keys():
        raise ValueError("dataset_metadata_required")
    key = dataset_key(dataset_id)
    if dataset["storage_path"] != key:
        raise ValueError("dataset_key_mismatch")
    path = resolve_dataset_path(data_dir, key)
    if not path.is_file():
        raise ValueError("dataset_file_unavailable")
    stats = scan_dataset(path)
    if (stats.sha256, stats.size_bytes, stats.row_count) != (dataset["sha256"], dataset["size_bytes"], dataset["row_count"]):
        raise ValueError("dataset_statistics_mismatch")
    if snapshot is None:
        raise ValueError("trusted_snapshot_required")
    snapshot = LegacySnapshot.model_validate(snapshot)
    if row["celery_task_id"] is None and snapshot.celery_task_id is None:
        raise ValueError("celery_task_id_required")
    celery_id = identifier(snapshot.celery_task_id or row["celery_task_id"])
    if row["celery_task_id"] is not None and identifier(row["celery_task_id"]) != celery_id:
        raise ValueError("celery_task_id_conflict")
    row.update(model_revision=snapshot.model_revision, dataset_key=key, dataset_sha256=stats.sha256,
        dataset_size_bytes=stats.size_bytes, dataset_row_count=stats.row_count,
        training_config=TrainingConfig.model_validate(row["training_config"]).model_dump(mode="json"),
        runtime_options=snapshot.runtime.model_dump(mode="json"), celery_task_id=celery_id,
        claim_token=None, worker_id=None, error_code=None, idempotency_key=None, request_sha256=None,
        manifest_sha256=None, training_summary=None)
    output = row["output_path"]
    if output is not None:
        supplied = Path(output)
        normalized = supplied.relative_to(data_dir).as_posix() if supplied.is_absolute() else output
        if normalized != f"outputs/{task_id}":
            raise ValueError("legacy_output_key_mismatch")
    if row["status"] == TaskStatus.RUNNING:
        if not snapshot.interrupt_running:
            raise ValueError("running_disposition_required")
        row.update(status=TaskStatus.FAILED, error_code="WORKER_INTERRUPTED",
            error_message="旧任务已由离线迁移显式结束，未自动重新训练。", finished_at=now)
    elif snapshot.interrupt_running:
        raise ValueError("unexpected_running_disposition")
    elif row["status"] == TaskStatus.FAILED:
        if snapshot.failure_code is None or snapshot.failure_message is None:
            raise ValueError("safe_failure_mapping_required")
        row.update(error_code=snapshot.failure_code, error_message=snapshot.failure_message)
    elif row["status"] == TaskStatus.COMPLETED:
        verified = verify_training_artifacts(data_dir / "outputs" / task_id,
            outputs_root=data_dir / "outputs", expected_task_id=task_id, expected_revision=snapshot.model_revision)
        manifest = verified.manifest
        if (manifest.config.model_dump(mode="json") != row["training_config"] or manifest.runtime != snapshot.runtime
                or (manifest.train_dataset.sha256, manifest.train_dataset.size_bytes, manifest.train_dataset.row_count)
                != (stats.sha256, stats.size_bytes, stats.row_count)):
            raise ValueError("completed_artifact_snapshot_mismatch")
        row.update(output_path=f"outputs/{task_id}", manifest_sha256=sha256(verified.result.manifest_path),
                   training_summary=manifest.summary.model_dump(mode="json"))
    if row["status"] != TaskStatus.COMPLETED:
        row["output_path"] = None  # Partial files remain untouched and the backup retains the old key.
    task_detail(row)
    return row


def _plan(connection, data_dir, snapshots, now):
    state = _state(connection)
    if state not in ("legacy", "current"):
        return TaskMigrationReport(state), []
    rows = list(connection.execute("SELECT * FROM training_tasks ORDER BY id"))
    report = TaskMigrationReport("ready" if state == "legacy" else "current", rows=len(rows))
    plans = []
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name=?", (STAGE,)).fetchone():
        report.issues.append({"code": "staging_object_exists"})
    for unknown in snapshots.keys() - {row["id"] for row in rows}:
        report.issues.append({"task_id": unknown, "code": "unknown_snapshot_mapping"})
    for row in rows:
        try:
            if state == "current":
                task_detail(_decode(row))
            else:
                plans.append(_legacy_row(connection, row, snapshots.get(row["id"]), data_dir, now))
        except Exception as error:
            # Never print record contents, sample text or raw storage/library errors.
            allowed = {"dataset_metadata_required", "dataset_key_mismatch", "dataset_file_unavailable",
                "dataset_statistics_mismatch", "trusted_snapshot_required", "celery_task_id_required",
                "celery_task_id_conflict", "legacy_output_key_mismatch", "running_disposition_required",
                "unexpected_running_disposition", "safe_failure_mapping_required", "completed_artifact_snapshot_mismatch"}
            code = str(error) if isinstance(error, ValueError) and str(error) in allowed else "invalid_task_or_artifacts"
            report.issues.append({"task_id": row["id"], "code": code})
    if list(connection.execute("PRAGMA foreign_key_check")):
        report.issues.append({"code": "existing_foreign_key_violation"})
    if report.issues:
        report.state = "blocked"
    return report, plans


def _replace_table(connection, plans):
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name=?", (STAGE,)).fetchone():
        raise RuntimeError("Migration staging table already exists")
    indexes = list(connection.execute("SELECT name,sql FROM sqlite_master WHERE tbl_name='training_tasks' AND type='index' AND sql IS NOT NULL"))
    ddl = _current_ddl().replace("CREATE TABLE training_tasks", f"CREATE TABLE {STAGE}", 1)
    connection.execute(ddl)
    columns = [column.name for column in TrainingTask.__table__.columns]
    names = ",".join(f'"{name}"' for name in columns)
    parameters = ",".join("?" for _ in columns)
    values = []
    for row in plans:
        encoded = []
        for name in columns:
            value = row[name]
            if name in JSON_FIELDS and value is not None:
                value = json.dumps(value, ensure_ascii=False, allow_nan=False)
            if name in {"created_at", "started_at", "finished_at"} and value is not None:
                value = datetime.fromisoformat(value) if isinstance(value, str) else value
                if value.tzinfo is not None:
                    value = value.astimezone(timezone.utc).replace(tzinfo=None)
                value = value.strftime("%Y-%m-%d %H:%M:%S.%f")
            encoded.append(value)
        values.append(tuple(encoded))
    connection.executemany(f"INSERT INTO {STAGE} ({names}) VALUES ({parameters})", values)
    connection.execute("DROP TABLE training_tasks")
    connection.execute(f"ALTER TABLE {STAGE} RENAME TO training_tasks")
    standard = {index.name for index in TrainingTask.__table__.indexes}
    for index in TrainingTask.__table__.indexes:
        connection.execute(str(CreateIndex(index).compile(dialect=dialect())))
    for name, sql in indexes:
        if name not in standard:
            connection.execute(sql)
    if list(connection.execute("PRAGMA foreign_key_check")):
        raise RuntimeError("Foreign key validation failed")


def migrate_tasks(engine, data_dir, *, apply=False, snapshots=None):
    if engine.dialect.name != "sqlite":
        raise ValueError("This migration only supports SQLite")
    database = engine.url.database
    if not database or database == ":memory:" or not Path(database).is_file():
        return TaskMigrationReport("not_initialized")
    mappings = {identifier(key): LegacySnapshot.model_validate(value).model_dump()
                for key, value in (snapshots or {}).items()}
    data_dir = Path(data_dir).resolve()
    now = datetime.now(timezone.utc)
    mode = "rw" if apply else "ro"
    connection = sqlite3.connect(f"{Path(database).resolve().as_uri()}?mode={mode}", uri=True, isolation_level=None, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN")
        report, before = _plan(connection, data_dir, mappings, now)
        connection.rollback()
        if not apply or report.state != "ready":
            return report
        backup_dir = data_dir / "backups"
        if backup_dir.is_symlink():
            raise ValueError("Backup directory must not be linked")
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"tasks-before-m3-{uuid4()}.sqlite3"
        descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        with sqlite3.connect(backup) as destination:
            connection.backup(destination)
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("BEGIN IMMEDIATE")
        report, plans = _plan(connection, data_dir, mappings, now)
        report.backup_path = str(backup)
        if report.state != "ready" or plans != before:
            connection.rollback()
            if report.state == "ready":
                report.state = "blocked"
                report.issues.append({"code": "database_changed_before_apply"})
            return report
        _replace_table(connection, plans)
        connection.commit()
        report.state = "applied"
        return report
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
