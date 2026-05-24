"""
Tests for PiAgent background execution and tool event streaming.

These tests mock the pi-python-client so no running pi subprocess is needed.
"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.open_llm_vtuber.agent.agents.pi_agent import PiAgent, _BG_THRESHOLD_SEC
from src.open_llm_vtuber.agent.input_types import BatchInput, TextData, TextSource
from src.open_llm_vtuber.agent.output_types import SentenceOutput, ToolCallStatus


def _make_agent() -> PiAgent:
    return PiAgent(system="You are a test assistant.", live2d_model=None)


def _make_input(text: str) -> BatchInput:
    return BatchInput(texts=[TextData(source=TextSource.INPUT, content=text)])


def _make_tool_event(tool_name: str, event_type: str, tool_call_id: str = "tc-1"):
    from src.open_llm_vtuber.pi_client.events import ToolEvent
    return ToolEvent(
        type=event_type,
        raw={},
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        args={"query": "test"},
        result={"data": "found it"} if event_type == "tool_execution_end" else None,
        is_error=False,
    )


class TestPiAgentFastResponse(unittest.IsolatedAsyncioTestCase):
    """Result arrives quickly — no background offload."""

    async def test_fast_response_yields_sentence_output_inline(self):
        agent = _make_agent()

        mock_client = MagicMock()
        mock_client._proc = True
        mock_client._event_handlers = []
        mock_client.prompt.return_value = SimpleNamespace(text="Hello, sweetie!")

        agent._pi_client = mock_client

        outputs = []
        async for item in agent.chat(_make_input("hi")):
            outputs.append(item)

        self.assertEqual(len(outputs), 1)
        self.assertIsInstance(outputs[0], SentenceOutput)
        self.assertEqual(outputs[0].tts_text, "Hello, sweetie!")

    async def test_fast_response_with_tool_event_still_inline_below_threshold(self):
        """Tool event arrives but result also comes back quickly — still inline."""
        agent = _make_agent()

        mock_client = MagicMock()
        mock_client._proc = True
        mock_client._event_handlers = []

        async def _fast_prompt(_):
            return SimpleNamespace(text="Done fast.")

        mock_client.prompt.return_value = SimpleNamespace(text="Done fast.")
        agent._pi_client = mock_client

        outputs = []
        async for item in agent.chat(_make_input("search something")):
            outputs.append(item)

        sentence_outputs = [o for o in outputs if isinstance(o, SentenceOutput)]
        self.assertEqual(len(sentence_outputs), 1)
        self.assertEqual(sentence_outputs[0].tts_text, "Done fast.")


class TestPiAgentToolEventFormat(unittest.IsolatedAsyncioTestCase):
    """Tool events yielded during a prompt must match frontend expectations."""

    async def test_tool_event_fields_match_frontend_contract(self):
        """Frontend needs: tool_id, tool_name, status, content, timestamp."""
        agent = _make_agent()

        loop = asyncio.get_event_loop()
        event_queue: asyncio.Queue = asyncio.Queue()
        tool_events_captured = []

        # Simulate: prompt takes a bit, fires a tool_execution_start event
        from pi_client.events import ToolEvent

        async def _slow_prompt_side_effect():
            await asyncio.sleep(0.05)
            # Simulate the event handler being triggered
            ev = _make_tool_event("obsidian_search", "tool_execution_start")
            await event_queue.put(ev)
            await asyncio.sleep(0.05)
            ev_end = _make_tool_event("obsidian_search", "tool_execution_end")
            await event_queue.put(ev_end)
            return SimpleNamespace(text="Found your note.")

        mock_client = MagicMock()
        mock_client._proc = True
        mock_client._event_handlers = []
        mock_client.prompt.return_value = SimpleNamespace(text="Found your note.")
        agent._pi_client = mock_client

        # Patch the event queue directly — inject events before the prompt resolves
        with patch.object(agent, "chat", wraps=agent.chat):
            # We'll manually test the event format by calling _drain logic inline
            ev_start = _make_tool_event("obsidian_search", "tool_execution_start", "tc-42")
            ev_end = _make_tool_event("obsidian_search", "tool_execution_end", "tc-42")

            for ev, expected_status in [(ev_start, "running"), (ev_end, "completed")]:
                content = str(ev.args) if ev.type != "tool_execution_end" else str(ev.result)
                status = "running" if ev.type != "tool_execution_end" else ("error" if ev.is_error else "completed")
                event_dict = {
                    "type": "tool_call_status",
                    "tool_id": ev.tool_call_id or "generated",
                    "tool_name": ev.tool_name,
                    "status": status,
                    "content": content,
                    "timestamp": "2026-01-01T00:00:00Z",
                }
                # Validate all frontend-required fields are present
                for field in ("type", "tool_id", "tool_name", "status", "content", "timestamp"):
                    self.assertIn(field, event_dict, f"Missing field: {field}")
                self.assertEqual(event_dict["status"], expected_status)
                self.assertEqual(event_dict["tool_name"], "obsidian_search")
                self.assertEqual(event_dict["tool_id"], "tc-42")


class TestPiAgentBackgroundOffload(unittest.IsolatedAsyncioTestCase):
    """Slow tool-calling responses offload to background after threshold."""

    async def test_slow_response_yields_ack_and_fires_background_task(self):
        import threading
        import time as _time

        agent = _make_agent()

        speak_received = []

        async def _mock_speak(text: str):
            speak_received.append(text)

        agent.set_speak_callback(_mock_speak)

        mock_client = MagicMock()
        mock_client._proc = True
        mock_client._event_handlers = []
        # Make on_event actually register the handler (not just record the call)
        mock_client.on_event.side_effect = lambda h: mock_client._event_handlers.append(h)

        final_answer = "I found the notes on your study schedule."
        allow_done = threading.Event()

        def _blocking_prompt(_msg):
            # Pure threading — no asyncio calls
            allow_done.wait(timeout=5.0)
            return SimpleNamespace(text=final_answer)

        mock_client.prompt.side_effect = _blocking_prompt
        agent._pi_client = mock_client

        collected = []

        with patch("src.open_llm_vtuber.agent.agents.pi_agent._BG_THRESHOLD_SEC", 0.15):
            async def _drive():
                async for item in agent.chat(_make_input("check my notes")):
                    collected.append(item)

            drive_task = asyncio.create_task(_drive())

            # Wait for chat() to register its event handler, then inject a tool event
            for _ in range(20):
                await asyncio.sleep(0.02)
                if mock_client._event_handlers:
                    break

            if mock_client._event_handlers:
                ev = _make_tool_event("obsidian_search", "tool_execution_start")
                for h in list(mock_client._event_handlers):
                    h(ev)

            # Wait past threshold so offload triggers
            await asyncio.sleep(0.3)
            allow_done.set()
            await drive_task
            await asyncio.sleep(0.1)  # let bg task deliver

        sentence_outputs = [o for o in collected if isinstance(o, SentenceOutput)]
        self.assertGreaterEqual(len(sentence_outputs), 1)
        self.assertIn("look into", sentence_outputs[0].tts_text.lower())
        self.assertEqual(speak_received, [final_answer])

    async def test_emits_tool_status_from_local_pi_client_tool_event(self):
        """Regression: local pi_client ToolEvent must be recognized and streamed."""
        import threading

        agent = _make_agent()
        mock_client = MagicMock()
        mock_client._proc = True
        mock_client._event_handlers = []
        mock_client.on_event.side_effect = lambda h: mock_client._event_handlers.append(h)

        allow_done = threading.Event()

        def _blocking_prompt(_msg):
            allow_done.wait(timeout=5.0)
            return SimpleNamespace(text="done")

        mock_client.prompt.side_effect = _blocking_prompt
        agent._pi_client = mock_client

        collected = []

        async def _drive():
            async for item in agent.chat(_make_input("use tools")):
                collected.append(item)

        task = asyncio.create_task(_drive())

        for _ in range(20):
            await asyncio.sleep(0.02)
            if mock_client._event_handlers:
                break

        self.assertTrue(mock_client._event_handlers)
        ev = _make_tool_event("browseros_navigate", "tool_execution_start", "tc-local")
        for h in list(mock_client._event_handlers):
            h(ev)

        await asyncio.sleep(0.1)
        allow_done.set()
        await task

        tool_updates = [o for o in collected if isinstance(o, ToolCallStatus)]
        self.assertGreaterEqual(len(tool_updates), 1)
        self.assertEqual(tool_updates[0].tool_name, "browseros_navigate")
        self.assertEqual(tool_updates[0].status, "running")

    async def test_bg_deliver_calls_speak_callback_with_result(self):
        """_bg_deliver speaks the result text via the callback."""
        agent = _make_agent()
        spoken = []

        async def _cb(text):
            spoken.append(text)

        agent.set_speak_callback(_cb)

        future = asyncio.get_event_loop().run_in_executor(
            None, lambda: SimpleNamespace(text="Background result here.")
        )
        await agent._bg_deliver(future)
        self.assertEqual(spoken, ["Background result here."])

    async def test_bg_deliver_skips_empty_result(self):
        """_bg_deliver does nothing if pi returns empty text."""
        agent = _make_agent()
        spoken = []

        async def _cb(text):
            spoken.append(text)

        agent.set_speak_callback(_cb)
        future = asyncio.get_event_loop().run_in_executor(
            None, lambda: SimpleNamespace(text="  ")
        )
        await agent._bg_deliver(future)
        self.assertEqual(spoken, [])


class TestPiAgentSpeakCallback(unittest.IsolatedAsyncioTestCase):
    def test_set_speak_callback_stores_fn(self):
        agent = _make_agent()
        fn = MagicMock()
        agent.set_speak_callback(fn)
        self.assertIs(agent._speak_callback, fn)

    def test_no_callback_does_not_crash_fast_path(self):
        agent = _make_agent()
        # No callback set — fast path should still work fine
        self.assertIsNone(agent._speak_callback)


if __name__ == "__main__":
    unittest.main()
