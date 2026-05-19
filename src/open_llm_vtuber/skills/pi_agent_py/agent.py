"""
PiAgent — pydantic-ai Agent backed by pi skills.

Skills with a known MCP URL (see registry.py) are wired as
MCPServerStreamableHTTP toolsets — the pydantic-ai agent calls their
tools directly, with full type-checking and streaming support.

Skills without a known MCP URL fall back to a pi subprocess tool:
the outer LLM calls pi as a black-box tool and gets back its text output.
"""
from __future__ import annotations

import shutil
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStreamableHTTP
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from .pi_tool import run_pi
from .registry import SKILL_MCP

DEFAULT_INSTRUCTIONS = (
    "You are a helpful AI assistant. "
    "Use the available tools to complete tasks accurately."
)

# Warn when estimated history tokens exceed this fraction of the budget
_WARN_FRACTION = 0.6
_DEFAULT_TOKEN_BUDGET = 32_000


def _estimate_tokens(messages: list[ModelMessage]) -> int:
    """Rough token estimate: serialized JSON chars / 4."""
    try:
        from pydantic_ai.messages import ModelMessagesTypeAdapter
        return len(ModelMessagesTypeAdapter.dump_json(messages)) // 4
    except Exception:
        return 0


def _red(text: str) -> str:
    return f"\033[91m{text}\033[0m"


def _warn_context(estimated: int, budget: int) -> None:
    pct = int(estimated / budget * 100)
    print(
        _red(
            f"⚠  Context warning: ~{estimated:,} tokens used"
            f" ({pct}% of {budget:,} budget)."
            f" Call agent.compress_history(messages) to summarize."
        ),
        file=sys.stderr,
    )


def create_agent(
    model,
    *,
    skills: list[str] | None = None,
    extensions: list[str | Path] | None = None,
    mcp_urls: list[str] | None = None,
    instructions: str | None = None,
    pi_bin: str | None = None,
    pi_provider: str | None = None,
    pi_model: str | None = None,
    pi_timeout: float = 300.0,
    retries: int = 3,
    **agent_kwargs,
) -> Agent:
    """
    Build a real pydantic-ai Agent backed by pi skills.

    Skills in the registry → MCPServerStreamableHTTP (native tools).
    Skills not in the registry → pi subprocess tool (fallback).

    Args:
        model:        pydantic-ai model string or model object.
        skills:       pi skill names to load.
        extensions:   Paths to .ts extension files.
        mcp_urls:     Explicit MCP server URLs to add as toolsets.
        instructions: System instructions for the agent.
        pi_bin:       Path to pi binary (default: auto-detect).
        pi_provider:  Provider passed to pi subprocess (non-MCP skills).
        pi_model:     Model passed to pi subprocess (non-MCP skills).
        pi_timeout:   Timeout in seconds for pi subprocess calls.
        retries:      Tool retry count (default 3, raised from pydantic-ai's 1).
        **agent_kwargs: Forwarded to pydantic_ai.Agent().
    """
    _pi_bin = pi_bin or shutil.which("pi") or "pi"
    _extensions = [Path(e) for e in (extensions or [])]

    toolsets: list[MCPServerStreamableHTTP] = []
    fallback_skills: list[str] = []

    for skill in (skills or []):
        url = SKILL_MCP.get(skill)
        if url:
            toolsets.append(MCPServerStreamableHTTP(url))
        else:
            fallback_skills.append(skill)

    for url in (mcp_urls or []):
        toolsets.append(MCPServerStreamableHTTP(url))

    agent: Agent = Agent(
        model,
        toolsets=toolsets if toolsets else [],
        instructions=instructions or DEFAULT_INSTRUCTIONS,
        retries=retries,
        **agent_kwargs,
    )

    if fallback_skills or _extensions:
        _skills_snapshot = list(fallback_skills)
        _exts_snapshot = list(_extensions)

        @agent.tool_plain(name="run_pi_skill", retries=retries)
        async def run_pi_skill(prompt: str) -> str:
            """
            Run a task using the pi agent with the loaded skills/extensions.
            Use this for browser actions, file edits, code execution, or any
            capability exposed by the loaded pi skills.
            prompt: full task description for the pi agent.
            """
            return await run_pi(
                prompt,
                skills=_skills_snapshot,
                extensions=_exts_snapshot,
                provider=pi_provider,
                model=pi_model,
                pi_bin=_pi_bin,
                timeout=pi_timeout,
            )

    return agent


