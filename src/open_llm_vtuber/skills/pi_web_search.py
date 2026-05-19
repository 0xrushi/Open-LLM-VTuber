"""Direct tool: web search via vendored pi-agent-py subprocess helper."""
from __future__ import annotations

import os
from pathlib import Path

from .pi_agent_py.pi_tool import run_pi


async def pi_web_search(query: str, max_results: int = 5) -> str:
    """Search the web via `pi` using a configured skill."""
    q = (query or "").strip()
    if not q:
        raise ValueError("query must be a non-empty string")

    max_results = max(1, min(int(max_results), 10))
    skill_name = os.environ.get("PI_WEB_SEARCH_SKILL", "browseros-pi")
    provider = os.environ.get("PI_WEB_SEARCH_PROVIDER")
    model = os.environ.get("PI_WEB_SEARCH_MODEL")
    pi_bin = os.environ.get("PI_WEB_SEARCH_BIN", "pi")
    timeout = float(os.environ.get("PI_WEB_SEARCH_TIMEOUT_SEC", "180"))

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

    return await run_pi(
        prompt=prompt,
        skills=[skill_name],
        extensions=[],
        provider=provider,
        model=model,
        pi_bin=pi_bin,
        timeout=timeout,
    )


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
