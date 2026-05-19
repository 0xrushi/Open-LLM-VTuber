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

xterm -T "rq-worker (obsidian + web-search)" -e bash -lc "cd \"$ROOT_DIR\" && export REDIS_URL=\"$REDIS_URL\" PYTHONPATH=\"$PYTHONPATH\" APP_DIR=\"$APP_DIR\" && uv run python -m open_llm_vtuber.obsidian_mcp.worker" &

echo "Opened xterm window for RQ worker (obsidian-tools + web-search queues)."
