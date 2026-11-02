"""Offline task reconciliation. Stop API/all Workers before explicit apply."""

import argparse
import json
from pathlib import Path
import sys
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.config import Settings  # noqa: E402
from backend.app.core.database import create_database_engine  # noqa: E402
from backend.app.services.task_reconciliation import reconcile_tasks  # noqa: E402


def task_id(value):
    try:
        identifier = UUID(value)
        if identifier.version == 4 and str(identifier) == value:
            return value
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("Expected a canonical UUIDv4")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Read-only proposals (default); does not prove a task is dead")
    mode.add_argument("--apply", action="store_true", help="Apply freshly checked proposals while holding the instance lock")
    parser.add_argument("--services-stopped", action="store_true", help="Confirm API and ALL Workers are stopped; required for apply")
    parser.add_argument("--task-id", type=task_id, action="append", help="Limit to this task (repeatable); default: all tasks")
    parser.add_argument("--database-url")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--log-dir", type=Path)
    args = parser.parse_args()
    overrides = {name: value for name, value in (("data_dir", args.data_dir), ("log_dir", args.log_dir)) if value is not None}
    engine = None
    try:
        settings = Settings(**overrides)
        engine = create_database_engine(args.database_url or settings.resolved_database_url)
        report = reconcile_tasks(engine, settings.data_dir, settings.log_dir, apply=args.apply,
            services_stopped=args.services_stopped, task_ids=args.task_id)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["state"] in {"current", "ready", "applied", "not_initialized"} else 2
    except Exception:
        print(json.dumps({"state": "error", "code": "reconciliation_failed"}), file=sys.stderr)
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
