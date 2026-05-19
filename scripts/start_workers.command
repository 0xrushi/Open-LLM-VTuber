#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379}"
export PYTHONPATH="${PYTHONPATH:-$ROOT_DIR/src}"
export APP_DIR="${APP_DIR:-$ROOT_DIR}"

osascript <<OSA
if application "iTerm2" exists then
  tell application "iTerm2"
    activate
    set w to (create window with default profile)
    tell current session of w
      write text "cd \"$ROOT_DIR\" && export REDIS_URL=\"$REDIS_URL\" PYTHONPATH=\"$PYTHONPATH\" APP_DIR=\"$APP_DIR\" && uv run python -m open_llm_vtuber.obsidian_mcp.worker && echo 'RQ worker: obsidian-tools + web-search queues'"
    end tell
  end tell
else
  tell application "Terminal"
    activate
    do script "cd \"$ROOT_DIR\" && export REDIS_URL=\"$REDIS_URL\" PYTHONPATH=\"$PYTHONPATH\" APP_DIR=\"$APP_DIR\" && uv run python -m open_llm_vtuber.obsidian_mcp.worker && echo 'RQ worker: obsidian-tools + web-search queues'"
  end tell
end if
OSA

echo "Opened Terminal windows for workers."
