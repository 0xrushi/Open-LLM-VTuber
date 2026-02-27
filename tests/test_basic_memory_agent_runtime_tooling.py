import unittest

from src.open_llm_vtuber.agent.agents.basic_memory_agent import BasicMemoryAgent
from src.open_llm_vtuber.mcpp.tool_manager import ToolManager


class DummyLLM:
    async def chat_completion(self, *args, **kwargs):
        if False:
            yield ""


class TestBasicMemoryAgentRuntimeTooling(unittest.TestCase):
    def test_set_runtime_tooling_rebinds_tools_and_prompt(self):
        agent = BasicMemoryAgent(
            llm=DummyLLM(),
            system="test",
            live2d_model=None,
            use_mcpp=True,
        )

        manager = ToolManager(
            formatted_tools_openai=[{"type": "function", "function": {"name": "openclaw_chat"}}],
            formatted_tools_claude=[{"name": "openclaw_chat"}],
            initial_tools_dict={},
        )

        agent.set_runtime_tooling(
            tool_manager=manager,
            tool_executor=None,
            mcp_prompt_string="runtime prompt",
        )

        self.assertIs(agent._tool_manager, manager)
        self.assertEqual(agent._mcp_prompt_string, "runtime prompt")
        self.assertEqual(len(agent._formatted_tools_openai), 1)
        self.assertEqual(len(agent._formatted_tools_claude), 1)


if __name__ == "__main__":
    unittest.main()
