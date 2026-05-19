#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379}"
PYTHONPATH="${PYTHONPATH:-$ROOT_DIR/src}"
APP_DIR="${APP_DIR:-$ROOT_DIR}"

if ! command -v xterm >/dev/null 2>&1; then
  echo "xterm not found. Install it first (e.g. apt install xterm)."
  exit 1
fi

xterm -T "redis" -e bash -lc "cd \"$ROOT_DIR\" && ./scripts/start_redis.command" &
xterm -T "web-build" -e bash -lc "cd \"$ROOT_DIR\" && ./scripts/start_web_build.command" &
xterm -T "backend" -e bash -lc "cd \"$ROOT_DIR\" && export REDIS_URL=\"$REDIS_URL\" PYTHONPATH=\"$PYTHONPATH\" APP_DIR=\"$APP_DIR\" && uv run python run_server.py" &
xterm -T "obsidian-worker" -e bash -lc "cd \"$ROOT_DIR\" && export REDIS_URL=\"$REDIS_URL\" PYTHONPATH=\"$PYTHONPATH\" APP_DIR=\"$APP_DIR\" && uv run python -m open_llm_vtuber.obsidian_mcp.worker" &

echo "Opened xterm windows for web build, redis, backend, and workers."
