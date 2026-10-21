"""Explicit SQLite M0 -> M1 migration. No automatic guessing or destructive reset."""

from dataclasses import asdict, dataclass, field
from datetime import datetime
import os
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from sqlalchemy import MetaData, inspect
from sqlalchemy.dialects.sqlite import dialect
from sqlalchemy.schema import CreateTable
from sqlalchemy.engine import Engine
from pydantic import ValidationError

from backend.app.models.dataset_schemas import DatasetDetail
from backend.app.models.entities import Dataset, User
from backend.app.services.dataset_paths import dataset_key, resolve_dataset_path, sanitize_filename
from trainer.dataset import DatasetValidationError, scan_dataset

LEGACY_COLUMNS = {"id", "user_id", "name", "storage_path", "size_bytes", "row_count", "created_at"}
M1_COLUMNS = LEGACY_COLUMNS | {"original_filename", "sha256"}


class DatasetSchemaMigrationRequired(RuntimeError):
    pass


def require_dataset_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    if inspector.has_table("datasets"):
        columns = {column["name"]: column for column in inspector.get_columns("datasets")}
        if not M1_COLUMNS.issubset(columns) or any(columns[name]["nullable"] for name in ("original_filename", "sha256") if name in columns):
            raise DatasetSchemaMigrationRequired(
                "数据集表需要显式迁移：uv run --locked python scripts/migrate_datasets.py --check；确认报告后使用 --apply。"
            )


@dataclass
class MigrationReport:
    state: str
    rows: int = 0
    issues: list[dict] = field(default_factory=list)
    backup_path: str | None = None

    def to_dict(self):
        return asdict(self)


def _schema_state(connection) -> str:
    columns = {row[1]: row for row in connection.execute("PRAGMA table_xinfo(datasets)")}
    if not columns:
        return "not_initialized"
    if set(columns) == M1_COLUMNS and all(columns[name][3] for name in ("original_filename", "sha256")):
        return "current"
    if set(columns) != LEGACY_COLUMNS:
        return "unsupported_schema"
    ddl = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='datasets'").fetchone()[0]
    if re.search(r"\b(CHECK|UNIQUE|GENERATED|COLLATE|STRICT)\b|WITHOUT\s+ROWID", ddl, re.I):
        return "unsupported_schema"
    expected_types = {"id": "VARCHAR(36)", "user_id": "VARCHAR(36)", "name": "VARCHAR(255)", "storage_path": "TEXT", "size_bytes": "INTEGER", "row_count": "INTEGER", "created_at": "DATETIME"}
    if any(columns[name][2].upper() != expected for name, expected in expected_types.items()):
        return "unsupported_schema"
    if any(columns[name][5] != (1 if name == 'id' else 0) or columns[name][4] is not None
           or bool(columns[name][3]) != (name != 'user_id') for name in LEGACY_COLUMNS):
        return "unsupported_schema"
    foreign_keys = list(connection.execute("PRAGMA foreign_key_list(datasets)"))
    if len(foreign_keys) != 1 or tuple(foreign_keys[0][2:7]) != ("users", "user_id", "id", "NO ACTION", "NO ACTION"):
        return "unsupported_schema"
    views = connection.execute("SELECT sql FROM sqlite_master WHERE type='view'")
    if any(re.search(r"\bdatasets\b", row[0] or "", re.I) for row in views):
        return "unsupported_schema"
    return "legacy"


