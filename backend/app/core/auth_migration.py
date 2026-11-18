"""Add account credentials explicitly; never infer owners of historical data."""

from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
import sqlite3
from uuid import UUID, uuid4

from sqlalchemy import inspect
from sqlalchemy.dialects.sqlite import dialect
from sqlalchemy.schema import CreateIndex, CreateTable

from backend.app.models.entities import AuthSession


class AuthSchemaMigrationRequired(RuntimeError):
    pass


def require_auth_schema(engine):
    if inspect(engine).has_table("users"):
        with engine.connect() as connection:
            report = _plan(connection.connection.driver_connection, None, ())
        if report.state == "ready":
            raise AuthSchemaMigrationRequired("账户表需要显式迁移：python scripts/migrate_auth.py --check；停服务后 --apply --services-stopped。")
        if report.state in ("unsupported_schema", "blocked"):
            raise AuthSchemaMigrationRequired("账户数据库结构无法识别，请先执行 migrate_auth.py --check 并核对报告。")


@dataclass
class AuthMigrationReport:
    state: str
    users: int = 0
    unowned_datasets: int = 0
    assigned_datasets: int = 0
    issues: list[str] = field(default_factory=list)
    backup_path: str | None = None

    def to_dict(self):
        return asdict(self)


def _plan(connection, assign_to_user, dataset_ids):
    columns = {row[1]: row for row in connection.execute("PRAGMA table_info(users)")}
    if not columns:
        return AuthMigrationReport("not_initialized")
    old = {"id", "username", "created_at"}
    credentials = old | {"password_hash"}
    profile = credentials | {"display_name"}
    if set(columns) not in (old, credentials, profile):
        return AuthMigrationReport("unsupported_schema", issues=["unknown_users_columns"])
    expected = {"id": "VARCHAR(36)", "username": "VARCHAR(64)", "created_at": "DATETIME",
                "password_hash": "VARCHAR(255)", "display_name": "VARCHAR(40)"}
    # The standalone account branch used VARCHAR(160). SQLite does not enforce
    # this length, so existing rows can be upgraded to scrypt in place.
    if "display_name" in columns and columns["password_hash"][2].upper() == "VARCHAR(160)":
        expected["password_hash"] = "VARCHAR(160)"
    if any(column[2].upper() != expected[name] for name, column in columns.items()):
        return AuthMigrationReport("unsupported_schema", issues=["unknown_users_types"])
    if not columns["id"][5] or any(not columns[name][3] for name in old):
        return AuthMigrationReport("unsupported_schema", issues=["unknown_users_constraints"])
    indexes = connection.execute("PRAGMA index_list(users)").fetchall()
    if not any(row[2] and [c[2] for c in connection.execute(f'PRAGMA index_info("{row[1]}")')] == ["username"] for row in indexes):
        return AuthMigrationReport("unsupported_schema", issues=["username_uniqueness_missing"])
    session_columns = {row[1] for row in connection.execute("PRAGMA table_info(auth_sessions)")}
    if session_columns and session_columns != {"token_hash", "user_id", "expires_at"}:
        return AuthMigrationReport("unsupported_schema", issues=["unknown_session_columns"])
    if session_columns:
        session_info = {row[1]: row for row in connection.execute("PRAGMA table_info(auth_sessions)")}
        expected_session = {"token_hash": "VARCHAR(64)", "user_id": "VARCHAR(36)", "expires_at": "FLOAT"}
        if any(info[2].upper() != expected_session[name] or not info[3]
                or info[5] != int(name == "token_hash") or info[4] is not None for name, info in session_info.items()):
            return AuthMigrationReport("unsupported_schema", issues=["unknown_session_types_or_constraints"])
        foreign = list(connection.execute("PRAGMA foreign_key_list(auth_sessions)"))
        if len(foreign) != 1 or tuple(foreign[0][2:7]) != ("users", "user_id", "id", "NO ACTION", "NO ACTION"):
            return AuthMigrationReport("unsupported_schema", issues=["unknown_session_foreign_key"])
        indexes = list(connection.execute("PRAGMA index_list(auth_sessions)"))
        indexed = {tuple(column[2] for column in connection.execute(f'PRAGMA index_info("{row[1]}")')) for row in indexes}
        if not {("token_hash",), ("user_id",), ("expires_at",)}.issubset(indexed):
            return AuthMigrationReport("unsupported_schema", issues=["session_indexes_missing"])
    ready = "display_name" not in columns or not session_columns
    report = AuthMigrationReport("ready" if ready else "current", users=connection.execute("SELECT count(*) FROM users").fetchone()[0])
    if connection.execute("SELECT lower(username) FROM users GROUP BY lower(username) HAVING count(*)>1 LIMIT 1").fetchone():
        report.issues.append("case_insensitive_username_collision")
    dataset_columns = {row[1] for row in connection.execute("PRAGMA table_info(datasets)")}
    if dataset_columns:
        if not {"id", "user_id"}.issubset(dataset_columns):
            return AuthMigrationReport("unsupported_schema", issues=["unknown_dataset_ownership"])
        report.unowned_datasets = connection.execute("SELECT count(*) FROM datasets WHERE user_id IS NULL").fetchone()[0]
    if bool(assign_to_user) != bool(dataset_ids):
        report.issues.append("explicit_user_and_dataset_ids_required_together")
    if assign_to_user and dataset_ids:
        try:
            assign_to_user = str(UUID(assign_to_user))
            dataset_ids = list(dict.fromkeys(str(UUID(value)) for value in dataset_ids))
        except (ValueError, TypeError):
            report.issues.append("invalid_uuid")
            return AuthMigrationReport("blocked", issues=report.issues)
        user = connection.execute("SELECT id FROM users WHERE id=?", (assign_to_user,)).fetchone()
        if user is None:
            report.issues.append("assignment_user_not_found")
        for identifier in dataset_ids:
            row = connection.execute("SELECT user_id FROM datasets WHERE id=?", (identifier,)).fetchone() if dataset_columns else None
            if row is None:
                report.issues.append("assignment_dataset_not_found")
            elif row[0] not in (None, assign_to_user):
                report.issues.append("dataset_already_owned_by_another_user")
            elif row[0] is None:
                report.assigned_datasets += 1
        if report.assigned_datasets:
            report.state = "ready"
    if connection.execute("PRAGMA foreign_key_check").fetchone():
        report.issues.append("existing_foreign_key_violation")
    if report.issues:
        report.state = "blocked"
    return report


