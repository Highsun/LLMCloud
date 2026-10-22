"""Run an isolated, disposable API for browser tests (never the business store)."""

import argparse
from pathlib import Path
import sys
import tempfile

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.config import Settings  # noqa: E402
from backend.app.main import create_app  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18000)
    parser.add_argument("--faults", action="store_true", help="Enable one-shot controls in this disposable server only")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="llmcloud-browser-") as directory:
        root = Path(directory)
        settings = Settings(
            _env_file=None, data_dir=root / "data", log_dir=root / "logs",
            database_url="", api_prefix="/api/v1",
        )
        app = create_app(settings)
        if args.faults:
            from scripts.browser_test_support import install_test_controls
            install_test_controls(app)
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
