"""
HermesAgent: wraps hermes via ACP (Agent Client Protocol) stdio JSON-RPC.

A long-lived `hermes acp` subprocess is kept alive per agent instance.
ACP session management provides conversation continuity across turns.
Tool events stream back as ToolCallStatus for the UI.

Background offload: if hermes takes longer than _HERMES_BG_THRESHOLD_SEC,
an ack is yielded immediately and the result is delivered via _speak_callback
when ready (same pattern as PiAgent).
"""

import asyncio
import os
import time
import uuid
from typing import AsyncIterator, Optional, Callable, Awaitable, Tuple, Any
from loguru import logger

from .agent_interface import AgentInterface
from ..output_types import SentenceOutput, DisplayText, Actions
from ..output_types import ToolCallStatus as VTuberToolCallStatus
from ..input_types import BaseInput, BatchInput
from ...config_manager import TTSPreprocessorConfig

# Seconds before a slow hermes response is offloaded to background TTS.
# First-turn warmups can exceed 60s in real usage (model cold start + ACP init),
# and the split "thinking..." ack is worse UX than waiting once.
_HERMES_BG_THRESHOLD_SEC = 120.0
# If we already see tool activity, offload much earlier so the user can keep
# chatting while long browser/obsidian actions continue in background.
_HERMES_BG_THRESHOLD_WITH_TOOLS_SEC = 6.0


class _HermesVTuberClient:
    """ACP Client: routes session_update events into a per-turn queue."""

    def __init__(self) -> None:
        self.event_queue: Optional[asyncio.Queue] = None

    async def session_update(self, session_id: str, update, **kwargs) -> None:
        if self.event_queue is not None:
            try:
                self.event_queue.put_nowait(update)
            except asyncio.QueueFull:
                pass

    async def request_permission(self, options, session_id, tool_call, **kwargs):
        try:
            from acp.schema import RequestPermissionResponse, AllowedOutcome

            first_id = options[0].id if options else "allow_once"
            return RequestPermissionResponse(
                outcome=AllowedOutcome(option_id=first_id, outcome="selected")
            )
        except Exception:
            return None

    async def write_text_file(self, content, path, session_id, **kwargs):
        return None

    async def read_text_file(self, path, session_id, **kwargs):
        from acp.schema import ReadTextFileResponse

        return ReadTextFileResponse(content="")

    async def create_terminal(self, command, session_id, **kwargs):
        from acp.schema import CreateTerminalResponse

        return CreateTerminalResponse(terminal_id=uuid.uuid4().hex[:8])

    async def terminal_output(self, session_id, terminal_id, **kwargs):
        from acp.schema import TerminalOutputResponse

        return TerminalOutputResponse(output="", truncated=False)

    async def release_terminal(self, session_id, terminal_id, **kwargs):
        return None

    async def wait_for_terminal_exit(self, session_id, terminal_id, **kwargs):
        from acp.schema import WaitForTerminalExitResponse

        return WaitForTerminalExitResponse(exit_code=0)

    async def kill_terminal(self, session_id, terminal_id, **kwargs):
        return None

    async def ext_method(self, method, params):
        return {}

    async def ext_notification(self, method, params):
        pass

    def on_connect(self, conn) -> None:
        pass


