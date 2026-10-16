#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# Compatibility exports only; edit dependencies in pyproject.toml, then uv lock.
uv export --locked --no-dev --no-emit-project --no-hashes --output-file requirements.txt > /dev/null
uv export --locked --extra training --no-dev --no-emit-project --no-hashes \
  --emit-index-url --output-file trainer/requirements.txt > /dev/null
