import os
import json
import asyncio
import uuid
from typing import Callable
from loguru import logger
from fastapi import WebSocket

from prompts import prompt_loader
from .live2d_model import Live2dModel
from .asr.asr_interface import ASRInterface
from .tts.tts_interface import TTSInterface
from .vad.vad_interface import VADInterface
from .agent.agents.agent_interface import AgentInterface
from .translate.translate_interface import TranslateInterface

from .asr.asr_factory import ASRFactory
from .tts.tts_factory import TTSFactory
from .vad.vad_factory import VADFactory
from .agent.agent_factory import AgentFactory
from .translate.translate_factory import TranslateFactory

from .config_manager import (
    Config,
    AgentConfig,
    CharacterConfig,
    SystemConfig,
    ASRConfig,
    TTSConfig,
    VADConfig,
    TranslatorConfig,
    read_yaml,
    validate_config,
)


class ServiceContext:
    """Initializes, stores, and updates the asr, tts, and llm instances and other
    configurations for a connected client."""

    def __init__(self):
        self.config: Config = None
        self.system_config: SystemConfig = None
        self.character_config: CharacterConfig = None

        self.live2d_model: Live2dModel = None
        self.asr_engine: ASRInterface = None
        self.tts_engine: TTSInterface = None
        self.agent_engine: AgentInterface = None
        self.vad_engine: VADInterface | None = None
        self.translate_engine: TranslateInterface | None = None

        self.system_prompt: str = None
        self.history_uid: str = ""

        self.send_text: Callable = None
        self.client_uid: str = None
        self._active_turns: int = 0
        self._turn_idle_event: asyncio.Event = asyncio.Event()
        self._turn_idle_event.set()

    def __str__(self):
        return (
            f"ServiceContext:\n"
            f"  System Config: {'Loaded' if self.system_config else 'Not Loaded'}\n"
            f"    Details: {json.dumps(self.system_config.model_dump(), indent=6) if self.system_config else 'None'}\n"
            f"  Live2D Model: {self.live2d_model.model_info if self.live2d_model else 'Not Loaded'}\n"
            f"  ASR Engine: {type(self.asr_engine).__name__ if self.asr_engine else 'Not Loaded'}\n"
            f"    Config: {json.dumps(self.character_config.asr_config.model_dump(), indent=6) if self.character_config.asr_config else 'None'}\n"
            f"  TTS Engine: {type(self.tts_engine).__name__ if self.tts_engine else 'Not Loaded'}\n"
            f"    Config: {json.dumps(self.character_config.tts_config.model_dump(), indent=6) if self.character_config.tts_config else 'None'}\n"
            f"  LLM Engine: {type(self.agent_engine).__name__ if self.agent_engine else 'Not Loaded'}\n"
            f"    Agent Config: {json.dumps(self.character_config.agent_config.model_dump(), indent=6) if self.character_config.agent_config else 'None'}\n"
            f"  VAD Engine: {type(self.vad_engine).__name__ if self.vad_engine else 'Not Loaded'}\n"
            f"    VAD Config: {json.dumps(self.character_config.vad_config.model_dump(), indent=6) if self.character_config.vad_config else 'None'}\n"
            f"  System Prompt: {self.system_prompt or 'Not Set'}\n"
        )

    # ==== Background TTS (used by pi-agent background results)

    async def _speak_background_tool_result(self, text: str) -> None:
        """Speak an async result directly through the current client TTS pipeline."""
        normalized = (text or "").strip()
        if not normalized:
            return
        if self._active_turns > 0:
            try:
                await asyncio.wait_for(self._turn_idle_event.wait(), timeout=120.0)
            except asyncio.TimeoutError:
                return
        if len(normalized) > 700:
            normalized = normalized[:700].rstrip() + " ..."
        if not self.send_text or not self.tts_engine:
            return
        try:
            from .agent.output_types import DisplayText, Actions
            from .conversations.tts_manager import TTSTaskManager

            display_text = DisplayText(
                text=normalized,
                name=self.character_config.character_name if self.character_config else "AI",
                avatar=self.character_config.avatar if self.character_config else None,
            )
            tts_manager = TTSTaskManager(turn_id=f"bg_{uuid.uuid4().hex[:8]}")
            await tts_manager.speak(
                tts_text=normalized,
                display_text=display_text,
                actions=Actions(expressions=["neutral"]),
                live2d_model=self.live2d_model,
                tts_engine=self.tts_engine,
                websocket_send=self.send_text,
            )
            if tts_manager.task_list:
                await asyncio.gather(*tts_manager.task_list)
                await self.send_text(json.dumps({"type": "backend-synth-complete"}))
            await self.send_text(json.dumps({"type": "force-new-message"}))
            tts_manager.clear()
        except Exception as exc:
            logger.exception(f"Failed to speak background result: {exc}")

    async def _send_bg_tool_event(self, event: "ToolCallStatus") -> None:
        """Forward a background tool event to the frontend WebSocket."""
        if self.send_text:
            try:
                await self.send_text(event.model_dump_json(exclude_none=False))
            except Exception:
                pass

    def mark_turn_start(self) -> None:
        self._active_turns += 1
        self._turn_idle_event.clear()

    def mark_turn_end(self) -> None:
        self._active_turns = max(0, self._active_turns - 1)
        if self._active_turns == 0:
            self._turn_idle_event.set()

    async def wait_until_turn_idle(self, timeout_sec: float = 60.0) -> None:
        try:
            await asyncio.wait_for(self._turn_idle_event.wait(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for turn idle for client {self.client_uid}.")

    async def close(self):
        logger.info("Closing ServiceContext resources...")
        if self.agent_engine and hasattr(self.agent_engine, "close"):
            await self.agent_engine.close()
        logger.info("ServiceContext closed.")

    # ==== Loaders

    async def load_cache(
        self,
        config: Config,
        system_config: SystemConfig,
        character_config: CharacterConfig,
        live2d_model: Live2dModel,
        asr_engine: ASRInterface,
        tts_engine: TTSInterface,
        vad_engine: VADInterface,
        agent_engine: AgentInterface,
        translate_engine: TranslateInterface | None,
        send_text: Callable = None,
        client_uid: str = None,
        # Legacy MCP params accepted but ignored
        mcp_server_registery=None,
        tool_adapter=None,
    ) -> None:
        """Load the ServiceContext with provided instances (pass-by-reference)."""
        if not character_config:
            raise ValueError("character_config cannot be None")
        if not system_config:
            raise ValueError("system_config cannot be None")

        self.config = config
        self.system_config = system_config
        self.character_config = character_config
        self.live2d_model = live2d_model
        self.asr_engine = asr_engine
        self.tts_engine = tts_engine
        self.vad_engine = vad_engine
        self.agent_engine = agent_engine
        self.translate_engine = translate_engine
        self.send_text = send_text
        self.client_uid = client_uid

        logger.debug(f"Loaded service context with cache: {character_config}")

    async def load_from_config(self, config: Config) -> None:
        """Load/reinitialize the ServiceContext from a Config object."""
        if not self.config:
            self.config = config
        if not self.system_config:
            self.system_config = config.system_config
        if not self.character_config:
            self.character_config = config.character_config

        self.init_live2d(config.character_config.live2d_model_name)
        self.init_asr(config.character_config.asr_config)
        self.init_tts(config.character_config.tts_config)
        self.init_vad(config.character_config.vad_config)

        await self.init_agent(
            config.character_config.agent_config,
            config.character_config.persona_prompt,
        )

        self.init_translate(
            config.character_config.tts_preprocessor_config.translator_config
        )

        self.config = config
        self.system_config = config.system_config or self.system_config
        self.character_config = config.character_config

    def init_live2d(self, live2d_model_name: str) -> None:
        logger.info(f"Initializing Live2D: {live2d_model_name}")
        try:
            self.live2d_model = Live2dModel(live2d_model_name)
            self.character_config.live2d_model_name = live2d_model_name
        except Exception as e:
            self.live2d_model = None
            logger.critical(f"Error initializing Live2D: {e}")
            logger.critical("Try to proceed without Live2D...")

    def init_asr(self, asr_config: ASRConfig) -> None:
        if not self.asr_engine or (self.character_config.asr_config != asr_config):
            logger.info(f"Initializing ASR: {asr_config.asr_model}")
            self.asr_engine = ASRFactory.get_asr_system(
                asr_config.asr_model,
                **getattr(asr_config, asr_config.asr_model).model_dump(),
            )
            self.character_config.asr_config = asr_config
        else:
            logger.info("ASR already initialized with the same config.")

    def init_tts(self, tts_config: TTSConfig) -> None:
        if not self.tts_engine or (self.character_config.tts_config != tts_config):
            logger.info(f"Initializing TTS: {tts_config.tts_model}")
            self.tts_engine = TTSFactory.get_tts_engine(
                tts_config.tts_model,
                **getattr(tts_config, tts_config.tts_model.lower()).model_dump(),
            )
            self.character_config.tts_config = tts_config
        else:
            logger.info("TTS already initialized with the same config.")

    def init_vad(self, vad_config: VADConfig) -> None:
        if vad_config.vad_model is None:
            logger.info("VAD is disabled.")
            self.vad_engine = None
            return
        if not self.vad_engine or (self.character_config.vad_config != vad_config):
            logger.info(f"Initializing VAD: {vad_config.vad_model}")
            self.vad_engine = VADFactory.get_vad_engine(
                vad_config.vad_model,
                **getattr(vad_config, vad_config.vad_model.lower()).model_dump(),
            )
            self.character_config.vad_config = vad_config
        else:
            logger.info("VAD already initialized with the same config.")

    async def init_agent(self, agent_config: AgentConfig, persona_prompt: str) -> None:
        logger.info(f"Initializing Agent: {agent_config.conversation_agent_choice}")

        if (
            self.agent_engine is not None
            and agent_config == self.character_config.agent_config
            and persona_prompt == self.character_config.persona_prompt
        ):
            logger.debug("Agent already initialized with the same config.")
            return

        system_prompt = await self.construct_system_prompt(persona_prompt)
        avatar = self.character_config.avatar or ""

        try:
            self.agent_engine = AgentFactory.create_agent(
                conversation_agent_choice=agent_config.conversation_agent_choice,
                agent_settings=agent_config.agent_settings.model_dump(),
                system_prompt=system_prompt,
                live2d_model=self.live2d_model,
                tts_preprocessor_config=self.character_config.tts_preprocessor_config,
                character_avatar=avatar,
                system_config=self.system_config.model_dump(),
            )
            self.character_config.agent_config = agent_config
            self.system_prompt = system_prompt

            if hasattr(self.agent_engine, "set_speak_callback"):
                self.agent_engine.set_speak_callback(self._speak_background_tool_result)
            if hasattr(self.agent_engine, "set_tool_event_callback"):
                self.agent_engine.set_tool_event_callback(self._send_bg_tool_event)
        except Exception as e:
            logger.error(f"Failed to initialize agent: {e}")
            raise

    def init_translate(self, translator_config: TranslatorConfig) -> None:
        if not translator_config.translate_audio:
            logger.debug("Translation is disabled.")
            return
        if (
            not self.translate_engine
            or self.character_config.tts_preprocessor_config.translator_config
            != translator_config
        ):
            logger.info(f"Initializing Translator: {translator_config.translate_provider}")
            self.translate_engine = TranslateFactory.get_translator(
                translator_config.translate_provider,
                getattr(translator_config, translator_config.translate_provider).model_dump(),
            )
            self.character_config.tts_preprocessor_config.translator_config = translator_config
        else:
            logger.info("Translation already initialized with the same config.")

    # ==== Utils

    async def construct_system_prompt(self, persona_prompt: str) -> str:
        logger.debug(f"constructing persona_prompt: '''{persona_prompt}'''")

        for prompt_name, prompt_file in self.system_config.tool_prompts.items():
            if prompt_name in ("group_conversation_prompt", "proactive_speak_prompt", "mcp_prompt"):
                continue

            prompt_content = prompt_loader.load_util(prompt_file)

            if prompt_name == "live2d_expression_prompt":
                if self.live2d_model is None:
                    logger.warning("Skipping live2d_expression_prompt: no Live2D model loaded.")
                    continue
                prompt_content = prompt_content.replace(
                    "[<insert_emomap_keys>]", self.live2d_model.emo_str
                )

            persona_prompt += prompt_content

        logger.debug("\n === System Prompt ===")
        logger.debug(persona_prompt)
        return persona_prompt

    async def apply_config_file(self, config_file_name: str) -> None:
        """Load a config file and update service context engines silently."""
        if config_file_name == "conf.yaml":
            new_character_config_data = read_yaml("conf.yaml").get("character_config")
        else:
            characters_dir = self.system_config.config_alts_dir
            file_path = os.path.normpath(os.path.join(characters_dir, config_file_name))
            if not file_path.startswith(characters_dir):
                raise ValueError("Invalid configuration file path")
            alt_config_data = self._load_and_validate_alt_character_config(file_path)
            new_character_config_data = deep_merge(
                self.config.character_config.model_dump(), alt_config_data
            )
        if new_character_config_data:
            new_config = {
                "system_config": self.system_config.model_dump(),
                "character_config": new_character_config_data,
            }
            await self.load_from_config(validate_config(new_config))

    async def handle_config_switch(self, websocket: WebSocket, config_file_name: str) -> None:
        try:
            if config_file_name == "conf.yaml":
                new_character_config_data = read_yaml("conf.yaml").get("character_config")
            else:
                characters_dir = self.system_config.config_alts_dir
                file_path = os.path.normpath(os.path.join(characters_dir, config_file_name))
                if not file_path.startswith(characters_dir):
                    raise ValueError("Invalid configuration file path")
                alt_config_data = self._load_and_validate_alt_character_config(file_path)
                new_character_config_data = deep_merge(
                    self.config.character_config.model_dump(), alt_config_data
                )

            if new_character_config_data:
                new_config = {
                    "system_config": self.system_config.model_dump(),
                    "character_config": new_character_config_data,
                }
                await self.load_from_config(validate_config(new_config))
                logger.debug(f"New config: {self}")

                await websocket.send_text(json.dumps({
                    "type": "set-model-and-conf",
                    "model_info": self.live2d_model.model_info if self.live2d_model else None,
                    "conf_name": self.character_config.conf_name,
                    "conf_uid": self.character_config.conf_uid,
                }))
                await websocket.send_text(json.dumps({
                    "type": "config-switched",
                    "message": f"Switched to config: {config_file_name}",
                }))
                logger.info(f"Configuration switched to {config_file_name}")
            else:
                raise ValueError(f"Failed to load configuration from {config_file_name}")

        except Exception as e:
            logger.error(f"Error switching configuration: {e}")
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": f"Error switching configuration: {str(e)}",
            }))
            raise e

    def _load_and_validate_alt_character_config(self, file_path: str) -> dict:
        loaded = read_yaml(file_path) or {}
        alt_config_data = loaded.get("character_config")
        if not isinstance(alt_config_data, dict):
            raise ValueError(
                f"Invalid character config in {file_path}: missing 'character_config' object."
            )
        persona_prompt = alt_config_data.get("persona_prompt")
        if not isinstance(persona_prompt, str) or not persona_prompt.strip():
            raise ValueError(
                f"Invalid character config in {file_path}: "
                "'character_config.persona_prompt' must be explicitly set and non-empty."
            )
        return alt_config_data


def deep_merge(dict1, dict2):
    """Recursively merges dict2 into dict1, prioritizing values from dict2."""
    result = dict1.copy()
    for key, value in dict2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result
