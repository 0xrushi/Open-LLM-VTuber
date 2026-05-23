"""
Core pi-client: RPC protocol wrapper for the pi coding agent.

Manages a subprocess of `pi --mode rpc` and provides a clean Python API
for prompting, bash execution, session management, and event handling.

All subagents, tool calls, and events are logged through the centralized
logger configured via LogConfig.setup().
"""

import json
import queue
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .events import (
    AgentEvent,
    CommandResult,
    LogConfig,
    MessageEvent,
    PromptResult,
    ToolEvent,
    TurnEvent,
    log_command,
    log_event,
    log_error,
    log_response,
)


@dataclass
class PiConfig:
    """Configuration for the pi client."""
    pi_bin: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    no_session: bool = False
    session_dir: Optional[str] = None
    thinking_level: Optional[str] = None
    api_key: Optional[str] = None
    tools: Optional[str] = None
    extension: Optional[str] = None
    skill: Optional[str] = None
    no_extensions: bool = False
    no_skills: bool = False
    no_context_files: bool = False
    system_prompt: Optional[str] = None
    append_system_prompt: Optional[str] = None
    verbose: bool = False
    offline: bool = False


class PiClient:
    """
    Python client for the pi coding agent via RPC protocol.

    Usage:
        client = PiClient()
        result = client.prompt("List all files in src/")
        print(result.text)

        # With centralized logging
        from pi_client import PiClient, LogConfig
        LogConfig.setup("pi_events.log", level="DEBUG")

        client = PiClient()
        # All events, tool calls, and subagent operations are logged
    """

    def __init__(self, config: Optional[PiConfig] = None):
        """
        Initialize the pi client.

        Args:
            config: Optional configuration for the pi RPC process.
        """
        self._config = config or PiConfig()
        self._proc: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._running = False
        self._reader_thread: Optional[threading.Thread] = None
        self._event_queue: queue.Queue = queue.Queue()
        self._event_handlers: list[Callable[[AgentEvent], None]] = []
        self._response_events: list[AgentEvent] = []
        self._response_commands: list[CommandResult] = []
        self._response_cv = threading.Condition()

    # --- Lifecycle ---

    def _build_cmd(self) -> list[str]:
        """Build the pi RPC command line."""
        cmd = [self._config.pi_bin or "pi", "--mode", "rpc"]
        if self._config.provider:
            cmd.extend(["--provider", self._config.provider])
        if self._config.model:
            cmd.extend(["--model", self._config.model])
        if self._config.no_session:
            cmd.append("--no-session")
        if self._config.session_dir:
            cmd.extend(["--session-dir", self._config.session_dir])
        if self._config.thinking_level:
            cmd.extend(["--thinking", self._config.thinking_level])
        if self._config.api_key:
            cmd.extend(["--api-key", self._config.api_key])
        if self._config.tools:
            cmd.extend(["--tools", self._config.tools])
        if self._config.extension:
            cmd.extend(["-e", self._config.extension])
        if self._config.skill:
            cmd.extend(["--skill", self._config.skill])
        if self._config.no_extensions:
            cmd.append("--no-extensions")
        if self._config.no_skills:
            cmd.append("--no-skills")
        if self._config.no_context_files:
            cmd.append("--no-context-files")
        if self._config.system_prompt:
            cmd.extend(["--system-prompt", self._config.system_prompt])
        if self._config.append_system_prompt:
            cmd.extend(["--append-system-prompt", self._config.append_system_prompt])
        if self._config.verbose:
            cmd.append("--verbose")
        if self._config.offline:
            cmd.append("--offline")
        return cmd

    def start(self) -> "PiClient":
        """
        Start the pi RPC process.

        Returns:
            Self for chaining.
        """
        if self._proc and self._proc.poll() is None:
            return self

        cmd = self._build_cmd()
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # Line buffered
        )
        self._running = True

        # Start background event reader thread
        self._reader_thread = threading.Thread(target=self._read_events_loop, daemon=True)
        self._reader_thread.start()

        return self

    def _read_events_loop(self) -> None:
        """Background thread loop reading JSONL events from stdout."""
        try:
            while self._running and self._proc and self._proc.stdout:
                line = self._proc.stdout.readline()
                if not line:
                    break
                line = line.rstrip("\r\n")
                if not line:
                    continue
                self._parse_line(line)
        except Exception as e:
            log_error(f"Event reader loop error: {e}", e)

    def _parse_line(self, line: str) -> None:
        """Parse a JSONL line from stdout."""
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return

        event_type = data.get("type")
        if not event_type:
            return

        # Check if it's a response (correlates with request)
        if event_type == "response":
            req_id = data.get("id")
            result = CommandResult(
                success=data.get("success", False),
                command=data.get("command", ""),
                data=data.get("data"),
                error=data.get("error"),
                id=req_id,
            )
            log_response(result)

            # Store for request/response wait
            with self._response_cv:
                self._response_commands.append(result)
                self._response_cv.notify_all()
            return

        # It's an event — emit it
        event = self._event_from_data(data)
        log_event(event)

        # Store for prompt wait
        with self._response_cv:
            self._response_events.append(event)
            self._response_cv.notify_all()

        # Notify handlers
        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception:
                pass

    def _event_from_data(self, data: dict) -> AgentEvent:
        """Convert raw event data to typed event."""
        event_type = data.get("type", "")

        if event_type in ("turn_start", "turn_end"):
            return TurnEvent(type=event_type, raw=data)

        if event_type in ("message_start", "message_end", "message_update"):
            delta = data.get("assistantMessageEvent", {})
            delta_type = delta.get("type", "")
            content = delta.get("delta", "")
            return MessageEvent(
                type=event_type,
                raw=data,
                delta_type=delta_type,
                content=content,
                partial=delta.get("partial"),
            )

        if event_type in ("tool_execution_start", "tool_execution_update", "tool_execution_end"):
            return ToolEvent(
                type=event_type,
                raw=data,
                tool_name=data.get("toolName", ""),
                tool_call_id=data.get("toolCallId", ""),
                args=data.get("args", {}),
                result=data.get("result"),
                is_error=data.get("isError", False),
            )

        return AgentEvent(type=event_type, raw=data)

    def stop(self) -> None:
        """Stop the pi RPC process."""
        self._running = False

        # Abort any running operation
        if self._proc and self._proc.stdin:
            try:
                self._send({"type": "abort"})
            except Exception:
                pass

        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()

        if self._reader_thread:
            self._reader_thread.join(timeout=2)

    # --- Helpers ---

    def _next_id(self) -> str:
        """Generate a unique request ID."""
        self._request_id += 1
        return f"req-{self._request_id}"

    def _send(self, cmd: dict) -> None:
        """Send a command to the pi process."""
        log_command(cmd)
        if not self._proc or not self._proc.stdin:
            raise RuntimeError("pi process not running. Call start() first.")
        line = json.dumps(cmd) + "\n"
        self._proc.stdin.write(line)
        self._proc.stdin.flush()

    def _wait_for_response(self, expected_type: Optional[str] = None, timeout: float = 120.0) -> Optional[AgentEvent]:
        """Wait for a response or event from pi.

        Args:
            expected_type: "response" to wait for command results, None to wait
                for agent events (prompt mode).
        """
        deadline = time.time() + timeout

        with self._response_cv:
            while time.time() < deadline:
                # Check for command results (used by state/bash methods)
                if expected_type == "response" and self._response_commands:
                    cmd = self._response_commands.pop(0)
                    return cmd
                # Check for events (used by prompt method)
                # Also drain stale command results to keep the queue clean
                if self._response_events:
                    event = self._response_events.pop(0)
                    if expected_type is None or event.type == expected_type:
                        return event
                    self._response_events.insert(0, event)
                # Drain stale command results even in event mode
                if self._response_commands:
                    self._response_commands.pop(0)
                self._response_cv.wait(timeout=0.1)

        return None

    # --- Event Handling ---

    def on_event(self, handler: Callable[[AgentEvent], None]) -> None:
        """Register an event handler. Called for every event from pi."""
        self._event_handlers.append(handler)

    # --- Core Commands ---

    def prompt(self, message: str, streaming: bool = False) -> PromptResult:
        """
        Send a prompt to the agent and wait for completion.

        Args:
            message: The prompt text.
            streaming: If True, processes streaming output.

        Returns:
            PromptResult with text, tools_used, and metadata.
        """
        self.start()
        req_id = self._next_id()
        cmd = {"id": req_id, "type": "prompt", "message": message}
        self._send(cmd)

        # Collect events until agent_end
        final_text = ""
        final_thinking = ""
        tools_used = []
        tool_results = []
        model = None
        tokens_input = 0
        tokens_output = 0
        cost = 0.0
        stop_reason = "stop"

        while True:
            event = self._wait_for_response(timeout=120.0)
            if event is None:
                break  # Timeout

            event_type = event.type

            if event_type == "agent_end":
                # Extract final message data
                messages = event.raw.get("messages", [])
                if messages:
                    msg = messages[-1]
                    if msg.get("role") == "assistant":
                        for content in msg.get("content", []):
                            if content.get("type") == "text":
                                final_text += content.get("text", "")
                            elif content.get("type") == "thinking":
                                final_thinking += content.get("thinking", "")
                            elif content.get("type") == "toolCall":
                                tools_used.append(content)
                    model = msg.get("model")
                    usage = msg.get("usage", {})
                    tokens_input = usage.get("input", 0)
                    tokens_output = usage.get("output", 0)
                    cost = usage.get("cost", {}).get("total", 0.0)
                    stop_reason = msg.get("stopReason", "stop")
                break

            if event_type == "turn_end":
                msg = event.raw.get("message", {})
                for content in msg.get("content", []):
                    if content.get("type") == "toolCall":
                        tools_used.append(content)
                for tr in event.raw.get("toolResults", []):
                    tool_results.append(tr)

            if event_type == "message_update":
                delta = event.raw.get("assistantMessageEvent", {})
                if delta.get("type") == "text_delta":
                    final_text += delta.get("delta", "")

        return PromptResult(
            text=final_text,
            thinking=final_thinking,
            tools_used=tools_used,
            tool_results=tool_results,
            model=model,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            cost=cost,
            stop_reason=stop_reason,
        )

    def steer(self, message: str) -> CommandResult:
        """Queue a steering message while agent is running."""
        self.start()
        req_id = self._next_id()
        self._send({"id": req_id, "type": "steer", "message": message})
        return self._wait_for_response(expected_type="response", timeout=30.0) or CommandResult(success=False, command="steer", error="timeout")

    def follow_up(self, message: str) -> CommandResult:
        """Queue a follow-up message for after agent finishes."""
        self.start()
        req_id = self._next_id()
        self._send({"id": req_id, "type": "follow_up", "message": message})
        return self._wait_for_response(expected_type="response", timeout=30.0) or CommandResult(success=False, command="follow_up", error="timeout")

    def abort(self) -> CommandResult:
        """Abort the current agent operation."""
        self.start()
        req_id = self._next_id()
        self._send({"id": req_id, "type": "abort"})
        return self._wait_for_response(expected_type="response", timeout=30.0) or CommandResult(success=False, command="abort", error="timeout")

    # --- State Commands ---

    def get_state(self) -> CommandResult:
        """Get current session state."""
        self.start()
        req_id = self._next_id()
        self._send({"id": req_id, "type": "get_state"})
        return self._wait_for_response(expected_type="response", timeout=30.0) or CommandResult(success=False, command="get_state", error="timeout")

    def get_messages(self) -> CommandResult:
        """Get all messages in the conversation."""
        self.start()
        req_id = self._next_id()
        self._send({"id": req_id, "type": "get_messages"})
        return self._wait_for_response(expected_type="response", timeout=30.0) or CommandResult(success=False, command="get_messages", error="timeout")

    def get_session_stats(self) -> CommandResult:
        """Get token usage, cost statistics."""
        self.start()
        req_id = self._next_id()
        self._send({"id": req_id, "type": "get_session_stats"})
        return self._wait_for_response(expected_type="response", timeout=30.0) or CommandResult(success=False, command="get_session_stats", error="timeout")

    def get_last_assistant_text(self) -> CommandResult:
        """Get the text content of the last assistant message."""
        self.start()
        req_id = self._next_id()
        self._send({"id": req_id, "type": "get_last_assistant_text"})
        return self._wait_for_response(expected_type="response", timeout=30.0) or CommandResult(success=False, command="get_last_assistant_text", error="timeout")

    # --- Model Commands ---

    def set_model(self, provider: str, model_id: str) -> CommandResult:
        """Switch to a specific model."""
        self.start()
        req_id = self._next_id()
        self._send({"id": req_id, "type": "set_model", "provider": provider, "modelId": model_id})
        return self._wait_for_response(expected_type="response", timeout=30.0) or CommandResult(success=False, command="set_model", error="timeout")

    def cycle_model(self) -> CommandResult:
        """Cycle to the next available model."""
        self.start()
        req_id = self._next_id()
        self._send({"id": req_id, "type": "cycle_model"})
        return self._wait_for_response(expected_type="response", timeout=30.0) or CommandResult(success=False, command="cycle_model", error="timeout")

    def get_available_models(self) -> CommandResult:
        """List all configured models."""
        self.start()
        req_id = self._next_id()
        self._send({"id": req_id, "type": "get_available_models"})
        return self._wait_for_response(expected_type="response", timeout=30.0) or CommandResult(success=False, command="get_available_models", error="timeout")

    def set_thinking_level(self, level: str) -> CommandResult:
        """Set reasoning/thinking level (off, minimal, low, medium, high, xhigh)."""
        self.start()
        req_id = self._next_id()
        self._send({"id": req_id, "type": "set_thinking_level", "level": level})
        return self._wait_for_response(expected_type="response", timeout=30.0) or CommandResult(success=False, command="set_thinking_level", error="timeout")

    def cycle_thinking_level(self) -> CommandResult:
        """Cycle through available thinking levels."""
        self.start()
        req_id = self._next_id()
        self._send({"id": req_id, "type": "cycle_thinking_level"})
        return self._wait_for_response(expected_type="response", timeout=30.0) or CommandResult(success=False, command="cycle_thinking_level", error="timeout")

    # --- Bash ---

    def bash(self, command: str) -> CommandResult:
        """
        Execute a shell command. Output is added to LLM context on next prompt.

        Args:
            command: The shell command to execute.

        Returns:
            BashResult with output, exitCode, truncated, etc.
        """
        self.start()
        req_id = self._next_id()
        self._send({"id": req_id, "type": "bash", "command": command})
        return self._wait_for_response(expected_type="response", timeout=30.0) or CommandResult(success=False, command="bash", error="timeout")

    # --- Compaction ---

    def compact(self, custom_instructions: Optional[str] = None) -> CommandResult:
        """Manually compact conversation context."""
        self.start()
        req_id = self._next_id()
        cmd: dict[str, Any] = {"id": req_id, "type": "compact"}
        if custom_instructions:
            cmd["customInstructions"] = custom_instructions
        self._send(cmd)
        return self._wait_for_response(expected_type="response", timeout=30.0) or CommandResult(success=False, command="compact", error="timeout")

    def set_auto_compaction(self, enabled: bool) -> CommandResult:
        """Enable or disable automatic compaction."""
        self.start()
        req_id = self._next_id()
        self._send({"id": req_id, "type": "set_auto_compaction", "enabled": enabled})
        return self._wait_for_response(expected_type="response", timeout=30.0) or CommandResult(success=False, command="set_auto_compaction", error="timeout")

    # --- Session ---

    def new_session(self) -> CommandResult:
        """Start a fresh session."""
        self.start()
        req_id = self._next_id()
        self._send({"id": req_id, "type": "new_session"})
        return self._wait_for_response(expected_type="response", timeout=30.0) or CommandResult(success=False, command="new_session", error="timeout")

    def export_html(self, output_path: Optional[str] = None) -> CommandResult:
        """Export session to HTML."""
        self.start()
        req_id = self._next_id()
        cmd: dict[str, Any] = {"id": req_id, "type": "export_html"}
        if output_path:
            cmd["outputPath"] = output_path
        self._send(cmd)
        return self._wait_for_response(expected_type="response", timeout=30.0) or CommandResult(success=False, command="export_html", error="timeout")

    def set_session_name(self, name: str) -> CommandResult:
        """Set a display name for the current session."""
        self.start()
        req_id = self._next_id()
        self._send({"id": req_id, "type": "set_session_name", "name": name})
        return self._wait_for_response(expected_type="response", timeout=30.0) or CommandResult(success=False, command="set_session_name", error="timeout")

    def get_fork_messages(self) -> CommandResult:
        """Get user messages available for forking."""
        self.start()
        req_id = self._next_id()
        self._send({"id": req_id, "type": "get_fork_messages"})
        return self._wait_for_response(expected_type="response", timeout=30.0) or CommandResult(success=False, command="get_fork_messages", error="timeout")

    # --- Commands ---

    def get_commands(self) -> CommandResult:
        """Get available commands (extensions, prompt templates, skills)."""
        self.start()
        req_id = self._next_id()
        self._send({"id": req_id, "type": "get_commands"})
        return self._wait_for_response(expected_type="response", timeout=30.0) or CommandResult(success=False, command="get_commands", error="timeout")

    # --- Context ---

    def __enter__(self) -> "PiClient":
        """Context manager: start on enter."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager: stop on exit."""
        self.stop()

    def __del__(self) -> None:
        """Destructor: ensure process is stopped."""
        try:
            self.stop()
        except Exception:
            pass
