#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p data/redis logs
# Local development queue. Do not start alongside the Compose Redis on port 6379.
exec redis-server --bind 127.0.0.1 --port 6379 --protected-mode yes \
  --dir "$PWD/data/redis" --appendonly yes --save "60 1" \
  --maxmemory 256mb --maxmemory-policy noeviction \
  --logfile "$PWD/logs/redis.log" --daemonize no
