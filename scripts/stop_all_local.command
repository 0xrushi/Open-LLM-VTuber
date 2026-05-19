#!/usr/bin/env bash
set -euo pipefail

echo "Stopping backend and workers..."
pkill -f "run_server.py" || true
pkill -f "open_llm_vtuber.obsidian_mcp.worker" || true

echo "Stopping redis-server..."
if command -v redis-cli >/dev/null 2>&1; then
  redis-cli -h 127.0.0.1 -p 6379 shutdown nosave >/dev/null 2>&1 || true
fi
pkill -f "[r]edis-server.*:6379" || true
pkill -x redis-server || true

echo "Local stack stopped."
