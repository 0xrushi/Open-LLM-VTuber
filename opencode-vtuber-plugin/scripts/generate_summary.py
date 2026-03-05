#!/usr/bin/env python3
"""Generates a witty summary of recent OpenCode events using `opencode run`."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

PLUGIN_DIR = Path(__file__).resolve().parent.parent


def load_config() -> dict[str, Any]:
    import yaml

    with open(PLUGIN_DIR / "config.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def read_events(log_file: str) -> list[dict]:
    path = Path(log_file)
    if not path.exists():
        return []

    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def format_events_for_prompt(events: list[dict]) -> str:
    lines = []
    for event in events:
        event_type = event.get("type", "?")
        if event_type == "tool.execute.after":
            tool = event.get("tool", "?")
            summary = event.get("summary", "")
            lines.append(f"- Used tool: {tool} | {summary}")
        elif event_type == "chat.message":
            summary = str(event.get("summary", ""))[:150]
            lines.append(f"- Developer vibe: {summary}")
        else:
            lines.append(f"- {event_type}: {str(event.get('summary', ''))[:100]}")
    return "\n".join(lines)


def resolve_opencode_binary(config: dict[str, Any]) -> str:
    configured = str(config["summary_llm"].get("opencode_binary", "opencode")).strip()
    candidates = [
        configured,
        os.path.expanduser("~/.opencode/bin/opencode"),
        os.path.expanduser("~/.local/share/opencode/bin/opencode"),
    ]

    for candidate in candidates:
        if not candidate:
            continue
        if "/" in candidate:
            if Path(candidate).exists():
                return candidate
        else:
            resolved = shutil.which(candidate)
            if resolved:
                return resolved

    return configured or "opencode"


def extract_commentary(stdout: str) -> str:
    cleaned = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", stdout)
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return ""

    content_lines = [
        line
        for line in lines
        if not line.startswith(">")
        and not line.startswith("Commands:")
        and not line.startswith("Options:")
    ]
    if not content_lines:
        return ""

    return " ".join(content_lines[-2:]).strip()


def generate_summary(config: dict[str, Any] | None = None) -> str:
    if config is None:
        config = load_config()

    events = read_events(config["log"]["file"])
    if len(events) < config["log"].get("min_events_to_summarize", 2):
        return ""

    system_prompt = config["personality"]["system_prompt"].strip()

    opencode_bin = resolve_opencode_binary(config)
    model = config["summary_llm"].get("model", "")
    summary_timeout = int(config["summary_llm"].get("timeout_seconds", 45))
    run_prompt = (
        f"System prompt:\n{system_prompt}\n\n"
        "Style guardrails:\n"
        "- Talk like you're reacting in real time, not reading a transcript.\n"
        "- Do not use framing like 'you said', 'i said', 'the user said', or quote-role narration.\n"
        "- Make it feel personal and direct, based on the session behavior.\n\n"
        f"Session events:\n{format_events_for_prompt(events)}\n\n"
        "Return only one short spoken-style comment (1-2 lines)."
    )

    cmd = [opencode_bin, "run"]
    if model:
        cmd.extend(["-m", model])
    cmd.append(run_prompt)

    try:
        env = os.environ.copy()
        env["OPENCODE_VTUBER_SKIP"] = "1"
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=summary_timeout,
            env=env,
        )
        summary = extract_commentary(result.stdout)
        if result.returncode == 0 and summary:
            return summary

        if model:
            retry_cmd = [opencode_bin, "run", run_prompt]
            retry_result = subprocess.run(
                retry_cmd,
                capture_output=True,
                text=True,
                timeout=summary_timeout,
                env=env,
            )
            retry_summary = extract_commentary(retry_result.stdout)
            if retry_result.returncode == 0 and retry_summary:
                return retry_summary
    except Exception:
        pass

    tools_used = [event.get("tool", "?") for event in events if event.get("tool")]
    files = [
        event.get("summary", "")
        for event in events
        if str(event.get("tool", "")).lower() in ("read", "write", "edit")
    ]
    interesting_file = "some files"
    for value in reversed(files):
        if value:
            interesting_file = value
            break

    top_tools: dict[str, int] = {}
    for tool in tools_used:
        name = str(tool)
        top_tools[name] = top_tools.get(name, 0) + 1

    if top_tools:
        main_tool = max(top_tools.items(), key=lambda item: item[1])[0]
        return (
            f"OpenCode went full {main_tool} mode and kept poking {interesting_file}. "
            "Very subtle, very efficient."
        )

    return "OpenCode wrapped a cycle and called it progress. Honestly, mood."


if __name__ == "__main__":
    print(generate_summary())
