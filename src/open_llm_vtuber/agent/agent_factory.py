from typing import Type
from loguru import logger

from .agents.agent_interface import AgentInterface
from .agents.pi_agent import PiAgent
from typing import Optional


class AgentFactory:
    @staticmethod
    def create_agent(
        conversation_agent_choice: str,
        agent_settings: dict,
        system_prompt: str,
        live2d_model=None,
        tts_preprocessor_config=None,
        **kwargs,
    ) -> Type[AgentInterface]:
        logger.info(f"Initializing agent: {conversation_agent_choice}")

        if conversation_agent_choice == "pi_agent":
            pi_settings = agent_settings.get("pi_agent") or {}
            return PiAgent(
                system=system_prompt,
                live2d_model=live2d_model,
                tts_preprocessor_config=tts_preprocessor_config,
                faster_first_response=pi_settings.get("faster_first_response", True),
                segment_method=pi_settings.get("segment_method", "pysbd"),
                interrupt_method=pi_settings.get("interrupt_method", "user"),
                vision_engine=kwargs.get("vision_engine"),
                pi_session_dir=pi_settings.get("pi_session_dir"),
            )

        raise ValueError(f"Unsupported agent type: {conversation_agent_choice}")
