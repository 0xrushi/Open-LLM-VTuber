"""
Event types and logging for pi-client.

Centralized logging captures:
- All RPC commands sent (prompt, bash, steer, etc.)
- All events received from pi (agent_start, message_update, tool_execution, etc.)
- Tool call results and subagent operations
- Errors and retries
"""

import logging
import json
from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime

# --- Centralized Logger ---

_logger: Optional[logging.Logger] = None


class LogConfig:
    """Configure centralized logging for pi-client."""

    @staticmethod
    def setup(
        log_file: Optional[str] = None,
        level: str = "INFO",
        console: bool = True,
    ) -> logging.Logger:
        """
        Set up the centralized pi-client logger.

        Args:
            log_file: Path to log file. None = no file logging.
            level: Logging level (DEBUG, INFO, WARNING, ERROR).
            console: Whether to also log to console.

        Returns:
            The configured logger instance.
        """
        global _logger
        _logger = logging.getLogger("pi_client")
        _logger.setLevel(getattr(logging, level.upper(), logging.INFO))
        _logger.handlers.clear()

        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            datefmt="%H:%M:%S",
        )

        if log_file:
            fh = logging.FileHandler(log_file, mode="a")
            fh.setFormatter(fmt)
            _logger.addHandler(fh)

        if console:
            ch = logging.StreamHandler()
            ch.setFormatter(fmt)
            _logger.addHandler(ch)

        return _logger


def _get_logger() -> logging.Logger:
    """Get the centralized logger, creating it if needed."""
    global _logger
    if _logger is None:
        _logger = LogConfig.setup(console=True)
    return _logger


# --- Event Dataclasses ---


@dataclass
class AgentEvent:
    """Base class for all pi events."""
    type: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    raw: dict = field(default_factory=dict)


@dataclass
class TurnEvent(AgentEvent):
    """A turn = one assistant response + tool calls + results."""
    turn_index: int = 0
    message: Optional[dict] = None
    tool_results: list = field(default_factory=list)


@dataclass
class MessageEvent(AgentEvent):
    """Streaming message event from the agent."""
    delta_type: str = ""  # text_delta, toolcall_delta, thinking_delta, etc.
    content: str = ""
    partial: Optional[dict] = None


@dataclass
class ToolEvent(AgentEvent):
    """Tool execution event (start/update/end)."""
    tool_name: str = ""
    tool_call_id: str = ""
    args: dict = field(default_factory=dict)
    result: Optional[dict] = None
    is_error: bool = False


@dataclass
class CommandResult:
    """Result of an RPC command."""
    success: bool
    command: str
    data: Optional[dict] = None
    error: Optional[str] = None
    id: Optional[str] = None


@dataclass
class PromptResult:
    """Result of a prompt — includes final text and tool usage."""
    text: str
    thinking: str = ""
    tools_used: list = field(default_factory=list)
    tool_results: list = field(default_factory=list)
    model: Optional[str] = None
    tokens_input: int = 0
    tokens_output: int = 0
    cost: float = 0.0
    stop_reason: str = "stop"


def log_command(cmd: dict) -> None:
    """Log an RPC command being sent."""
    logger = _get_logger()
    logger.debug("COMMAND  | type=%s | id=%s | payload=%s",
                 cmd.get("type"), cmd.get("id"),
                 {k: v for k, v in cmd.items() if k not in ("images",)})


def log_response(result: CommandResult) -> None:
    """Log an RPC response."""
    logger = _get_logger()
    status = "OK" if result.success else "FAIL"
    logger.info("RESPONSE | %s | cmd=%s | id=%s | err=%s",
                status, result.command, result.id, result.error)


def log_event(event: AgentEvent) -> None:
    """Log a streaming event."""
    logger = _get_logger()
    if isinstance(event, ToolEvent):
        logger.info("TOOL     | %s | tool=%s | call=%s | error=%s",
                     event.type, event.tool_name, event.tool_call_id, event.is_error)
    elif isinstance(event, MessageEvent):
        if event.delta_type == "text_delta":
            logger.debug("STREAM   | delta=%s | text=%s",
                         event.delta_type, event.content[:100])
        elif event.delta_type in ("toolcall_start", "toolcall_delta", "toolcall_end"):
            logger.debug("STREAM   | delta=%s | toolcall=True", event.delta_type)
        else:
            logger.debug("STREAM   | delta=%s", event.delta_type)
    else:
        logger.debug("EVENT    | type=%s", event.type)


def log_error(message: str, exc: Optional[Exception] = None) -> None:
    """Log an error."""
    logger = _get_logger()
    if exc:
        logger.error("ERROR    | %s | %s", message, exc)
    else:
        logger.error("ERROR    | %s", message)