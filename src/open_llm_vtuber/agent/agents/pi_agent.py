"""
PiAgent: wraps pi-python-client for the VTuber conversation pipeline.

Handles background tool execution: fast responses come back inline; slow
tool-calling responses yield a quick acknowledgment and deliver the final
answer via _speak_callback when ready.

A SINGLE pi client is kept alive across all turns so conversation history
is preserved. When a turn is offloaded to background, self._bg_future tracks
the in-flight asyncio Task; the next chat() call waits for it before issuing
a new prompt(), ensuring serial access to the pi subprocess.
"""

import asyncio
import json
import os
import time
import uuid
from typing import AsyncIterator, Any, Optional, Callable, Awaitable, Literal
from loguru import logger

from .agent_interface import AgentInterface
from ..output_types import SentenceOutput, DisplayText, Actions, ToolCallStatus
from ..input_types import BaseInput, BatchInput
from ...config_manager import TTSPreprocessorConfig
from ...vision.vision_interface import VisionInterface

# Seconds before a slow tool-calling response is offloaded to background TTS.
_BG_THRESHOLD_SEC = 3.0


class PiAgent(AgentInterface):
    """Agent that uses pi-python-client for all intelligence."""

    def __init__(
        self,
        system: str,
        live2d_model,
        tts_preprocessor_config: TTSPreprocessorConfig = None,
        faster_first_response: bool = True,
        segment_method: str = "pysbd",
        interrupt_method: str = "user",
        vision_engine: Optional[VisionInterface] = None,
        pi_session_dir: str = None,
        runtime: Literal["pi", "hermes"] = "pi",
        runtime_bin: Optional[str] = None,
    ):
        super().__init__()
        self._live2d_model = live2d_model
        self._tts_preprocessor_config = tts_preprocessor_config
        self._faster_first_response = faster_first_response
        self._segment_method = segment_method
        self._interrupt_method = interrupt_method
        self._system_prompt = system
        self._vision_engine = vision_engine
        self._interrupt_handled = False
        self._pi_client = None
        self._runtime = runtime
        self._runtime_bin = runtime_bin or ("hermes" if runtime == "hermes" else "pi")
        default_session_dir = "~/.hermes/vtuber_sessions" if runtime == "hermes" else "~/.pi/vtuber_sessions"
        self._pi_session_dir = pi_session_dir or os.path.expanduser(default_session_dir)
        # Injected by ServiceContext so background results can be spoken.
        self._speak_callback: Optional[Callable[[str], Awaitable[None]]] = None
        # Injected by ServiceContext to forward background tool events to the UI.
        self._tool_event_callback: Optional[Callable[[ToolCallStatus], Awaitable[None]]] = None
        # Tracks an in-flight background future so the next turn waits for it.
        self._bg_future: Optional[asyncio.Future] = None

    def set_speak_callback(self, fn: Callable[[str], Awaitable[None]]) -> None:
        self._speak_callback = fn

    def set_tool_event_callback(self, fn: Callable[[ToolCallStatus], Awaitable[None]]) -> None:
        self._tool_event_callback = fn

    def _create_pi_client(self):
        from ...pi_client import PiClient, PiConfig

        runtime_bin = self._runtime_bin

        class _RuntimeClient(PiClient):
            def _build_cmd(self_inner) -> list[str]:
                cmd = super(_RuntimeClient, self_inner)._build_cmd()
                cmd[0] = runtime_bin
                return cmd

        pi_skill = os.environ.get("PI_SKILL")
        # Multi-skill support (comma-separated): e.g.
        # PI_SKILLS="browseros-pi,mcp,discord-rag-pi,twitter-rag-pi,npm:pi-obsidian"
        # Discord/X retrieval should prefer MCP discord/twitter tools when present.
        pi_skills = os.environ.get(
            "PI_SKILLS",
            "browseros-pi,mcp,discord-rag-pi,twitter-rag-pi,npm:pi-obsidian",
        )
        routing_hint = (
            "\n\n[Tool routing]\n"
            "- For Discord history/db-rag questions, prefer MCP discord tools when available "
            "(obsidianvtuber__discord_search / obsidianvtuber__discord_sync).\n"
            "- For Twitter/X history questions, prefer MCP twitter tools when available "
            "(obsidianvtuber__twitter_search / obsidianvtuber__twitter_sync).\n"
            "- Fallback only if those tools are truly unavailable; do not claim unavailable without checking.\n"
        )

        config = PiConfig(
            provider=os.environ.get("PI_PROVIDER"),
            model=os.environ.get("PI_MODEL"),
            api_key=os.environ.get("PI_API_KEY"),
            tools=os.environ.get("PI_TOOLS"),
            skill=pi_skill if pi_skill else None,
            skills=pi_skills,
            session_dir=self._pi_session_dir,
            append_system_prompt=(self._system_prompt or "") + routing_hint,
        )
        client = _RuntimeClient(config)
        client.start()
        return client

    def _ensure_pi_client(self):
        if self._pi_client is None:
            self._pi_client = self._create_pi_client()
            logger.info(
                f"PiAgent initialized (runtime={self._runtime}, bin={self._runtime_bin}, session_dir={self._pi_session_dir})"
            )

    async def chat(self, input_data: BaseInput) -> AsyncIterator[SentenceOutput | ToolCallStatus | dict]:
        self.reset_interrupt()

        batch = input_data if isinstance(input_data, BatchInput) else None
        user_text = (
            " ".join(t.content for t in batch.texts if t.content).strip()
            if batch else ""
        )
        if not user_text:
            logger.warning("PiAgent: no user text to process")
            return

        logger.info(f"PiAgent processing: {user_text[:100]}...")

        # Wait for any in-flight background turn to complete before issuing the
        # next prompt — keeps conversation history intact on the single client.
        if self._bg_future and not self._bg_future.done():
            logger.info("PiAgent: waiting for background task before next turn...")
            try:
                await asyncio.wait_for(asyncio.shield(self._bg_future), timeout=120.0)
            except (asyncio.TimeoutError, Exception) as e:
                logger.warning(f"PiAgent: background wait ended early: {e}")

        self._ensure_pi_client()
        turn_client = self._pi_client

        agent_name = (
            self._live2d_model.model_info.get("name", "AI") if self._live2d_model else "AI"
        )

        loop = asyncio.get_event_loop()
        event_queue: asyncio.Queue = asyncio.Queue()
        tool_events_seen = []

        # Register a per-call tool event handler — clear previous ones first.
        from ...pi_client.events import ToolEvent
        turn_client._event_handlers.clear()

        def _tool_handler(event):
            asyncio.run_coroutine_threadsafe(event_queue.put(event), loop)

        turn_client.on_event(_tool_handler)

        result_future = asyncio.ensure_future(
            loop.run_in_executor(None, lambda: self._run_pi_prompt_with(turn_client, user_text))
        )

        t0 = loop.time()
        offloaded = False

        try:
            while True:
                done, _ = await asyncio.wait({result_future}, timeout=0.15)

                # Drain any tool events that arrived
                while not event_queue.empty():
                    try:
                        ev = event_queue.get_nowait()
                        if isinstance(ev, ToolEvent):
                            tool_events_seen.append(ev)
                            if ev.type == "tool_execution_end":
                                status = "error" if ev.is_error else "completed"
                                content = str(ev.result) if ev.result else ""
                            else:
                                status = "running"
                                content = str(ev.args) if ev.args else ""
                            yield ToolCallStatus(
                                tool_id=ev.tool_call_id or uuid.uuid4().hex[:8],
                                tool_name=ev.tool_name,
                                status=status,
                                content=content,
                                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                name=agent_name,
                            )
                        elif any(
                            marker in str(getattr(ev, "type", "")).lower()
                            for marker in ("subagent", "delegate")
                        ):
                            yield {
                                "type": "internal_debug_trace",
                                "title": f"{self._runtime.title()} sub-agent event",
                                "content": json.dumps(
                                    getattr(
                                        ev,
                                        "raw",
                                        {"event_type": getattr(ev, "type", "unknown")},
                                    ),
                                    ensure_ascii=False,
                                ),
                            }
                    except asyncio.QueueEmpty:
                        break

                if done:
                    break

                # Slow + tool activity → ack and deliver in background
                elapsed = loop.time() - t0
                if (
                    not offloaded
                    and elapsed > _BG_THRESHOLD_SEC
                    and tool_events_seen
                    and self._speak_callback
                ):
                    offloaded = True

                    # Replace in-turn handler with a background one that forwards
                    # remaining tool events to the UI via the callback.
                    turn_client._event_handlers.clear()
                    if self._tool_event_callback:
                        def _bg_tool_handler(event):
                            if isinstance(event, ToolEvent):
                                if event.type == "tool_execution_end":
                                    status = "error" if event.is_error else "completed"
                                    content = str(event.result) if event.result else ""
                                else:
                                    status = "running"
                                    content = str(event.args) if event.args else ""
                                tool_status = ToolCallStatus(
                                    tool_id=event.tool_call_id or uuid.uuid4().hex[:8],
                                    tool_name=event.tool_name,
                                    status=status,
                                    content=content,
                                    timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                    name=agent_name,
                                )
                                asyncio.run_coroutine_threadsafe(
                                    self._tool_event_callback(tool_status), loop
                                )
                        turn_client.on_event(_bg_tool_handler)

                    ack = "Let me look into that — I'll let you know when I'm done."
                    yield SentenceOutput(
                        display_text=DisplayText(text=ack, name=agent_name),
                        tts_text=ack,
                        actions=Actions(),
                    )
                    # Track the future so the next chat() waits before prompting.
                    self._bg_future = result_future
                    asyncio.create_task(self._bg_deliver(result_future))
                    return

            # Fast path: yield inline
            if not offloaded:
                try:
                    result = result_future.result()
                except Exception as e:
                    logger.error(f"PiAgent prompt error: {e}")
                    return

                text = (result.text if result else "").strip()
                if not text:
                    logger.warning("PiAgent returned empty response")
                    return
                yield SentenceOutput(
                    display_text=DisplayText(text=text, name=agent_name),
                    tts_text=text,
                    actions=Actions(),
                )
        finally:
            if not offloaded:
                turn_client._event_handlers.clear()

    async def _bg_deliver(self, future: asyncio.Future) -> None:
        """Wait for pi to finish and speak the result via the callback."""
        try:
            result = await asyncio.wait_for(future, timeout=300.0)
            text = (result.text if result else "").strip()
            if text and self._speak_callback:
                await self._speak_callback(text)
        except asyncio.TimeoutError:
            logger.warning("PiAgent background task timed out.")
        except Exception as e:
            logger.exception(f"PiAgent background delivery failed: {e}")
        finally:
            self._bg_future = None

    def _run_pi_prompt_with(self, client, message: str) -> Any:
        """Run pi.prompt on a specific client (called from executor thread)."""
        if not client or client._proc is None:
            return None
        try:
            return client.prompt(message)
        except Exception as e:
            logger.exception(f"Error in pi.prompt: {e}")
            return None

    def reset_interrupt(self):
        self._interrupt_handled = False

    def handle_interrupt(self, heard_response: str = "") -> None:
        self._interrupt_handled = True
        logger.info("PiAgent: interrupt received.")
        if self._pi_client:
            try:
                self._pi_client.abort()
            except Exception:
                pass

    def set_memory_from_history(self, conf_uid: str, history_uid: str) -> None:
        pass

    async def close(self):
        if self._pi_client:
            try:
                self._pi_client.stop()
            except Exception:
                pass
            self._pi_client = None
            logger.info("PiAgent closed.")
