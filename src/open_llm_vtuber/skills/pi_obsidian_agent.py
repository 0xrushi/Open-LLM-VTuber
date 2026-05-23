"""Direct tool: execute Obsidian requests via pi RPC client + skill."""
from __future__ import annotations

import asyncio
import os

from ..pi_client import PiClient, PiConfig


async def pi_obsidian_agent(request: str, context: str = "") -> str:
    """Run an Obsidian note/task/calendar request through pi skill tools."""
    req = (request or "").strip()
    if not req:
        raise ValueError("request must be a non-empty string")

    pi_bin = os.environ.get("PI_OBSIDIAN_AGENT_BIN", "pi")
    provider = os.environ.get("PI_OBSIDIAN_AGENT_PROVIDER", "llama-swap")
    model = os.environ.get("PI_OBSIDIAN_AGENT_MODEL", "qwen3-6-35b-a3b-gguf-q8")
    skill_name = os.environ.get("PI_OBSIDIAN_AGENT_SKILL", "npm:pi-obsidian")
    tools = os.environ.get("PI_OBSIDIAN_AGENT_TOOLS") or None
    timeout = float(os.environ.get("PI_OBSIDIAN_AGENT_TIMEOUT_SEC", "300"))
    vault_path = os.environ.get(
        "PI_OBSIDIAN_AGENT_VAULT_PATH",
        os.environ.get(
            "OBSIDIAN_VAULT_PATH",
            "/Users/bread/Library/Mobile Documents/iCloud~md~obsidian/Documents/openllmlog",
        ),
    )

    prompt = (
        "You are an Obsidian assistant with tool access through pi-obsidian.\n"
        "Always use available tools to complete the request end-to-end.\n"
        "Preferred vault path:\n"
        f"{vault_path}\n"
        "If the request is ambiguous, ask one short clarification question.\n"
        "Otherwise return concise concrete results.\n\n"
        f"User request:\n{req}"
    )
    ctx = (context or "").strip()
    if ctx:
        prompt = f"{prompt}\n\nRecent context:\n{ctx}"

    config = PiConfig(
        pi_bin=pi_bin,
        provider=provider,
        model=model,
        no_session=True,
        skill=skill_name,
        tools=tools,
    )

    def _run_prompt() -> str:
        with PiClient(config) as client:
            result = client.prompt(prompt)
            text = (result.text or "").strip()
            return text or "Obsidian task completed but returned no text output."

    try:
        return await asyncio.wait_for(asyncio.to_thread(_run_prompt), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise RuntimeError(
            f"Obsidian request timed out after {int(timeout)}s. Try a narrower request."
        ) from exc


PI_OBSIDIAN_AGENT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "pi_obsidian_agent",
        "description": (
            "Execute Obsidian note/task/calendar requests using pi-obsidian skill."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "request": {
                    "type": "string",
                    "description": "User request for Obsidian operations",
                },
                "context": {
                    "type": "string",
                    "description": "Optional recent context to disambiguate request",
                },
            },
            "required": ["request"],
            "additionalProperties": False,
        },
    },
}
