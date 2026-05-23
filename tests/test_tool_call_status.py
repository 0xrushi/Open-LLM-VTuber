"""
Tests for the ToolCallStatus Pydantic model and its integration with PiAgent.
"""

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.open_llm_vtuber.agent.output_types import ToolCallStatus
from src.open_llm_vtuber.agent.agents.pi_agent import PiAgent
from src.open_llm_vtuber.agent.input_types import BatchInput, TextData, TextSource
from src.open_llm_vtuber.agent.output_types import SentenceOutput


def _make_agent() -> PiAgent:
    return PiAgent(system="You are a test assistant.", live2d_model=None)


def _make_input(text: str) -> BatchInput:
    return BatchInput(texts=[TextData(source=TextSource.INPUT, content=text)])


class TestToolCallStatusModel(unittest.TestCase):
    """Unit tests for the ToolCallStatus Pydantic model itself."""

    def test_default_type_field(self):
        s = ToolCallStatus(
            tool_id="abc",
            tool_name="obsidian_search",
            status="running",
            content="{}",
            timestamp="2026-01-01T00:00:00Z",
        )
        self.assertEqual(s.type, "tool_call_status")

    def test_serializes_to_json_with_all_fields(self):
        s = ToolCallStatus(
            tool_id="tc-1",
            tool_name="web_search",
            status="completed",
            content="result",
            timestamp="2026-01-01T00:00:00Z",
            name="Nami",
        )
        data = json.loads(s.model_dump_json())
        for field in ("type", "tool_id", "tool_name", "status", "content", "timestamp", "name"):
            self.assertIn(field, data)
        self.assertEqual(data["type"], "tool_call_status")
        self.assertEqual(data["name"], "Nami")

    def test_valid_status_literals(self):
        for status in ("running", "completed", "error"):
            s = ToolCallStatus(
                tool_id="x", tool_name="t", status=status,
                content="", timestamp="2026-01-01T00:00:00Z",
            )
            self.assertEqual(s.status, status)

    def test_invalid_status_raises(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            ToolCallStatus(
                tool_id="x", tool_name="t", status="unknown",
                content="", timestamp="2026-01-01T00:00:00Z",
            )

    def test_name_defaults_to_none(self):
        s = ToolCallStatus(
            tool_id="x", tool_name="t", status="running",
            content="", timestamp="2026-01-01T00:00:00Z",
        )
        self.assertIsNone(s.name)

    def test_model_copy_update_name(self):
        s = ToolCallStatus(
            tool_id="x", tool_name="t", status="running",
            content="", timestamp="2026-01-01T00:00:00Z",
        )
        s2 = s.model_copy(update={"name": "Hugo"})
        self.assertEqual(s2.name, "Hugo")
        self.assertIsNone(s.name)  # original unchanged


class TestPiAgentYieldsToolCallStatus(unittest.IsolatedAsyncioTestCase):
    """PiAgent must yield ToolCallStatus instances, not raw dicts."""

    async def test_inline_tool_event_yields_toolcallstatus_instance(self):
        import threading

        agent = _make_agent()

        mock_client = MagicMock()
        mock_client._proc = True
        mock_client._event_handlers = []
        mock_client.on_event.side_effect = lambda h: mock_client._event_handlers.append(h)

        allow_done = threading.Event()

        def _prompt_with_event(_msg):
            # Block until test injects the tool event and unblocks
            allow_done.wait(timeout=5.0)
            return SimpleNamespace(text="Done.")

        mock_client.prompt.side_effect = _prompt_with_event
        agent._pi_client = mock_client

        from pi_client.events import ToolEvent

        collected = []

        async def _drive():
            async for item in agent.chat(_make_input("search something")):
                collected.append(item)

        drive_task = asyncio.create_task(_drive())

        # Wait for the event handler to be registered
        for _ in range(20):
            await asyncio.sleep(0.01)
            if mock_client._event_handlers:
                break

        # Inject tool event while prompt is still blocking
        if mock_client._event_handlers:
            ev = ToolEvent(
                type="tool_execution_start",
                raw={},
                tool_name="obsidian_search",
                tool_call_id="tc-99",
                args={"q": "test"},
                result=None,
                is_error=False,
            )
            for h in list(mock_client._event_handlers):
                h(ev)

        # Give the event queue a chance to be drained by chat()'s poll loop
        await asyncio.sleep(0.2)
        allow_done.set()
        await drive_task

        tool_items = [o for o in collected if isinstance(o, ToolCallStatus)]
        self.assertGreaterEqual(len(tool_items), 1)
        self.assertIsInstance(tool_items[0], ToolCallStatus)
        self.assertEqual(tool_items[0].tool_name, "obsidian_search")
        self.assertEqual(tool_items[0].tool_id, "tc-99")
        self.assertEqual(tool_items[0].status, "running")
        self.assertEqual(tool_items[0].type, "tool_call_status")

    async def test_tool_call_status_not_dict(self):
        """Ensure no raw dicts leak from chat() — everything is typed."""
        agent = _make_agent()

        mock_client = MagicMock()
        mock_client._proc = True
        mock_client._event_handlers = []
        mock_client.on_event.side_effect = lambda h: mock_client._event_handlers.append(h)
        mock_client.prompt.return_value = SimpleNamespace(text="Answer.")
        agent._pi_client = mock_client

        from pi_client.events import ToolEvent

        collected = []

        async def _drive():
            async for item in agent.chat(_make_input("query")):
                collected.append(item)

        drive_task = asyncio.create_task(_drive())
        for _ in range(20):
            await asyncio.sleep(0.01)
            if mock_client._event_handlers:
                break

        if mock_client._event_handlers:
            ev = ToolEvent(
                type="tool_execution_end",
                raw={},
                tool_name="web_search",
                tool_call_id="tc-7",
                args={},
                result={"data": "found"},
                is_error=False,
            )
            for h in list(mock_client._event_handlers):
                h(ev)

        await drive_task

        for item in collected:
            self.assertNotIsInstance(item, dict, "Raw dict leaked from chat()")


class TestToolEventCallbackReceivesToolCallStatus(unittest.IsolatedAsyncioTestCase):
    """_tool_event_callback must receive ToolCallStatus instances during background offload."""

    async def test_bg_tool_handler_calls_callback_with_toolcallstatus(self):
        import threading

        agent = _make_agent()

        async def _mock_speak(text):
            pass

        agent.set_speak_callback(_mock_speak)

        received_events = []

        async def _mock_tool_cb(event):
            received_events.append(event)

        agent.set_tool_event_callback(_mock_tool_cb)

        mock_client = MagicMock()
        mock_client._proc = True
        mock_client._event_handlers = []
        mock_client.on_event.side_effect = lambda h: mock_client._event_handlers.append(h)

        allow_done = threading.Event()

        def _blocking_prompt(_msg):
            allow_done.wait(timeout=5.0)
            return SimpleNamespace(text="Background answer.")

        mock_client.prompt.side_effect = _blocking_prompt
        agent._pi_client = mock_client

        from pi_client.events import ToolEvent

        collected = []

        with patch("src.open_llm_vtuber.agent.agents.pi_agent._BG_THRESHOLD_SEC", 0.1):
            async def _drive():
                async for item in agent.chat(_make_input("do something slow")):
                    collected.append(item)

            drive_task = asyncio.create_task(_drive())

            for _ in range(20):
                await asyncio.sleep(0.02)
                if mock_client._event_handlers:
                    break

            # Inject event to trigger offload
            if mock_client._event_handlers:
                ev_start = ToolEvent(
                    type="tool_execution_start", raw={}, tool_name="slow_tool",
                    tool_call_id="bg-1", args={"x": 1}, result=None, is_error=False,
                )
                for h in list(mock_client._event_handlers):
                    h(ev_start)

            # Wait past threshold
            await asyncio.sleep(0.25)
            allow_done.set()
            await drive_task
            await asyncio.sleep(0.2)  # let bg events arrive

            # Inject a post-offload tool event via the new background handler
            if len(mock_client._event_handlers) > 0:
                ev_end = ToolEvent(
                    type="tool_execution_end", raw={}, tool_name="slow_tool",
                    tool_call_id="bg-1", args={}, result={"ans": "done"}, is_error=False,
                )
                for h in list(mock_client._event_handlers):
                    h(ev_end)
                await asyncio.sleep(0.05)

        for event in received_events:
            self.assertIsInstance(event, ToolCallStatus, f"Expected ToolCallStatus, got {type(event)}")


if __name__ == "__main__":
    unittest.main()
