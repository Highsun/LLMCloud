#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
exec uv run --locked python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
