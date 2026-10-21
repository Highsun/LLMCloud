"""Report storage inconsistencies; never delete files. Stop writers before repair."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.services.datasets import DatasetService


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-hash", action="store_true", help="Also scan files and compare SHA256/size/rows")
    args = parser.parse_args()
    report = DatasetService().audit_storage(verify_hash=args.verify_hash)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(1 if any(report.values()) else 0)