def _plan(connection, data_dir: Path, filenames: dict) -> tuple[MigrationReport, list[dict]]:
    state = _schema_state(connection)
    if state != "legacy":
        count = connection.execute('SELECT count(*) FROM datasets').fetchone()[0] if state == 'current' else 0
        return MigrationReport(state, rows=count), []
    rows = list(connection.execute("SELECT * FROM datasets"))
    report = MigrationReport("ready", rows=len(rows))
    plans = []
    identifiers = {row["id"] for row in rows}
    for identifier in filenames.keys() - identifiers:
        report.issues.append({"dataset_id": identifier, "code": "unknown_filename_mapping"})
    for row in rows:
        identifier = row["id"]
        try:
            key = dataset_key(identifier)
            legacy_path = Path(row["storage_path"])
            normalized = legacy_path.relative_to(data_dir).as_posix() if legacy_path.is_absolute() else row["storage_path"]
            if normalized != key:
                raise ValueError()
            path = resolve_dataset_path(data_dir, key)
        except (ValueError, TypeError):
            report.issues.append({"dataset_id": identifier, "code": "storage_path_needs_repair"})
            continue
        if identifier not in filenames:
            report.issues.append({"dataset_id": identifier, "code": "original_filename_required"})
            continue
        try:
            original = sanitize_filename(filenames[identifier])
        except ValueError:
            report.issues.append({"dataset_id": identifier, "code": "invalid_original_filename"})
            continue
        try:
            stats = scan_dataset(path)
        except OSError:
            report.issues.append({"dataset_id": identifier, "code": "source_file_unavailable"})
            continue
        except DatasetValidationError as error:
            report.issues.append({"dataset_id": identifier, "code": error.code, "line": error.line})
            continue
        if stats.size_bytes != row['size_bytes'] or stats.row_count != row['row_count']:
            report.issues.append({"dataset_id": identifier, "code": "legacy_statistics_mismatch"})
            continue
        try:
            DatasetDetail(id=identifier, name=row['name'], format='alpaca_jsonl', original_filename=original,
                          size_bytes=stats.size_bytes, row_count=stats.row_count, sha256=stats.sha256,
                          created_at=datetime.fromisoformat(row['created_at']))
        except (ValidationError, ValueError, TypeError):
            report.issues.append({"dataset_id": identifier, "code": "invalid_legacy_metadata"})
            continue
        plans.append({**dict(row), "storage_path": key, "original_filename": original,
                      "sha256": stats.sha256, "size_bytes": stats.size_bytes, "row_count": stats.row_count})
    if list(connection.execute("PRAGMA foreign_key_check")):
        report.issues.append({"code": "existing_foreign_key_violation"})
    if report.issues:
        report.state = "blocked"
    return report, plans


def _replace_table(connection, plans):
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='datasets_m1_new'").fetchone():
        raise RuntimeError("Migration staging table already exists")
    objects = [row[0] for row in connection.execute("SELECT sql FROM sqlite_master WHERE tbl_name='datasets' AND type IN ('index','trigger') AND sql IS NOT NULL")]
    metadata = MetaData()
    User.__table__.to_metadata(metadata)
    replacement = Dataset.__table__.to_metadata(metadata, name="datasets_m1_new")
    connection.execute(str(CreateTable(replacement).compile(dialect=dialect())))
    columns = [column.name for column in Dataset.__table__.columns]
    names = ", ".join(f'"{name}"' for name in columns)
    parameters = ", ".join("?" for _ in columns)
    connection.executemany(f"INSERT INTO datasets_m1_new ({names}) VALUES ({parameters})", [tuple(row[name] for name in columns) for row in plans])
    connection.execute("DROP TABLE datasets")
    connection.execute("ALTER TABLE datasets_m1_new RENAME TO datasets")
    for statement in objects:
        connection.execute(statement)
    if list(connection.execute("PRAGMA foreign_key_check")):
        raise RuntimeError("Foreign key validation failed")


def migrate_datasets(engine: Engine, data_dir: Path, *, apply: bool = False, filenames: dict[str, str] | None = None) -> MigrationReport:
    """Supports the known M0 schema only. Stop API/Workers before --apply."""
    if engine.dialect.name != "sqlite":
        raise ValueError("This migration only supports SQLite")
    database = engine.url.database
    if not database or database == ":memory:" or not Path(database).is_file():
        return MigrationReport("not_initialized")
    data_dir = Path(data_dir).resolve()
    connection = sqlite3.connect(f"{Path(database).resolve().as_uri()}?mode=rw", uri=True, isolation_level=None, timeout=5)
    connection.row_factory = sqlite3.Row
    backup = None
    try:
        report, _ = _plan(connection, data_dir, filenames or {})
        if not apply or report.state != "ready":
            return report
        # SQLite backup captures WAL content too; do not copy just the .db file.
        backup_dir = data_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"datasets-before-m1-{uuid4()}.sqlite3"
        descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        with sqlite3.connect(backup) as destination:
            connection.backup(destination)
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("BEGIN IMMEDIATE")
        report, plans = _plan(connection, data_dir, filenames or {})
        report.backup_path = str(backup)
        if report.state != "ready":
            connection.rollback()
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
