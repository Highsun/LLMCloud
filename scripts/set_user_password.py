"""Explicitly activate/reset an existing account, with a backup and hidden prompts."""

import argparse
import getpass
import json
import os
from pathlib import Path
import sqlite3
import sys
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.auth_migration import require_auth_schema
from backend.app.core.config import Settings
from backend.app.core.database import create_database_engine
from backend.app.core.worker_lock import WorkerInstanceLock
from backend.app.services.auth import password_hash, validate_password


def set_user_password(engine, data_dir, user_id, password, *, services_stopped=False):
    if not services_stopped:
        raise ValueError("Stop API and Worker first")
    if engine.dialect.name != "sqlite":
        raise ValueError("SQLite only")
    validate_password(password)
    user_id = str(UUID(user_id))
    require_auth_schema(engine)
    path = Path(engine.url.database).resolve()
    if not path.is_file():
        raise ValueError("Existing database required")
    with sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, isolation_level=None, timeout=5) as connection:
        if not connection.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone():
            raise ValueError("User not found")
        encoded = password_hash(password)
        directory = Path(data_dir).resolve() / "backups"
        directory.mkdir(parents=True, exist_ok=True)
        backup = directory / f"auth-before-password-reset-{uuid4()}.sqlite3"
        descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        with sqlite3.connect(backup) as destination:
            connection.backup(destination)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        try:
            changed = connection.execute("UPDATE users SET password_hash=? WHERE id=?", (encoded, user_id)).rowcount
            if changed != 1:
                raise ValueError("User disappeared")
            revoked = connection.execute("DELETE FROM auth_sessions WHERE user_id=?", (user_id,)).rowcount
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        return {"state": "applied", "user_id": user_id, "revoked_sessions": revoked, "backup_path": str(backup)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True, help="Existing account UUID, not a new owner guess")
    parser.add_argument("--services-stopped", action="store_true")
    parser.add_argument("--database-url")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--log-dir", type=Path)
    args = parser.parse_args()
    if not args.services_stopped:
        parser.error("Stop API and Worker, then pass --services-stopped")
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        parser.error("Use an interactive terminal; passwords are never accepted through arguments, files, or stdin pipes")
    values = {name: getattr(args, name) for name in ("database_url", "data_dir", "log_dir") if getattr(args, name) is not None}
    settings = Settings(**values)
    engine = create_database_engine(settings.resolved_database_url)
    lock = WorkerInstanceLock(settings.log_dir)
    try:
        password = getpass.getpass("New password (12–128 characters): ")
        confirmation = getpass.getpass("Confirm new password: ")
        if password != confirmation:
            raise ValueError("Password confirmation differs")
        validate_password(password)
        lock.acquire()
        result = set_user_password(engine, settings.data_dir, args.user_id, password, services_stopped=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        # Do not stringify exceptions originating from credential handling.
        print(json.dumps({"state": "error", "reason": type(error).__name__}), file=sys.stderr)
        return 2
    finally:
        lock.release()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
