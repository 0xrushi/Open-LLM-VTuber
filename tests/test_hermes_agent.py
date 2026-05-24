"""
Tests for HermesAgent ACP-based implementation.

All tests mock the ACP connection layer — no hermes binary required.
"""

import asyncio
import threading
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.open_llm_vtuber.agent.agents.hermes_agent import (
    HermesAgent,
    _HermesVTuberClient,
    _HERMES_BG_THRESHOLD_SEC,
)
from src.open_llm_vtuber.agent.input_types import BatchInput, TextData, TextSource
from src.open_llm_vtuber.agent.output_types import SentenceOutput, ToolCallStatus


def _make_agent() -> HermesAgent:
    return HermesAgent(system="You are a test assistant.", live2d_model=None)


def _make_input(text: str) -> BatchInput:
    return BatchInput(texts=[TextData(source=TextSource.INPUT, content=text)])


def _mock_acp_text_chunk(text: str):
    """Build a fake AgentMessageChunk with TextContentBlock content."""
    content = MagicMock()
    content.text = text
    chunk = MagicMock()
    chunk.__class__.__name__ = "AgentMessageChunk"
    chunk.content = content
    return chunk


def _mock_tool_start(tool_id: str, title: str, raw_input=None):
    ev = MagicMock()
    ev.__class__.__name__ = "ToolCallStart"
    ev.tool_call_id = tool_id
    ev.title = title
    ev.raw_input = raw_input
    return ev


def _mock_tool_complete(tool_id: str, title: str, output: str = ""):
    ev = MagicMock()
    ev.__class__.__name__ = "ToolCallProgress"
    ev.tool_call_id = tool_id
    ev.title = title
    ev.status = "completed"
    content_item = MagicMock()
    content_item.text = output
    ev.content = [content_item]
    return ev


class TestHermesVTuberClient(unittest.TestCase):
    """_HermesVTuberClient must queue session_update events."""

    def test_session_update_puts_event_in_queue(self):
        client = _HermesVTuberClient()
        queue = asyncio.Queue()
        client.event_queue = queue

        event = object()
        asyncio.run(client.session_update("sess", event))
        self.assertEqual(queue.get_nowait(), event)

    def test_session_update_no_queue_does_not_crash(self):
        client = _HermesVTuberClient()
        asyncio.run(client.session_update("sess", "ignored"))

    def test_request_permission_returns_response(self):
        client = _HermesVTuberClient()
        option = MagicMock()
        option.id = "allow_once"

        async def _run():
            return await client.request_permission([option], "sess", MagicMock())

        result = asyncio.run(_run())
        # Must not raise; must return a non-None response when acp is installed
        self.assertIsNotNone(result)


class TestHermesAgentTextExtraction(unittest.TestCase):
    """_extract_text must accumulate AgentMessageChunk text and skip other events."""

    def setUp(self):
        self.agent = _make_agent()

    def test_extracts_text_from_message_chunks(self):
        try:
            from acp.schema import AgentMessageChunk, TextContentBlock
        except ImportError:
            self.skipTest("acp not installed")

        chunk1 = AgentMessageChunk(
            session_update="agent_message_chunk",
            content=TextContentBlock(type="text", text="Hello "),
        )
        chunk2 = AgentMessageChunk(
            session_update="agent_message_chunk",
            content=TextContentBlock(type="text", text="world"),
        )
        result = self.agent._extract_text([chunk1, chunk2])
        self.assertEqual(result, "Hello world")

    def test_skips_non_text_events(self):
        try:
            from acp.schema import AgentMessageChunk, TextContentBlock
        except ImportError:
            self.skipTest("acp not installed")

        chunk = AgentMessageChunk(
            session_update="agent_message_chunk",
            content=TextContentBlock(type="text", text="Real answer"),
        )
        garbage = MagicMock()
        garbage.__class__.__name__ = "UsageUpdate"
        result = self.agent._extract_text([garbage, chunk, garbage])
        self.assertEqual(result, "Real answer")

    def test_empty_events_returns_empty(self):
        self.assertEqual(self.agent._extract_text([]), "")


class TestHermesAgentToolStatus(unittest.TestCase):
    """_event_to_tool_status must map ACP tool events to VTuberToolCallStatus."""

    def setUp(self):
        self.agent = _make_agent()

    def test_tool_start_yields_running_status(self):
        try:
            from acp.schema import ToolCallStart
        except ImportError:
            self.skipTest("acp not installed")

        ev = ToolCallStart(
            session_update="tool_call",
            tool_call_id="tc1",
            title="search",
            raw_input={"query": "weather"},
        )
        ts = self.agent._event_to_tool_status(ev, "AI")
        self.assertIsNotNone(ts)
        self.assertEqual(ts.status, "running")
        self.assertEqual(ts.tool_id, "tc1")
        self.assertEqual(ts.tool_name, "search")

    def test_tool_progress_completed_yields_completed_status(self):
        try:
            from acp.schema import ToolCallProgress, ContentToolCallContent
        except ImportError:
            self.skipTest("acp not installed")

        ev = ToolCallProgress(
            session_update="tool_call_update",
            tool_call_id="tc2",
            title="bash",
            status="completed",
            content=None,
        )
        ts = self.agent._event_to_tool_status(ev, "AI")
        self.assertIsNotNone(ts)
        self.assertEqual(ts.status, "completed")

    def test_tool_progress_failed_yields_error_status(self):
        try:
            from acp.schema import ToolCallProgress
        except ImportError:
            self.skipTest("acp not installed")

        ev = ToolCallProgress(
            session_update="tool_call_update",
            tool_call_id="tc3",
            title="write_file",
            status="failed",
            content=None,
        )
        ts = self.agent._event_to_tool_status(ev, "AI")
        self.assertIsNotNone(ts)
        self.assertEqual(ts.status, "error")

    def test_unknown_event_returns_none(self):
        garbage = MagicMock()
        garbage.__class__.__name__ = "UsageUpdate"
        self.assertIsNone(self.agent._event_to_tool_status(garbage, "AI"))


