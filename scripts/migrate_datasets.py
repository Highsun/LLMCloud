"""Check or explicitly apply the SQLite M1 dataset migration; backups are automatic."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.config import get_settings
from backend.app.core.database import engine
from backend.app.core.dataset_migration import migrate_datasets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Read-only report (default)")
    mode.add_argument("--apply", action="store_true", help="Back up and migrate; stop API/Workers first")
    parser.add_argument("--filenames", type=Path, help="Trusted JSON mapping: dataset UUID -> original filename")
    args = parser.parse_args()
    filenames = json.loads(args.filenames.read_text(encoding="utf-8")) if args.filenames else {}
    if not isinstance(filenames, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in filenames.items()):
        parser.error("filenames must be a JSON object mapping strings to strings")
    report = migrate_datasets(engine, get_settings().data_dir, apply=args.apply, filenames=filenames)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if report.state in ("ready", "current", "applied", "not_initialized") else 2


if __name__ == "__main__":
    raise SystemExit(main())
