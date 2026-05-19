"""
Subprocess tool: lets a pydantic-ai agent call pi for skills
that don't expose a known MCP server.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path


async def run_pi(
    prompt: str,
    *,
    skills: list[str],
    extensions: list[Path],
    provider: str | None,
    model: str | None,
    pi_bin: str,
    timeout: float,
) -> str:
    """Spawn pi --print --mode json and return the final assistant text."""
    cmd: list[str] = [pi_bin, "--print", "--mode", "json", "--no-session"]

    for skill in skills:
        cmd += ["--skill", skill]
    for ext in extensions:
        cmd += ["--extension", str(ext)]
    if provider:
        cmd += ["--provider", provider]
    if model:
        cmd += ["--model", model]
    cmd.append(prompt)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"pi timed out after {timeout}s")

    text = ""
    for raw in stdout.decode(errors="replace").splitlines():
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