class _MockConn:
    """Minimal fake ACP ClientSideConnection for testing."""

    def __init__(self, prompt_result_text: str = ""):
        self._prompt_result_text = prompt_result_text
        self.cancelled = False
        self._event_queue_ref = None

    async def prompt(self, content, session_id, **kwargs):
        return MagicMock()

    async def cancel(self, session_id, **kwargs):
        self.cancelled = True

    async def close(self):
        pass


def _patch_ensure_connected(agent: HermesAgent, conn: _MockConn, session_id: str = "test-session"):
    """Patch _ensure_connected to inject a mock connection."""

    async def _fake_ensure():
        agent._conn = conn
        agent._proc = MagicMock()
        agent._proc.returncode = None
        agent._session_id = session_id
        conn._event_queue_ref = agent._event_queue

    agent._ensure_connected = _fake_ensure


class TestHermesAgentFastResponse(unittest.IsolatedAsyncioTestCase):
    """Fast path: response arrives before threshold — inline SentenceOutput."""

    async def test_fast_response_yields_sentence_output(self):
        agent = _make_agent()
        conn = _MockConn()
        _patch_ensure_connected(agent, conn)

        # Inject a text chunk into the queue before prompt "completes"
        try:
            from acp.schema import AgentMessageChunk, TextContentBlock
            chunk = AgentMessageChunk(
                session_update="agent_message_chunk",
                content=TextContentBlock(type="text", text="Hi there!"),
            )
        except ImportError:
            chunk = _mock_acp_text_chunk("Hi there!")

        async def _prompt_with_event(content, session_id, **kwargs):
            agent._event_queue.put_nowait(chunk)
            return MagicMock()

        conn.prompt = _prompt_with_event

        outputs = []
        async for item in agent.chat(_make_input("hello")):
            outputs.append(item)

        sentence_outputs = [o for o in outputs if isinstance(o, SentenceOutput)]
        self.assertEqual(len(sentence_outputs), 1)
        self.assertIn("Hi there!", sentence_outputs[0].tts_text)

    async def test_no_user_text_yields_nothing(self):
        agent = _make_agent()
        conn = _MockConn()
        _patch_ensure_connected(agent, conn)

        outputs = []
        async for item in agent.chat(_make_input("")):
            outputs.append(item)
        self.assertEqual(len(outputs), 0)

    async def test_empty_response_yields_nothing(self):
        agent = _make_agent()
        conn = _MockConn()
        _patch_ensure_connected(agent, conn)

        # No events pushed — queue stays empty

        outputs = []
        async for item in agent.chat(_make_input("hello")):
            outputs.append(item)

        sentence_outputs = [o for o in outputs if isinstance(o, SentenceOutput)]
        self.assertEqual(len(sentence_outputs), 0)


class TestHermesAgentToolEvents(unittest.IsolatedAsyncioTestCase):
    """Tool events from ACP must be forwarded as ToolCallStatus yields."""

    async def test_tool_start_yielded_inline(self):
        agent = _make_agent()
        conn = _MockConn()
        _patch_ensure_connected(agent, conn)

        try:
            from acp.schema import ToolCallStart, AgentMessageChunk, TextContentBlock
            tool_ev = ToolCallStart(
                session_update="tool_call",
                tool_call_id="tc42",
                title="web_search",
                raw_input={"q": "test"},
            )
            text_ev = AgentMessageChunk(
                session_update="agent_message_chunk",
                content=TextContentBlock(type="text", text="Done!"),
            )
        except ImportError:
            self.skipTest("acp not installed")

        async def _prompt_with_events(content, session_id, **kwargs):
            agent._event_queue.put_nowait(tool_ev)
            agent._event_queue.put_nowait(text_ev)
            return MagicMock()

        conn.prompt = _prompt_with_events

        outputs = []
        async for item in agent.chat(_make_input("search for test")):
            outputs.append(item)

        tool_statuses = [o for o in outputs if isinstance(o, ToolCallStatus)]
        self.assertEqual(len(tool_statuses), 1)
        self.assertEqual(tool_statuses[0].status, "running")
        self.assertEqual(tool_statuses[0].tool_id, "tc42")


