#!/usr/bin/env python3
"""Appends OpenCode plugin events to a rolling JSONL log file."""

import fcntl
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent


def load_config():
    import yaml

    config_path = PLUGIN_DIR / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def summarize_tool_input(tool_name: str, tool_input: dict) -> str:
    if not tool_input:
        return ""

    lower_tool = (tool_name or "").lower()
    if lower_tool in ("read", "write", "edit"):
        return str(tool_input.get("filePath", tool_input.get("file_path", "")))[:200]
    if lower_tool == "bash":
        return str(tool_input.get("command", ""))[:200]
    if lower_tool in ("glob", "grep"):
        pattern = str(tool_input.get("pattern", ""))
        search_path = str(tool_input.get("path", ""))
        text = f"{pattern} in {search_path}" if search_path else pattern
        return text[:200]

    for value in tool_input.values():
        if isinstance(value, str):
            return value[:200]
    return ""


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return
        event = json.loads(raw)
    except Exception:
        return

    config = load_config()
    log_file = Path(config["log"]["file"])
    max_events = int(config["log"].get("max_events", 50))

    hook_type = event.get("hook_type", "unknown")
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": hook_type,
    }

    if hook_type == "tool.execute.after":
        tool_name = str(event.get("tool_name", "unknown"))
        tool_input = event.get("tool_input", {})
        tool_result = str(event.get("tool_result", ""))[:200]
        entry["tool"] = tool_name
        entry["summary"] = summarize_tool_input(tool_name, tool_input)
        entry["result_preview"] = tool_result
    elif hook_type == "chat.message":
        message = str(event.get("message", ""))
        entry["summary"] = message[:300]
    else:
        entry["summary"] = str(event)[:200]

    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.write(json.dumps(entry) + "\n")
            f.seek(0)
            lines = f.readlines()
            if len(lines) > max_events:
                lines = lines[-max_events:]
                f.seek(0)
                f.truncate()
                f.writelines(lines)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


if __name__ == "__main__":
    main()
