from types import SimpleNamespace

import pytest

from src.open_llm_vtuber.pi_client.client import PiClient, PiConfig
from src.open_llm_vtuber.pi_client.events import CommandResult


def _ev(event_type: str, raw: dict):
    return SimpleNamespace(type=event_type, raw=raw)


def test_prompt_does_not_duplicate_streamed_text_with_agent_end_snapshot(monkeypatch):
    client = PiClient(PiConfig())

    monkeypatch.setattr(client, "start", lambda: client)
    monkeypatch.setattr(client, "_next_id", lambda: "req-1")
    monkeypatch.setattr(client, "_send", lambda _cmd: None)

    events = iter(
        [
            _ev(
                "message_update",
                {"assistantMessageEvent": {"type": "text_delta", "delta": "Hello "}},
            ),
            _ev(
                "message_update",
                {"assistantMessageEvent": {"type": "text_delta", "delta": "world"}},
            ),
            _ev(
                "agent_end",
                {
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [{"type": "text", "text": "Hello world"}],
                            "usage": {"input": 1, "output": 2, "cost": {"total": 0.0}},
                        }
                    ]
                },
            ),
        ]
    )

    def _wait_for_response(expected_type=None, timeout=120.0):
        if expected_type == "response":
            return CommandResult(success=True, command="prompt", id="req-1")
        return next(events, None)

    monkeypatch.setattr(client, "_wait_for_response", _wait_for_response)

    result = client.prompt("hi")
    assert result.text == "Hello world"


def test_prompt_raises_on_failed_prompt_response(monkeypatch):
    client = PiClient(PiConfig())

    monkeypatch.setattr(client, "start", lambda: client)
    monkeypatch.setattr(client, "_next_id", lambda: "req-1")
    monkeypatch.setattr(client, "_send", lambda _cmd: None)

    called = {"count": 0}

    def _wait_for_response(expected_type=None, timeout=120.0):
        if expected_type == "response":
            called["count"] += 1
            if called["count"] == 1:
                return CommandResult(
                    success=False,
                    command="prompt",
                    id="req-1",
                    error="Agent is already processing. Specify streamingBehavior ('steer' or 'followUp') to queue the message.",
                )
        return None

    monkeypatch.setattr(client, "_wait_for_response", _wait_for_response)

    with pytest.raises(RuntimeError, match="already processing"):
        client.prompt("hi")



def test_prompt_ignores_stale_command_responses(monkeypatch):
    client = PiClient(PiConfig())

    monkeypatch.setattr(client, "start", lambda: client)
    monkeypatch.setattr(client, "_next_id", lambda: "req-2")
    monkeypatch.setattr(client, "_send", lambda _cmd: None)

    events = iter(
        [
            _ev(
                "agent_end",
                {
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [{"type": "text", "text": "ok"}],
                            "usage": {"input": 1, "output": 1, "cost": {"total": 0.0}},
                        }
                    ]
                },
            )
        ]
    )

    responses = iter(
        [
            CommandResult(success=True, command="bash", id="req-old"),
            CommandResult(success=True, command="prompt", id="req-2"),
        ]
    )

    def _wait_for_response(expected_type=None, timeout=120.0):
        if expected_type == "response":
            return next(responses, None)
        return next(events, None)

    monkeypatch.setattr(client, "_wait_for_response", _wait_for_response)

    result = client.prompt("hi")
    assert result.text == "ok"