class PiAgent:
    """
    Convenience wrapper that manages the pydantic-ai Agent lifecycle.

    Context management
    ------------------
    Pass `token_budget` to enable automatic context warnings. When message
    history grows beyond 60% of the budget a red warning is printed to stderr.
    Call `await agent.compress_history(messages)` to summarize old messages
    into a compact pair before they overflow the budget.

    The underlying Agent is exposed as `.agent` for full pydantic-ai access.
    """

    def __init__(
        self,
        *,
        model=None,
        skills: list[str] | None = None,
        extensions: list[str | Path] | None = None,
        mcp_urls: list[str] | None = None,
        instructions: str | None = None,
        pi_bin: str | None = None,
        pi_provider: str | None = None,
        pi_model: str | None = None,
        pi_timeout: float = 300.0,
        token_budget: int = _DEFAULT_TOKEN_BUDGET,
        retries: int = 3,
        **agent_kwargs,
    ) -> None:
        if model is None:
            model = "anthropic:claude-sonnet-4-6"
        self._model = model
        self.token_budget = token_budget
        self.agent = create_agent(
            model,
            skills=skills,
            extensions=extensions,
            mcp_urls=mcp_urls,
            instructions=instructions,
            pi_bin=pi_bin,
            pi_provider=pi_provider,
            pi_model=pi_model,
            pi_timeout=pi_timeout,
            retries=retries,
            **agent_kwargs,
        )

    def _check_context(self, message_history: list[ModelMessage] | None) -> None:
        if not message_history:
            return
        estimated = _estimate_tokens(message_history)
        if estimated >= int(self.token_budget * _WARN_FRACTION):
            _warn_context(estimated, self.token_budget)

    async def run(self, prompt: str, **kwargs):
        """
        Run the agent. MCP connections are opened/closed automatically.

        Pass message_history=result.new_messages() for multi-turn conversations.
        A red warning is printed to stderr when history approaches the token budget.
        """
        self._check_context(kwargs.get("message_history"))
        async with self.agent:
            return await self.agent.run(prompt, **kwargs)

    def run_sync(self, prompt: str, **kwargs):
        """Synchronous run."""
        import asyncio
        return asyncio.get_event_loop().run_until_complete(self.run(prompt, **kwargs))

    @asynccontextmanager
    async def run_stream(self, prompt: str, **kwargs) -> AsyncIterator[AsyncIterator[str]]:
        """
        Stream text tokens.

            async with agent.run_stream("prompt") as stream:
                async for chunk in stream:
                    print(chunk, end="")
        """
        self._check_context(kwargs.get("message_history"))
        async with self.agent:
            async with self.agent.run_stream(prompt, **kwargs) as response:
                yield response.stream_text()

    async def compress_history(
        self,
        messages: list[ModelMessage],
        keep_last: int = 2,
    ) -> list[ModelMessage]:
        """
        Summarize old messages to reduce context size.

        Compresses everything except the most recent `keep_last` exchanges
        into a single summary message pair, then appends the recent messages.

        Args:
            messages:  Full message history (e.g. result.new_messages()).
            keep_last: Number of recent message pairs to keep verbatim.

        Returns:
            Compressed message list suitable for the next message_history= call.

        Example:
            history = result.new_messages()
            history = await agent.compress_history(history)
            result2 = await agent.run("next prompt", message_history=history)
        """
        if len(messages) <= keep_last * 2:
            return messages

        to_summarize = messages[: -keep_last * 2] if keep_last else messages
        recent = messages[-keep_last * 2 :] if keep_last else []

        # Build a plain-text transcript of the messages to summarize
        lines: list[str] = []
        for m in to_summarize:
            if isinstance(m, ModelRequest):
                for part in m.parts:
                    if isinstance(part, UserPromptPart):
                        lines.append(f"User: {part.content}")
            elif isinstance(m, ModelResponse):
                for part in m.parts:
                    if isinstance(part, TextPart):
                        lines.append(f"Assistant: {part.content}")
        transcript = "\n".join(lines)

        summarizer: Agent = Agent(
            self._model,
            instructions=(
                "You are a conversation summarizer. "
                "Produce a concise factual summary of the conversation. "
                "Preserve key decisions, results, file paths, URLs, and any "
                "information the assistant will need to continue the task. "
                "Be brief — aim for under 200 words."
            ),
        )
        async with summarizer:
            summary_result = await summarizer.run(
                f"Summarize this conversation:\n\n{transcript}"
            )
        summary_text = summary_result.output

        before_tokens = _estimate_tokens(messages)
        after_tokens = _estimate_tokens(recent) + len(summary_text) // 4
        saved = before_tokens - after_tokens

        print(
            f"Context compressed: ~{before_tokens:,} → ~{after_tokens:,} tokens"
            f" (saved ~{saved:,}).",
            file=sys.stderr,
        )

        compressed: list[ModelMessage] = [
            ModelRequest(parts=[UserPromptPart(content=f"[Conversation summary]\n{summary_text}")]),
            ModelResponse(parts=[TextPart(content="Understood, continuing with this context.")]),
            *recent,
        ]
        return compressed
