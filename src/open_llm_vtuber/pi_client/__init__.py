"""
pi-client: Python client for the pi coding agent via RPC protocol.

Usage:
    from pi_client import PiClient

    client = PiClient()
    result = client.prompt("List all .ts files in src/")
    print(result.text)
    print(result.tools_used)

    # With centralized logging
    from pi_client import PiClient, LogConfig
    LogConfig.setup("pi_events.log", level="DEBUG")

    client = PiClient()
    # All events, tool calls, and subagent operations are logged
"""

from .client import PiClient
from .events import (
    AgentEvent,
    CommandResult,
    LogConfig,
    MessageEvent,
    PromptResult,
    TurnEvent,
    ToolEvent,
)
from .client import PiClient, PiConfig

__all__ = [
    "AgentEvent",
    "CommandResult",
    "LogConfig",
    "MessageEvent",
    "PiClient",
    "PiConfig",
    "PromptResult",
    "ToolEvent",
    "TurnEvent",
]
