#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# python -m worker holds LOG_DIR/worker.lock for the process lifetime.
# Direct Celery startup is protected by worker_init too. Do not delete a live lock file.
exec uv run --locked python -m worker
