#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379}"
PYTHONPATH="${PYTHONPATH:-$ROOT_DIR/src}"
APP_DIR="${APP_DIR:-$ROOT_DIR}"

osascript <<OSA
if application "iTerm2" exists then
  tell application "iTerm2"
    activate
    set w to (create window with default profile)
    tell current session of w
      write text "cd \"$ROOT_DIR\" && ./scripts/start_web_build.command"
    end tell
    tell w
      create tab with default profile
      tell current session
        write text "cd \"$ROOT_DIR\" && ./scripts/start_redis.command"
      end tell
      create tab with default profile
      tell current session
        write text "cd \"$ROOT_DIR\" && export REDIS_URL=\"$REDIS_URL\" PYTHONPATH=\"$PYTHONPATH\" APP_DIR=\"$APP_DIR\" && uv run python run_server.py"
      end tell
      create tab with default profile
      tell current session
        write text "cd \"$ROOT_DIR\" && export REDIS_URL=\"$REDIS_URL\" PYTHONPATH=\"$PYTHONPATH\" APP_DIR=\"$APP_DIR\" && uv run python -m open_llm_vtuber.obsidian_mcp.worker"
      end tell
    end tell
  end tell
else
  tell application "Terminal"
    activate
    do script "cd \"$ROOT_DIR\" && ./scripts/start_web_build.command"
    do script "cd \"$ROOT_DIR\" && ./scripts/start_redis.command"
    do script "cd \"$ROOT_DIR\" && export REDIS_URL=\"$REDIS_URL\" PYTHONPATH=\"$PYTHONPATH\" APP_DIR=\"$APP_DIR\" && uv run python run_server.py"
    do script "cd \"$ROOT_DIR\" && export REDIS_URL=\"$REDIS_URL\" PYTHONPATH=\"$PYTHONPATH\" APP_DIR=\"$APP_DIR\" && uv run python -m open_llm_vtuber.obsidian_mcp.worker"
  end tell
end if
OSA

echo "Opened windows for web build, redis, backend, and workers."
