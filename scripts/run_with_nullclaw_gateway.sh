#!/usr/bin/env bash
set -euo pipefail

OPEN_LLM_VTUBER_DIR="${OPEN_LLM_VTUBER_DIR:-/home/alpha/Documents/Open-LLM-VTuber}"
NULLCLAW_BIN="${NULLCLAW_BIN:-/home/alpha/Documents/nullclaw/zig-out/bin/nullclaw}"
NULLCLAW_HOST="${NULLCLAW_HOST:-0.0.0.0}"
NULLCLAW_PORT="${NULLCLAW_PORT:-5001}"

if [[ ! -x "$NULLCLAW_BIN" ]]; then
  echo "nullclaw binary not found or not executable: $NULLCLAW_BIN" >&2
  exit 1
fi

cd "$OPEN_LLM_VTUBER_DIR"

"$NULLCLAW_BIN" gateway --port "$NULLCLAW_PORT" --host "$NULLCLAW_HOST" &
NULLCLAW_PID=$!

cleanup() {
  if kill -0 "$NULLCLAW_PID" 2>/dev/null; then
    kill "$NULLCLAW_PID" 2>/dev/null || true
    wait "$NULLCLAW_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

exec "$OPEN_LLM_VTUBER_DIR/.venv/bin/python" "$OPEN_LLM_VTUBER_DIR/run_server.py"
