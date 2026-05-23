"""Direct tool: web search via pi RPC client."""
from __future__ import annotations

import asyncio
import os

from ..pi_client import PiClient, PiConfig


async def pi_web_search(query: str, max_results: int = 5) -> str:
    """Search the web via `pi` using configured BrowserOS skill."""
    q = (query or "").strip()
    if not q:
        raise ValueError("query must be a non-empty string")

    max_results = max(1, min(int(max_results), 10))
    skill_name = os.environ.get("PI_WEB_SEARCH_SKILL", "browseros-pi")
    provider = os.environ.get("PI_WEB_SEARCH_PROVIDER") or None
    model = os.environ.get("PI_WEB_SEARCH_MODEL") or None
    pi_bin = os.environ.get("PI_WEB_SEARCH_BIN", "pi")
    timeout = float(os.environ.get("PI_WEB_SEARCH_TIMEOUT_SEC", "240"))
    tools = os.environ.get("PI_WEB_SEARCH_TOOLS") or None

    prompt = (
        "Use BrowserOS skill tools to browse and search the web.\n"
        "Open websites in BrowserOS while gathering results.\n"
        f"Query: {q}\n"
        f"Max results: {max_results}\n"
        "Return plain text only, no markdown.\n"
        "Output format:\n"
        "1. title | url | short summary\n"
        "Each line must be <= 140 characters."
    )
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
            return text or "Web search completed but returned no text output."

    try:
        return await asyncio.wait_for(asyncio.to_thread(_run_prompt), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise RuntimeError(
            f"Web search timed out after {int(timeout)}s. Try a narrower query."
        ) from exc


PI_WEB_SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "pi_web_search",
        "description": "Search the web using pi-agent and return summarized results.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {
                    "type": "integer",
                    "description": "Maximum results to include (1-10)",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 5,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}
