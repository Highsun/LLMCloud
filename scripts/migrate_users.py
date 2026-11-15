"""Check or back up and upgrade the SQLite account schema with the platform stopped."""

import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.config import get_settings
from backend.app.core.database import engine
from backend.app.core.user_migration import migrate_users


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true", help="Read-only schema and legacy dataset count (default)")
    action.add_argument("--apply", action="store_true", help="Back up and add account columns")
    action.add_argument("--assign-unowned-to", metavar="USERNAME",
                        help="Back up and assign all unowned datasets and their tasks to this registered account")
    args = parser.parse_args()
    try:
        result = migrate_users(engine, get_settings().data_dir,
                               apply=args.apply, assign_unowned_to=args.assign_unowned_to)
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(2, f"账号迁移失败：{error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
