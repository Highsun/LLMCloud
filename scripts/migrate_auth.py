"""Read-only account migration plan, or explicit backed-up application while stopped."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.auth_migration import migrate_auth
from backend.app.core.config import Settings
from backend.app.core.database import create_database_engine
from backend.app.core.worker_lock import WorkerInstanceLock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--apply", action="store_true")
    parser.add_argument("--services-stopped", action="store_true")
    parser.add_argument("--database-url")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--assign-to-user", help="Existing user UUID; never infer ownership")
    parser.add_argument("--dataset-id", action="append", default=[], help="Exact historical dataset UUID; repeat as needed")
    args = parser.parse_args()
    if args.apply and not args.services_stopped:
        parser.error("--apply requires --services-stopped; stop API and Worker first")
    values = {name: getattr(args, name) for name in ("data_dir", "log_dir", "database_url") if getattr(args, name) is not None}
    settings = Settings(**values)
    engine = create_database_engine(settings.resolved_database_url)
    lock = None
    try:
        if args.apply:
            lock = WorkerInstanceLock(settings.log_dir)
            lock.acquire()
        report = migrate_auth(engine, settings.data_dir, apply=args.apply, services_stopped=args.services_stopped,
            assign_to_user=args.assign_to_user, dataset_ids=args.dataset_id)
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0 if report.state in ("not_initialized", "current", "ready", "applied") else 2
    except Exception as error:
        print(json.dumps({"state": "error", "reason": type(error).__name__}), file=sys.stderr)
        return 2
    finally:
        if lock:
            lock.release()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
