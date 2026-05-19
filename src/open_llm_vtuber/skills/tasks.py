"""RQ-serializable job functions for background web search.

These are module-level functions (no closures) so RQ can serialize them
across worker processes.
"""
from __future__ import annotations

import json
import os
import subprocess


def run_pi_web_search(
    query: str,
    max_results: int,
    pi_bin: str,
    skill_name: str,
    provider: str | None,
    model: str | None,
) -> str:
    """Execute pi web search synchronously inside an RQ worker process."""
    prompt = (
        "Use BrowserOS skill tools to browse and search the web.\n"
        "Open websites in BrowserOS while gathering results.\n"
        f"Query: {query}\n"
        f"Max results: {max_results}\n"
        "Return plain text only, no markdown.\n"
        "Output format:\n"
        "1. title | url | short summary\n"
        "Each line must be <= 140 characters."
    )

    cmd: list[str] = [pi_bin, "--print", "--mode", "json", "--no-session", "--skill", skill_name]
    if provider:
        cmd += ["--provider", provider]
    if model:
        cmd += ["--model", model]
    cmd.append(prompt)

    timeout = float(os.environ.get("PI_WEB_SEARCH_TIMEOUT_SEC", "180"))

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"pi timed out after {timeout}s")

    text = ""
    for raw in result.stdout.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "turn_end":
            msg = ev.get("message", {})
            if msg.get("role") == "assistant":
                for c in msg.get("content", []):
                    if c.get("type") == "text":
                        text = c["text"]

    return text or "(no output)"
