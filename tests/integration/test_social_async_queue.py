"""Integration tests for async social tool queue behavior.

Covers Discord/Twitter tools routed through ToolExecutor's async queue path:
1. Immediate placeholder response (non-blocking)
2. Deferred completion websocket event from poller
"""

import json
import sys
import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.open_llm_vtuber.mcpp.tool_executor import ToolExecutor
from src.open_llm_vtuber.mcpp.tool_manager import ToolManager
from src.open_llm_vtuber.mcpp.types import FormattedTool

# Add src/ so bare 'from open_llm_vtuber.*' imports inside ToolExecutor work
_src = str(Path(__file__).parent.parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)


async def _collect(executor: ToolExecutor, tool_calls: list, mode: str = "OpenAI") -> list:
    return [u async for u in executor.execute_tools(tool_calls, mode)]


class TestSocialAsyncQueueIntegration(unittest.IsolatedAsyncioTestCase):
    def _build_executor(self, tool_names: list[str]) -> tuple[ToolExecutor, MagicMock]:
        mock_client = MagicMock()
        mock_client.call_tool = AsyncMock(return_value={
            "metadata": {},
            "content_items": [{"type": "text", "text": "sync fallback result"}],
        })

        manager = ToolManager(
            formatted_tools_openai=[],
            formatted_tools_claude=[],
            initial_tools_dict={
                name: FormattedTool(input_schema={}, related_server="obsidian")
                for name in tool_names
            },
        )

        executor = ToolExecutor(
            mcp_client=mock_client,
            tool_manager=manager,
            obsidian_async_enabled=True,
        )
        return executor, mock_client

    async def test_discord_search_returns_zeus_placeholder_immediately(self):
        executor, mock_client = self._build_executor(["discord_search"])

        mock_queue = MagicMock()
        mock_queue.is_available.return_value = True
        mock_queue.enqueue.return_value = "job-social-1"
        executor._obsidian_queue = mock_queue

        with patch.object(executor, "_poll_obsidian_job", new_callable=AsyncMock) as mock_poll:
            updates = await _collect(
                executor,
                [{"id": "d1", "name": "discord_search", "input": {"query": "chunking"}}],
                "OpenAI",
            )

        mock_client.call_tool.assert_not_called()
        mock_poll.assert_called_once_with(
            job_id="job-social-1",
            origin_tool_name="discord_search",
            origin_tool_id="d1",
        )

        finals = [u for u in updates if u.get("type") == "final_tool_results"]
        self.assertTrue(finals)
        content = finals[0]["results"][0]["content"]
        self.assertIn("ZEUS AGENT", content)

    async def test_poll_finished_emits_completed_event_for_social_tool(self):
        executor, _ = self._build_executor(["discord_search"])

        mock_queue = MagicMock()
        mock_queue.get_result.return_value = ("finished", "Found chonkie details")
        executor._obsidian_queue = mock_queue

        ws_events = []

        async def _capture(data: str):
            ws_events.append(json.loads(data))

        speak = AsyncMock()
        executor._mcp_client._send_text = _capture
        executor._mcp_client._background_result_handler = speak

        await executor._poll_obsidian_job(
            job_id="job-social-2",
            origin_tool_name="discord_search",
            origin_tool_id="d2",
            poll_interval_sec=0.01,
            timeout_sec=1.0,
        )
        await asyncio.sleep(0)

        completed = [e for e in ws_events if e.get("status") == "completed"]
        self.assertTrue(completed)
        self.assertEqual(completed[0]["tool_name"], "discord_search")
        self.assertIn("discord", completed[0]["content"].lower())
        speak.assert_awaited()
        mock_queue.cleanup.assert_called_once_with("job-social-2")


if __name__ == "__main__":
    unittest.main()
