#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# Start only ONE such worker per physical GPU. Training will use the gpu queue.
exec .venv/bin/python -m worker
