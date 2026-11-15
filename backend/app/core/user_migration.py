"""Explicit SQLite account migration and offline assignment of legacy data."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from sqlalchemy import inspect

AUTH_COLUMNS = {"password_hash": "VARCHAR(160)", "display_name": "VARCHAR(40)"}


def require_user_schema(engine):
    inspector = inspect(engine)
    if inspector.has_table("users") and not AUTH_COLUMNS.keys() <= {
        column["name"] for column in inspector.get_columns("users")
    }:
        raise RuntimeError("用户表需要显式迁移。停止 API 和 Worker 后运行 scripts/migrate_users.py --check 和 --apply。")


def _state(database):
    tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    columns = {row[1] for row in database.execute("PRAGMA table_info(users)")}
    if not {"id", "username", "created_at"} <= columns:
        raise ValueError("数据库用户表结构不符合预期。")
    unowned = (database.execute("SELECT count(*) FROM datasets WHERE user_id IS NULL").fetchone()[0]
               if "datasets" in tables else 0)
    return tables, sorted(AUTH_COLUMNS.keys() - columns), unowned


def _backup(database, directory):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / f"before-user-system-{uuid4()}.sqlite3"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    try:
        with closing(sqlite3.connect(path)) as destination:
            database.backup(destination)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def migrate_users(engine, data_dir, *, apply=False, assign_unowned_to=None):
    if engine.dialect.name != "sqlite":
        raise ValueError("账号迁移仅支持项目使用的 SQLite 数据库。")
    database = engine.url.database
    if not database or database == ":memory:" or not Path(database).is_file():
        return {"status": "not_initialized"}
    modifying = apply or assign_unowned_to is not None
    uri = f"{Path(database).resolve().as_uri()}?mode={'rw' if modifying else 'ro'}"
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        tables, missing, unowned = _state(connection)
        report = {"status": "ready" if missing else "current",
                  "missing_columns": missing, "unowned_datasets": unowned}
        if not modifying:
            return report
        if assign_unowned_to is not None and missing:
            raise ValueError("请先完成用户表结构迁移。")
        if apply and not missing:
            return report
        account = None
        if assign_unowned_to is not None:
            account = connection.execute("SELECT id FROM users WHERE username = ? AND password_hash IS NOT NULL",
                                         (assign_unowned_to.strip().lower(),)).fetchone()
            if account is None:
                raise ValueError("接收旧数据的账号必须先注册。")
            if not unowned:
                return report
        backup = _backup(connection, Path(data_dir) / "backups")
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            if _state(connection)[1:] != (missing, unowned):
                raise ValueError("数据库在备份期间发生变化，请停止 API 和 Worker 后重试。")
            for column in missing:
                connection.execute(f"ALTER TABLE users ADD COLUMN {column} {AUTH_COLUMNS[column]}")
            if "datasets" in tables:
                connection.execute("CREATE INDEX IF NOT EXISTS ix_datasets_user_id ON datasets(user_id)")
            if account is not None:
                assigned = connection.execute("UPDATE datasets SET user_id = ? WHERE user_id IS NULL", account)
                report.update(status="assigned", assigned_datasets=assigned.rowcount, unowned_datasets=0)
            else:
                report.update(status="applied", missing_columns=[])
        return {**report, "backup": str(backup)}