def migrate_auth(engine, data_dir, *, apply=False, services_stopped=False, assign_to_user=None, dataset_ids=()):
    if engine.dialect.name != "sqlite":
        raise ValueError("Auth migration supports SQLite only")
    if apply and not services_stopped:
        raise ValueError("Stop API and Worker, then explicitly confirm services_stopped")
    database = engine.url.database
    if not database or database == ":memory:" or not Path(database).is_file():
        return AuthMigrationReport("not_initialized")
    uri = Path(database).resolve().as_uri() + ("?mode=rw" if apply else "?mode=ro")
    with sqlite3.connect(uri, uri=True, isolation_level=None, timeout=5) as connection:
        report = _plan(connection, assign_to_user, dataset_ids)
        if not apply or report.state != "ready":
            return report
        root = Path(data_dir).resolve() / "backups"
        root.mkdir(parents=True, exist_ok=True)
        backup = root / f"auth-before-migration-{uuid4()}.sqlite3"
        descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        with sqlite3.connect(backup) as destination:
            connection.backup(destination)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        try:
            report = _plan(connection, assign_to_user, dataset_ids)
            if report.state != "ready":
                connection.rollback()
                report.backup_path = str(backup)
                return report
            user_columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
            if "password_hash" not in user_columns:
                connection.execute("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255)")
            if "display_name" not in user_columns:
                connection.execute("ALTER TABLE users ADD COLUMN display_name VARCHAR(40)")
            if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='auth_sessions'").fetchone():
                connection.execute(str(CreateTable(AuthSession.__table__).compile(dialect=dialect())))
                for index in AuthSession.__table__.indexes:
                    connection.execute(str(CreateIndex(index).compile(dialect=dialect())))
            if assign_to_user:
                for identifier in set(dataset_ids):
                    connection.execute("UPDATE datasets SET user_id=? WHERE id=? AND user_id IS NULL",
                        (str(UUID(assign_to_user)), str(UUID(identifier))))
            if connection.execute("PRAGMA foreign_key_check").fetchone():
                raise RuntimeError("Foreign key validation failed")
            connection.commit()
            report.state, report.backup_path = "applied", str(backup)
            return report
        except BaseException:
            connection.rollback()
            raise
