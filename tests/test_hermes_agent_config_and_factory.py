import unittest

from src.open_llm_vtuber.agent.agent_factory import AgentFactory
from src.open_llm_vtuber.agent.agents.hermes_agent import HermesAgent
from src.open_llm_vtuber.config_manager.agent import AgentConfig


class TestHermesAgentConfig(unittest.TestCase):
    def test_agent_config_allows_hermes_choice(self):
        cfg = AgentConfig.model_validate(
            {
                "conversation_agent_choice": "hermes_agent",
                "agent_settings": {
                    "hermes_agent": {
                        "hermes_bin": "hermes",
                        "hermes_cwd": "/tmp/hermes_work",
                    }
                },
            }
        )
        self.assertEqual(cfg.conversation_agent_choice, "hermes_agent")
        self.assertEqual(cfg.agent_settings.hermes_agent.hermes_bin, "hermes")
        self.assertEqual(cfg.agent_settings.hermes_agent.hermes_cwd, "/tmp/hermes_work")

    def test_agent_config_hermes_defaults(self):
        cfg = AgentConfig.model_validate(
            {
                "conversation_agent_choice": "hermes_agent",
                "agent_settings": {"hermes_agent": {}},
            }
        )
        self.assertIsNone(cfg.agent_settings.hermes_agent.hermes_bin)
        self.assertIsNone(cfg.agent_settings.hermes_agent.hermes_cwd)


class TestHermesAgentFactory(unittest.TestCase):
    def test_factory_creates_hermes_agent(self):
        agent = AgentFactory.create_agent(
            conversation_agent_choice="hermes_agent",
            agent_settings={
                "hermes_agent": {
                    "hermes_bin": "hermes",
                    "hermes_cwd": "/tmp/hermes_work",
                }
            },
            system_prompt="You are test",
            live2d_model=None,
            tts_preprocessor_config=None,
        )
        self.assertIsInstance(agent, HermesAgent)

    def test_factory_hermes_passes_cwd(self):
        agent = AgentFactory.create_agent(
            conversation_agent_choice="hermes_agent",
            agent_settings={"hermes_agent": {"hermes_cwd": "/custom/cwd"}},
            system_prompt="test",
        )
        self.assertEqual(agent._hermes_cwd, "/custom/cwd")

