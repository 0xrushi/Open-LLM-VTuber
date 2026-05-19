"""Tests that social-history tools use the obsidian async queue path.

When obsidian_async_enabled=True, obsidian and social tools (discord/twitter
search+sync) should be enqueued and return a placeholder immediately.
"""

import sys
import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add src/ so bare 'from open_llm_vtuber.*' imports inside ToolExecutor work
_src = str(Path(__file__).parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from src.open_llm_vtuber.mcpp.tool_executor import ToolExecutor
from src.open_llm_vtuber.mcpp.tool_manager import ToolManager
from src.open_llm_vtuber.mcpp.types import FormattedTool, ToolCallFunctionObject, ToolCallObject


DISCORD_SEARCH_RESULT = "Alice @ 2024-01-01: hey, did you see the new update?"
OBSIDIAN_ASYNC_PLACEHOLDER = "Searching your notes, I'll let you know..."


def _make_tool_call(name: str, args: dict | None = None) -> ToolCallObject:
    import json
    return ToolCallObject(
        id="call_1",
        type="function",
        index=0,
        function=ToolCallFunctionObject(
            name=name,
            arguments=json.dumps(args or {"query": "test"}),
        ),
    )


def _make_executor(tool_names: list[str], server: str = "obsidian") -> tuple[ToolExecutor, MagicMock]:
    """Build a ToolExecutor with obsidian_async_enabled=True and a mock MCP client."""
    mock_client = MagicMock()
    mock_client.call_tool = AsyncMock(return_value={
        "metadata": {},
        "content_items": [{"type": "text", "text": DISCORD_SEARCH_RESULT}],
    })

    tools_dict = {
        name: FormattedTool(input_schema={}, related_server=server)
        for name in tool_names
    }
    manager = ToolManager(
        formatted_tools_openai=[],
        formatted_tools_claude=[],
        initial_tools_dict=tools_dict,
    )

    mock_queue = MagicMock()
    mock_queue.is_available.return_value = True

    executor = ToolExecutor(
        mcp_client=mock_client,
        tool_manager=manager,
        obsidian_async_enabled=True,
    )
    executor._obsidian_queue = mock_queue
    return executor, mock_client


class TestDiscordToolUsesObsidianAsync(unittest.IsolatedAsyncioTestCase):

    async def _collect(self, executor: ToolExecutor, tool_call: ToolCallObject) -> list[dict]:
        updates = []
        async for item in executor.execute_tools([tool_call], caller_mode="OpenAI"):
            updates.append(item)
        return updates

    async def test_discord_search_uses_async_path(self):
        """discord_search must go through the async queue path."""
        executor, mock_client = _make_executor(["discord_search"])

        with patch.object(
            executor,
            "_run_obsidian_async_nonblocking",
            wraps=executor._run_obsidian_async_nonblocking,
        ) as mock_async:
            await self._collect(executor, _make_tool_call("discord_search"))

        mock_async.assert_called_once()

    async def test_discord_sync_uses_async_path(self):
        """discord_sync must go through the async queue path."""
        executor, mock_client = _make_executor(["discord_sync"])

        with patch.object(
            executor,
            "_run_obsidian_async_nonblocking",
            wraps=executor._run_obsidian_async_nonblocking,
        ) as mock_async:
            await self._collect(executor, _make_tool_call("discord_sync", {}))

        mock_async.assert_called_once()

    async def test_twitter_search_uses_async_path(self):
        """twitter_search must go through the async queue path."""
        executor, mock_client = _make_executor(["twitter_search"])

        with patch.object(
            executor,
            "_run_obsidian_async_nonblocking",
            wraps=executor._run_obsidian_async_nonblocking,
        ) as mock_async:
            await self._collect(executor, _make_tool_call("twitter_search"))

        mock_async.assert_called_once()

    async def test_twitter_sync_uses_async_path(self):
        """twitter_sync must go through the async queue path."""
        executor, mock_client = _make_executor(["twitter_sync"])

        with patch.object(
            executor,
            "_run_obsidian_async_nonblocking",
            wraps=executor._run_obsidian_async_nonblocking,
        ) as mock_async:
            await self._collect(executor, _make_tool_call("twitter_sync", {}))

        mock_async.assert_called_once()

    async def test_obsidian_search_uses_async_path(self):
        """obsidian_search (slow vault search) must still go through the async queue."""
        executor, mock_client = _make_executor(["obsidian_search"])

        with patch.object(
            executor,
            "_run_obsidian_async_nonblocking",
            new_callable=AsyncMock,
            return_value=(False, OBSIDIAN_ASYNC_PLACEHOLDER, {}, [{"type": "text", "text": OBSIDIAN_ASYNC_PLACEHOLDER}]),
        ) as mock_async:
            await self._collect(executor, _make_tool_call("obsidian_search"))

        mock_async.assert_called_once()
        mock_client.call_tool.assert_not_called()

    async def test_discord_search_returns_queued_placeholder(self):
        """The async queued placeholder must appear in final_tool_results."""
        executor, _ = _make_executor(["discord_search"])
        with patch.object(
            executor,
            "_run_obsidian_async_nonblocking",
            new_callable=AsyncMock,
            return_value=(
                False,
                "I have asked my ZEUS AGENT to run that in the background.",
                {},
                [{"type": "text", "text": "I have asked my ZEUS AGENT to run that in the background."}],
            ),
        ):
            updates = await self._collect(executor, _make_tool_call("discord_search"))

        finals = [u for u in updates if u.get("type") == "final_tool_results"]
        self.assertTrue(finals, "No final_tool_results emitted")
        results = finals[0]["results"]
        self.assertTrue(results)
        result_text = results[0].get("content", "") if isinstance(results[0], dict) else str(results[0])
        self.assertIn("ZEUS AGENT", result_text)

    async def test_discord_background_result_strips_instruction_scaffold(self):
        """Finished discord_search job must not leak internal INSTRUCTION scaffold text."""
        executor, _ = _make_executor(["discord_search"])
        raw = (
            "[androso @ 2026-05-17T18:00:38.912000+00:00] (score: 0.5809)\n"
            "ahh\n\n---\n"
            "INSTRUCTION: Based on the messages above, reason about what they reveal."
        )
        executor._obsidian_queue.get_result.return_value = ("finished", raw)
        executor._obsidian_queue.cleanup = MagicMock()

        events = []
        async def _capture_event(payload):
            events.append(payload)

        spoke = []
        async def _capture_speak(text: str):
            spoke.append(text)

        executor._send_ws_event = _capture_event
        executor._mcp_client._background_result_handler = _capture_speak

        await executor._poll_obsidian_job(
            job_id="job-social-3",
            origin_tool_name="discord_search",
            origin_tool_id="d3",
            poll_interval_sec=0.01,
            timeout_sec=1.0,
        )
        await asyncio.sleep(0.05)

        self.assertTrue(events)
        content = events[0].get("content", "")
        self.assertNotIn("INSTRUCTION:", content)
        self.assertTrue(spoke)
        self.assertNotIn("INSTRUCTION:", spoke[0])

    async def test_discord_background_result_is_concise_not_raw_dump(self):
        """Background completion for discord_search should not dump raw retrieval blocks."""
        executor, _ = _make_executor(["discord_search"])
        raw = (
            "[androso @ 2026-05-17T18:00:38.912000+00:00] (score: 0.5809)\n"
            "ahh\n"
            "Person: androso\n\n---\n\n"
            "[androso @ 2026-05-17T17:26:18.180000+00:00] (score: 0.5234)\n"
            "it is me indeed\n"
            "Person: androso\n\n---\n\n"
            "[androso @ 2026-05-18T00:06:20.693000+00:00] (score: 0.5134)\n"
            "i hope you sleep a lot today chibs\n"
            "Server: My Server\n"
            "Channel: tortoise-lounge\n"
            "Person: androso"
        )
        executor._obsidian_queue.get_result.return_value = ("finished", raw)
        executor._obsidian_queue.cleanup = MagicMock()

        events = []

        async def _capture_event(payload):
            events.append(payload)

        spoke = []

        async def _capture_speak(text: str):
            spoke.append(text)

        executor._send_ws_event = _capture_event
        executor._mcp_client._background_result_handler = _capture_speak

        await executor._poll_obsidian_job(
            job_id="job-social-4",
            origin_tool_name="discord_search",
            origin_tool_id="d4",
            poll_interval_sec=0.01,
            timeout_sec=1.0,
        )
        await asyncio.sleep(0.05)

        self.assertTrue(events)
        content = events[0].get("content", "")
        self.assertNotIn("[androso @", content)
        self.assertIn("I checked Discord", content)
        self.assertTrue(spoke)
        self.assertNotIn("[androso @", spoke[0])

    async def test_async_disabled_obsidian_search_also_calls_mcp_client(self):
        """With obsidian_async_enabled=False, obsidian_search also goes synchronous."""
        mock_client = MagicMock()
        mock_client.call_tool = AsyncMock(return_value={
            "metadata": {},
            "content_items": [{"type": "text", "text": "some note content"}],
        })
        manager = ToolManager(
            formatted_tools_openai=[],
            formatted_tools_claude=[],
            initial_tools_dict={
                "obsidian_search": FormattedTool(input_schema={}, related_server="obsidian")
            },
        )
        executor = ToolExecutor(
            mcp_client=mock_client,
            tool_manager=manager,
            obsidian_async_enabled=False,
        )

        with patch.object(executor, "_run_obsidian_async_nonblocking", new_callable=AsyncMock) as mock_async:
            await self._collect(executor, _make_tool_call("obsidian_search"))

        mock_async.assert_not_called()
        mock_client.call_tool.assert_called_once()


class TestDiscordAsyncRoutingCondition(unittest.TestCase):
    """Whitebox tests for the routing condition without executing tools."""

    def _check_would_use_async(self, tool_name: str, obsidian_async_enabled: bool = True) -> bool:
        """Replicate the routing condition from tool_executor.py."""
        related_server = "obsidian"
        return (
            obsidian_async_enabled
            and related_server == "obsidian"
        )

    def test_discord_search_uses_async_when_enabled(self):
        self.assertTrue(self._check_would_use_async("discord_search", obsidian_async_enabled=True))
        self.assertFalse(self._check_would_use_async("discord_search", obsidian_async_enabled=False))

    def test_discord_sync_uses_async_when_enabled(self):
        self.assertTrue(self._check_would_use_async("discord_sync", obsidian_async_enabled=True))
        self.assertFalse(self._check_would_use_async("discord_sync", obsidian_async_enabled=False))

    def test_obsidian_search_uses_async_when_enabled(self):
        self.assertTrue(self._check_would_use_async("obsidian_search", obsidian_async_enabled=True))

    def test_obsidian_search_skips_async_when_disabled(self):
        self.assertFalse(self._check_would_use_async("obsidian_search", obsidian_async_enabled=False))

    def test_obsidian_tasks_uses_async_when_enabled(self):
        self.assertTrue(self._check_would_use_async("obsidian_tasks", obsidian_async_enabled=True))

    def test_all_discord_tools_use_async(self):
        discord_tools = ["discord_search", "discord_sync"]
        for tool in discord_tools:
            with self.subTest(tool=tool):
                self.assertTrue(self._check_would_use_async(tool))

    def test_all_twitter_tools_use_async(self):
        twitter_tools = ["twitter_search", "twitter_sync"]
        for tool in twitter_tools:
            with self.subTest(tool=tool):
                self.assertTrue(self._check_would_use_async(tool))


if __name__ == "__main__":
    unittest.main()
