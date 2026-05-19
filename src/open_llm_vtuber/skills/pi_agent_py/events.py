"""Parse pi --mode json NDJSON event stream."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    result: Any = None


@dataclass
class Message:
    role: str  # "user" | "assistant"
    text: str
    thinking: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


def parse_event_stream(ndjson: str) -> tuple[str, list[Message]]:
    """
    Parse pi JSON event stream into (final_text, messages).

    Returns the last assistant text and all messages from agent_end.
    Falls back to collecting text from turn_end if agent_end is absent.
    """
    messages: list[Message] = []
    final_text = ""

    for raw in ndjson.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            continue

        ev_type = ev.get("type")

        if ev_type == "agent_end":
            messages = _parse_messages(ev.get("messages", []))
            final_text = _last_text(messages)

        elif ev_type == "turn_end" and not final_text:
            msg = ev.get("message", {})
            if msg.get("role") == "assistant":
                for c in msg.get("content", []):
                    if c.get("type") == "text":
                        final_text = c["text"]
                        break

    return final_text, messages


def _parse_messages(raw_messages: list[dict]) -> list[Message]:
    result = []
    for m in raw_messages:
        role = m.get("role", "")
        text = ""
        thinking = ""
        tool_calls: list[ToolCall] = []

        for c in m.get("content", []):
            ctype = c.get("type")
            if ctype == "text":
                text = c.get("text", "")
            elif ctype == "thinking":
                thinking = c.get("thinking", "")
            elif ctype == "tool_use":
                tool_calls.append(
                    ToolCall(
                        name=c.get("name", ""),
                        arguments=c.get("input", {}),
                    )
                )
            elif ctype == "tool_result":
                # attach result to the last matching tool call if possible
                tool_id = c.get("tool_use_id")
                for tc in reversed(tool_calls):
                    if not tc.result:
                        tc.result = c.get("content")
                        break

        result.append(
            Message(
                role=role,
                text=text,
                thinking=thinking,
                tool_calls=tool_calls,
                model=m.get("model", ""),
                usage=m.get("usage", {}),
            )
        )
    return result


def _last_text(messages: list[Message]) -> str:
    for m in reversed(messages):
        if m.role == "assistant" and m.text:
            return m.text
    return ""
