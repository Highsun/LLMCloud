"""Disposable real account/SQLite API for browser regression; no Redis or GPU."""

import argparse
from pathlib import Path
import sys
import tempfile

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.core.config import Settings
from backend.app.main import create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Native Linux disposable parent on runtime disk")
    parser.add_argument("--port", type=int, default=18008)
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="auth-ui-", dir=args.root) as temporary:
        root = Path(temporary)
        settings = Settings(_env_file=None, data_dir=root / "data", log_dir=root / "logs", database_url="",
            auth_enabled=True, cors_origins=["http://127.0.0.1:15178"])
        uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
