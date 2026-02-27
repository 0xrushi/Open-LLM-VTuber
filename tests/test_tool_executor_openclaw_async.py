import asyncio
import json
import unittest

from src.open_llm_vtuber.mcpp.tool_executor import ToolExecutor
from src.open_llm_vtuber.mcpp.tool_manager import ToolManager
from src.open_llm_vtuber.mcpp.types import FormattedTool, ToolCallFunctionObject, ToolCallObject


class FakeMCPClient:
    def __init__(self):
        self.sent_events = []
        self.spoken_results = []
        self.calls = []

    async def _send_text(self, payload: str):
        self.sent_events.append(json.loads(payload))

    async def _background_result_handler(self, text: str):
        self.spoken_results.append(text)

    async def call_tool(self, server_name: str, tool_name: str, tool_args: dict):
        self.calls.append((server_name, tool_name, tool_args))
        if tool_name == "openclaw_chat_async":
            return {
                "metadata": {},
                "content_items": [{"type": "text", "text": '{"task_id":"task_123"}'}],
            }
        if tool_name == "openclaw_task_status":
            return {
                "metadata": {},
                "content_items": [
                    {
                        "type": "text",
                        "text": '{"status":"completed","result":"Boston: cloudy, 30F"}',
                    }
                ],
            }
        raise AssertionError(f"Unexpected tool: {tool_name}")


class TestToolExecutorOpenClawAsync(unittest.IsolatedAsyncioTestCase):
    async def test_execute_tools_openclaw_chat_runs_async_and_emits_background_result(self):
        client = FakeMCPClient()
        manager = ToolManager(
            formatted_tools_openai=[],
            formatted_tools_claude=[],
            initial_tools_dict={
                "openclaw_chat": FormattedTool(input_schema={}, related_server="openclaw")
            },
        )
        executor = ToolExecutor(client, manager)

        tool_call = ToolCallObject(
            id="call_1",
            type="function",
            index=0,
            function=ToolCallFunctionObject(
                name="openclaw_chat",
                arguments='{"message":"weather in boston"}',
            ),
        )

        updates = []
        async for item in executor.execute_tools([tool_call], caller_mode="OpenAI"):
            updates.append(item)

        if executor._background_tasks:
            await asyncio.gather(*list(executor._background_tasks))

        running = [
            u
            for u in updates
            if u.get("type") == "tool_call_status" and u.get("status") == "running"
        ]
        completed = [
            u
            for u in updates
            if u.get("type") == "tool_call_status" and u.get("status") == "completed"
        ]
        finals = [u for u in updates if u.get("type") == "final_tool_results"]

        self.assertTrue(running)
        self.assertTrue(completed)
        self.assertIn("OpenClaw task queued", completed[0]["content"])
        self.assertTrue(finals and finals[0]["results"])

        self.assertTrue(any(call[1] == "openclaw_chat_async" for call in client.calls))
        self.assertTrue(any(call[1] == "openclaw_task_status" for call in client.calls))

        bg_completed_events = [
            e
            for e in client.sent_events
            if e.get("type") == "tool_call_status" and e.get("status") == "completed"
        ]
        self.assertTrue(bg_completed_events)
        self.assertEqual(client.spoken_results, ["Boston: cloudy, 30F"])

    async def test_openclaw_async_nonblocking_requires_message(self):
        client = FakeMCPClient()
        manager = ToolManager(
            initial_tools_dict={
                "openclaw_chat": FormattedTool(input_schema={}, related_server="openclaw")
            }
        )
        executor = ToolExecutor(client, manager)

        is_error, text_content, _, _ = await executor._run_openclaw_chat_async_nonblocking(
            "openclaw_chat", "call_2", {"message": "   "}
        )

        self.assertTrue(is_error)
        self.assertIn("non-empty 'message'", text_content)


if __name__ == "__main__":
    unittest.main()
