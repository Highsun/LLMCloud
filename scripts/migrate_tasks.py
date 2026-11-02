"""Check/apply the explicit SQLite task migration. Stop API/Workers before apply."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.config import Settings  # noqa: E402
from backend.app.core.database import create_database_engine  # noqa: E402
from backend.app.core.task_migration import migrate_tasks  # noqa: E402
from trainer.artifacts import read_json  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Read-only report (default)")
    mode.add_argument("--apply", action="store_true", help="Back up and migrate after stopping API/Workers")
    parser.add_argument("--snapshots", type=Path, help="Trusted task UUID -> revision/runtime/celery ID/failure mapping")
    parser.add_argument("--database-url")
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    settings = Settings(**({"data_dir": args.data_dir} if args.data_dir else {}))
    engine = create_database_engine(args.database_url or settings.resolved_database_url)
    try:
        mappings = read_json(args.snapshots) if args.snapshots else {}
        if not isinstance(mappings, dict):
            raise ValueError("Expected an object mapping")
        report = migrate_tasks(engine, settings.data_dir, apply=args.apply, snapshots=mappings)
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0 if report.state in ("not_initialized", "current", "ready", "applied") else 2
    except Exception as error:
        print(json.dumps({"state": "error", "code": "migration_failed", "reason": type(error).__name__}), file=sys.stderr)
        return 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
