#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379}"
export PYTHONPATH="${PYTHONPATH:-$ROOT_DIR/src}"
export APP_DIR="${APP_DIR:-$ROOT_DIR}"

echo "Starting backend (run_server.py)..."
uv run python run_server.py