class HermesAgent(AgentInterface):
    """Agent that communicates with hermes via the ACP stdio JSON-RPC protocol."""

    def __init__(
        self,
        system: str,
        live2d_model,
        tts_preprocessor_config: TTSPreprocessorConfig = None,
        faster_first_response: bool = True,
        segment_method: str = "pysbd",
        interrupt_method: str = "user",
        vision_engine=None,
        hermes_session_dir: Optional[str] = None,
        hermes_bin: Optional[str] = None,
        hermes_cwd: Optional[str] = None,
    ):
        super().__init__()
        self._live2d_model = live2d_model
        self._tts_preprocessor_config = tts_preprocessor_config
        self._system_prompt = system
        self._hermes_bin = hermes_bin or "hermes"
        self._hermes_cwd = hermes_cwd or os.getcwd()

        # ACP connection state
        self._conn = None
        self._proc = None
        self._session_id: Optional[str] = None
        self._acp_client = _HermesVTuberClient()
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._acp_client.event_queue = self._event_queue

        # Background offload tracking
        self._bg_future: Optional[asyncio.Future] = None
        self._interrupt_handled: bool = False

        # Injected callbacks
        self._speak_callback: Optional[Callable[[str], Awaitable[None]]] = None
        self._tool_event_callback: Optional[
            Callable[[VTuberToolCallStatus], Awaitable[None]]
        ] = None

    def set_speak_callback(self, fn: Callable[[str], Awaitable[None]]) -> None:
        self._speak_callback = fn

    def set_tool_event_callback(
        self, fn: Callable[[VTuberToolCallStatus], Awaitable[None]]
    ) -> None:
        self._tool_event_callback = fn

    async def _open_ephemeral_session(self) -> Tuple[Any, Any, str, _HermesVTuberClient, asyncio.Queue]:
        """Open a one-shot ACP connection/session for foreground chat while bg task runs."""
        from acp.client.connection import ClientSideConnection
        from acp.schema import Implementation
        from acp import PROTOCOL_VERSION

        client = _HermesVTuberClient()
        q: asyncio.Queue = asyncio.Queue()
        client.event_queue = q

        proc = await asyncio.create_subprocess_exec(
            self._hermes_bin,
            "acp",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
            cwd=self._hermes_cwd,
        )
        conn = ClientSideConnection(client, proc.stdin, proc.stdout)
        await conn.initialize(
            protocol_version=PROTOCOL_VERSION,
            client_info=Implementation(name="open-llm-vtuber-fg", version="1.0"),
        )
        resp = await conn.new_session(
            cwd=self._hermes_cwd,
            _meta={"vtuber_system_prompt": self._system_prompt},
        )
        return conn, proc, resp.session_id, client, q

    async def _run_ephemeral_foreground(
        self, user_text: str, agent_name: str
    ) -> AsyncIterator[SentenceOutput | VTuberToolCallStatus]:
        """Run one foreground turn in an ephemeral ACP session."""
        conn = proc = session_id = None
        q: asyncio.Queue | None = None
        events: list = []
        try:
            conn, proc, session_id, _client, q = await self._open_ephemeral_session()
            from acp.schema import TextContentBlock as ACPTextBlock

            task = asyncio.create_task(
                conn.prompt([ACPTextBlock(type="text", text=user_text)], session_id=session_id)
            )
            while True:
                done, _ = await asyncio.wait({task}, timeout=0.15)
                while q is not None and not q.empty():
                    ev = q.get_nowait()
                    events.append(ev)
                    ts = self._event_to_tool_status(ev, agent_name)
                    if ts is not None:
                        yield ts
                if done:
                    break
            if q is not None:
                while not q.empty():
                    events.append(q.get_nowait())
            text = self._extract_text(events)
            if text:
                yield SentenceOutput(
                    display_text=DisplayText(text=text, name=agent_name),
                    tts_text=text,
                    actions=Actions(),
                )
        except Exception as e:
            logger.warning(f"HermesAgent: ephemeral foreground failed: {e}")
            yield SentenceOutput(
                display_text=DisplayText(text="I’m still finishing that task — try again in a moment.", name=agent_name),
                tts_text="I’m still finishing that task — try again in a moment.",
                actions=Actions(),
            )
        finally:
            try:
                if conn:
                    await conn.close()
            except Exception:
                pass
            try:
                if proc:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=3.0)
            except Exception:
                pass

    async def _ensure_connected(self) -> None:
        """Start hermes acp subprocess and ACP session if not already running."""
        if self._conn is not None and self._proc is not None:
            if self._proc.returncode is None:
                return
            logger.warning("HermesAgent: hermes acp process died, reconnecting...")
            self._conn = None
            self._proc = None
            self._session_id = None

        try:
            from acp.client.connection import ClientSideConnection
            from acp.schema import Implementation
            from acp import PROTOCOL_VERSION
        except ImportError as exc:
            raise RuntimeError(
                "agent-client-protocol is required for HermesAgent. "
                "Install it with: uv add agent-client-protocol"
            ) from exc

        logger.info(
            f"HermesAgent: starting hermes acp (bin={self._hermes_bin}, cwd={self._hermes_cwd})"
        )

        # Drain stale queue events from a previous session
        self._drain_queue()

        try:
            proc = await asyncio.create_subprocess_exec(
                self._hermes_bin,
                "acp",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=os.environ.copy(),
                cwd=self._hermes_cwd,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"hermes binary not found: '{self._hermes_bin}'. "
                f"Please install hermes or set hermes_bin in config to the correct path."
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                f"Failed to start hermes acp subprocess: {exc}"
            ) from exc

        self._proc = proc

        # Check if process crashed immediately (give it 100ms)
        await asyncio.sleep(0.1)
        if self._proc.returncode is not None:
            stderr_output = ""
            try:
                stderr_output = await asyncio.wait_for(
                    self._proc.stderr.read(), timeout=0.5
                )
                stderr_output = stderr_output.decode("utf-8", errors="replace")
            except Exception:
                pass
            raise RuntimeError(
                f"hermes acp process exited immediately with code {self._proc.returncode}. "
                f"stderr: {stderr_output or '(no output)'}"
            )

        # proc.stdin → StreamWriter, proc.stdout → StreamReader
        self._conn = ClientSideConnection(self._acp_client, proc.stdin, proc.stdout)

        try:
            await self._conn.initialize(
                protocol_version=PROTOCOL_VERSION,
                client_info=Implementation(name="open-llm-vtuber", version="1.0"),
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to initialize ACP connection with hermes: {exc}"
            ) from exc

        # Pass the VTuber system prompt via ACP _meta so the ACP adapter
        # can inject it into the agent before the first prompt.
        resp = await self._conn.new_session(
            cwd=self._hermes_cwd,
            _meta={"vtuber_system_prompt": self._system_prompt},
        )
        self._session_id = resp.session_id
        logger.info(f"HermesAgent: ACP session {self._session_id} created")

        # Auto-approve all file edits (yolo-equivalent).
        # Fire-and-forget so it doesn't add latency to the connection handshake.
        asyncio.create_task(self._set_session_mode_silent("dont_ask", self._session_id))

    def _drain_queue(self) -> list:
        """Drain and return all pending events from the queue."""
        events = []
        while not self._event_queue.empty():
            try:
                events.append(self._event_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return events

    async def _set_session_mode_silent(self, mode: str, session_id: str) -> None:
        """Set session mode without blocking the connection handshake."""
        try:
            await self._conn.set_session_mode(mode, session_id)
        except Exception as e:
            logger.debug(f"HermesAgent: set_session_mode failed (non-critical): {e}")

    def _extract_text(self, events: list) -> str:
        """Extract accumulated assistant text from session_update events."""
        try:
            from acp.schema import AgentMessageChunk, TextContentBlock as ACPTextBlock
        except ImportError:
            return ""
        parts = []
        for ev in events:
            if isinstance(ev, AgentMessageChunk):
                content = ev.content
                if isinstance(content, ACPTextBlock) and content.text:
                    parts.append(content.text)
        return "".join(parts).strip()

    def _event_to_tool_status(
        self, ev, agent_name: str
    ) -> Optional[VTuberToolCallStatus]:
        """Convert an ACP ToolCallStart or ToolCallProgress to VTuberToolCallStatus."""
        try:
            from acp.schema import ToolCallStart, ToolCallProgress
        except ImportError:
            return None
        try:
            if isinstance(ev, ToolCallStart):
                raw_in = ev.raw_input
                content = str(raw_in) if raw_in else ""
                return VTuberToolCallStatus(
                    tool_id=ev.tool_call_id,
                    tool_name=ev.title,
                    status="running",
                    content=content,
                    timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    name=agent_name,
                )
            if isinstance(ev, ToolCallProgress):
                # acp.schema.ToolCallStatus is a Literal; "completed"/"failed" are the terminal states
                acp_status = getattr(ev, "status", None)
                if acp_status == "completed":
                    vtb_status = "completed"
                elif acp_status == "failed":
                    vtb_status = "error"
                else:
                    return None  # skip pending / in_progress noise
                parts = []
                for item in ev.content or []:
                    if hasattr(item, "text"):
                        parts.append(str(item.text))
                    elif hasattr(item, "content"):
                        parts.append(str(item.content))
                return VTuberToolCallStatus(
                    tool_id=ev.tool_call_id,
                    tool_name=ev.title,
                    status=vtb_status,
                    content="".join(parts),
                    timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    name=agent_name,
                )
        except Exception as e:
            logger.debug(f"HermesAgent: could not convert tool event: {e}")
        return None

    async def chat(
        self, input_data: BaseInput
    ) -> AsyncIterator[SentenceOutput | VTuberToolCallStatus]:
        self.reset_interrupt()

        batch = input_data if isinstance(input_data, BatchInput) else None
        user_text = (
            " ".join(t.content for t in batch.texts if t.content).strip()
            if batch
            else ""
        )
        if not user_text:
            logger.warning("HermesAgent: no user text to process")
            return

        logger.info(f"HermesAgent processing: {user_text[:100]}...")

        # If background task is running, use an ephemeral ACP session for this
        # foreground turn so it doesn't get queued behind the in-flight task.
        bg_running = self._bg_future and not self._bg_future.done()
        if bg_running:
            logger.info("HermesAgent: background task still running; using ephemeral foreground session.")

        try:
            if not bg_running:
                await self._ensure_connected()
        except RuntimeError as e:
            error_msg = str(e)
            logger.error(f"HermesAgent initialization failed: {error_msg}")
            agent_name = (
                self._live2d_model.model_info.get("name", "AI")
                if self._live2d_model
                else "AI"
            )
            yield SentenceOutput(
                display_text=DisplayText(
                    text=f"[Agent Error] {error_msg}",
                    name=agent_name
                ),
                tts_text=f"Agent initialization failed: {error_msg}",
                actions=Actions(),
            )
            return

        agent_name = (
            self._live2d_model.model_info.get("name", "AI")
            if self._live2d_model
            else "AI"
        )

        if bg_running:
            async for out in self._run_ephemeral_foreground(user_text, agent_name):
                yield out
            return

        loop = asyncio.get_event_loop()

        # Discard any events left over from previous turns
        self._drain_queue()

        from acp.schema import TextContentBlock as ACPTextBlock

        prompt_task = asyncio.create_task(
            self._conn.prompt(
                [ACPTextBlock(type="text", text=user_text)],
                session_id=self._session_id,
            )
        )

        t0 = loop.time()
        offloaded = False
        accumulated_events: list = []
        saw_tool_activity = False

        try:
            while True:
                done, _ = await asyncio.wait({prompt_task}, timeout=0.15)

                # Drain incoming events
                while not self._event_queue.empty():
                    try:
                        ev = self._event_queue.get_nowait()
                        accumulated_events.append(ev)
                        ts = self._event_to_tool_status(ev, agent_name)
                        if ts is not None:
                            saw_tool_activity = True
                            yield ts
                    except asyncio.QueueEmpty:
                        break

                if done:
                    break

                elapsed = loop.time() - t0
                should_offload = (
                    elapsed > _HERMES_BG_THRESHOLD_SEC
                    or (
                        saw_tool_activity
                        and elapsed > _HERMES_BG_THRESHOLD_WITH_TOOLS_SEC
                    )
                )
                if not offloaded and should_offload and self._speak_callback:
                    offloaded = True
                    ack = (
                        "Got it — I’m running that in the background. "
                        "Keep chatting and I’ll read out the result when it’s ready."
                    )
                    yield SentenceOutput(
                        display_text=DisplayText(text=ack, name=agent_name),
                        tts_text=ack,
                        actions=Actions(),
                    )
                    self._bg_future = prompt_task
                    asyncio.create_task(
                        self._bg_deliver(prompt_task, accumulated_events, agent_name)
                    )
                    return

        except asyncio.CancelledError:
            prompt_task.cancel()
            raise

        if not offloaded:
            # One more drain pass after completion (events may have arrived last cycle)
            await asyncio.sleep(0)
            for ev in self._drain_queue():
                accumulated_events.append(ev)

            text = self._extract_text(accumulated_events)
            if not text:
                logger.warning("HermesAgent: empty response from hermes")
                return
            yield SentenceOutput(
                display_text=DisplayText(text=text, name=agent_name),
                tts_text=text,
                actions=Actions(),
            )

    async def _bg_deliver(
        self,
        task: asyncio.Task,
        events_so_far: list,
        agent_name: str,
    ) -> None:
        """Wait for the in-flight prompt to finish and speak the result."""
        try:
            # Browser/tool tasks can run long; keep generous timeout so
            # background delivery is not dropped too aggressively.
            await asyncio.wait_for(task, timeout=180.0)
            # One async sleep to let any trailing events be dispatched
            await asyncio.sleep(0)
            for ev in self._drain_queue():
                events_so_far.append(ev)
                ts = self._event_to_tool_status(ev, agent_name)
                if ts is not None and self._tool_event_callback:
                    try:
                        await self._tool_event_callback(ts)
                    except Exception:
                        pass

            # Debug: log all event types we received
            event_types = [type(ev).__name__ for ev in events_so_far]
            logger.info(
                f"HermesAgent: background task done, events={len(events_so_far)}, "
                f"types={event_types}"
            )

            text = self._extract_text(events_so_far)
            if text:
                # Suppress internal interruption boilerplate from cancelled
                # background runs so it doesn't get spoken over normal chat.
                lowered = text.strip().lower()
                if lowered.startswith("operation interrupted:"):
                    logger.info(
                        "HermesAgent: suppressing interrupted background boilerplate: %s",
                        text[:120],
                    )
                    return
                logger.info(f"HermesAgent: background delivery speaking: {text[:100]}...")
                await self._speak_callback(text)
            else:
                logger.warning(
                    "HermesAgent: background task completed but extracted text is empty. "
                    "Event types seen: %s", event_types
                )
        except asyncio.TimeoutError:
            logger.warning("HermesAgent background task timed out (180s). LLM may be hanging.")
        except Exception as e:
            logger.exception(f"HermesAgent background delivery failed: {e}")
        finally:
            self._bg_future = None

    def reset_interrupt(self) -> None:
        self._interrupt_handled = False

    def handle_interrupt(self, heard_response: str = "") -> None:
        self._interrupt_handled = True
        logger.info("HermesAgent: interrupt received.")

        # Do not cancel the main ACP session when a background-offloaded task
        # is still running. That background task should continue independently
        # while the user starts a new foreground turn.
        if self._bg_future and not self._bg_future.done():
            logger.info("HermesAgent: preserving background task on interrupt; skip main session cancel.")
            return

        if self._conn and self._session_id:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._conn.cancel(self._session_id), loop
                    )
            except Exception as e:
                logger.debug(f"HermesAgent: cancel error: {e}")

    def set_memory_from_history(self, conf_uid: str, history_uid: str) -> None:
        pass

    async def close(self) -> None:
        if self._conn:
            try:
                await self._conn.close()
            except Exception:
                pass
            self._conn = None
        if self._proc:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        logger.info("HermesAgent closed.")
