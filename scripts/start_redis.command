#!/usr/bin/env bash
set -euo pipefail

if pgrep -x redis-server >/dev/null 2>&1; then
  echo "redis-server is already running."
  exit 0
fi

if command -v redis-server >/dev/null 2>&1; then
  echo "Starting redis-server..."
  redis-server
else
  echo "redis-server not found. Install Redis first."
  exit 1
fi