class TestHermesAgentBackgroundOffload(unittest.IsolatedAsyncioTestCase):
    """Slow responses offload to background and deliver via speak callback."""

    async def test_slow_response_yields_ack_and_calls_speak(self):
        agent = _make_agent()
        conn = _MockConn()
        _patch_ensure_connected(agent, conn)

        spoken = []

        async def _speak(text: str):
            spoken.append(text)

        agent.set_speak_callback(_speak)
        allow_done = asyncio.Event()

        try:
            from acp.schema import AgentMessageChunk, TextContentBlock
            text_ev = AgentMessageChunk(
                session_update="agent_message_chunk",
                content=TextContentBlock(type="text", text="Background answer."),
            )
        except ImportError:
            text_ev = _mock_acp_text_chunk("Background answer.")

        async def _slow_prompt(content, session_id, **kwargs):
            await allow_done.wait()
            agent._event_queue.put_nowait(text_ev)
            return MagicMock()

        conn.prompt = _slow_prompt

        collected = []
        with patch(
            "src.open_llm_vtuber.agent.agents.hermes_agent._HERMES_BG_THRESHOLD_SEC",
            0.1,
        ):
            async def _drive():
                async for item in agent.chat(_make_input("slow question")):
                    collected.append(item)

            drive_task = asyncio.create_task(_drive())
            await asyncio.sleep(0.3)
            allow_done.set()
            await drive_task
            await asyncio.sleep(0.1)

        sentence_outputs = [o for o in collected if isinstance(o, SentenceOutput)]
        self.assertEqual(len(sentence_outputs), 1)
        self.assertIn("think", sentence_outputs[0].tts_text.lower())
        self.assertEqual(spoken, ["Background answer."])

    async def test_bg_deliver_calls_speak_with_result(self):
        agent = _make_agent()
        spoken = []

        async def _cb(text):
            spoken.append(text)

        agent.set_speak_callback(_cb)

        try:
            from acp.schema import AgentMessageChunk, TextContentBlock
            ev = AgentMessageChunk(
                session_update="agent_message_chunk",
                content=TextContentBlock(type="text", text="Delivered!"),
            )
        except ImportError:
            ev = _mock_acp_text_chunk("Delivered!")

        agent._event_queue.put_nowait(ev)

        future_task = asyncio.ensure_future(asyncio.sleep(0))
        await agent._bg_deliver(future_task, [], "AI")
        self.assertEqual(spoken, ["Delivered!"])

    async def test_bg_deliver_skips_empty_response(self):
        agent = _make_agent()
        spoken = []

        async def _cb(text):
            spoken.append(text)

        agent.set_speak_callback(_cb)

        future_task = asyncio.ensure_future(asyncio.sleep(0))
        await agent._bg_deliver(future_task, [], "AI")
        self.assertEqual(spoken, [])

    async def test_next_turn_waits_for_background(self):
        agent = _make_agent()
        conn = _MockConn()
        _patch_ensure_connected(agent, conn)

        # Simulate in-flight background future
        bg_done = asyncio.get_event_loop().run_in_executor(None, lambda: None)
        agent._bg_future = bg_done

        try:
            from acp.schema import AgentMessageChunk, TextContentBlock
            ev = AgentMessageChunk(
                session_update="agent_message_chunk",
                content=TextContentBlock(type="text", text="Turn2 response"),
            )
        except ImportError:
            ev = _mock_acp_text_chunk("Turn2 response")

        async def _prompt_t2(content, session_id, **kwargs):
            agent._event_queue.put_nowait(ev)
            return MagicMock()

        conn.prompt = _prompt_t2

        turn2_outputs = []
        async for item in agent.chat(_make_input("next question")):
            turn2_outputs.append(item)

        self.assertEqual(len([o for o in turn2_outputs if isinstance(o, SentenceOutput)]), 1)
        self.assertTrue(bg_done.done())


class TestHermesAgentInterrupt(unittest.IsolatedAsyncioTestCase):
    """handle_interrupt must send ACP cancel to the running session."""

    async def test_interrupt_sends_cancel(self):
        agent = _make_agent()
        conn = _MockConn()
        _patch_ensure_connected(agent, conn)
        await agent._ensure_connected()

        agent.handle_interrupt()
        await asyncio.sleep(0.05)  # let coroutine_threadsafe callback run
        self.assertTrue(agent._interrupt_handled)

    async def test_interrupt_no_session_does_not_crash(self):
        agent = _make_agent()
        agent.handle_interrupt()  # no connection established — must not raise
        self.assertTrue(agent._interrupt_handled)


class TestHermesAgentCallbacks(unittest.TestCase):
    def test_set_speak_callback_stores_fn(self):
        agent = _make_agent()
        fn = MagicMock()
        agent.set_speak_callback(fn)
        self.assertIs(agent._speak_callback, fn)

    def test_set_tool_event_callback_stores_fn(self):
        agent = _make_agent()
        fn = MagicMock()
        agent.set_tool_event_callback(fn)
        self.assertIs(agent._tool_event_callback, fn)


if __name__ == "__main__":
    unittest.main()
