from loguru import logger
from typing import Callable, Dict, Any, List, Literal, Optional

from .types import FormattedTool


class ToolManager:
    """Tool Manager for managing pre-formatted tools for different LLM APIs.

    Supports both MCP-based tools (via ToolAdapter) and direct Python callables
    registered with ``register_direct_tool``.
    """

    def __init__(
        self,
        formatted_tools_openai: List[Dict[str, Any]] = None,
        formatted_tools_claude: List[Dict[str, Any]] = None,
        initial_tools_dict: Dict[str, FormattedTool] = None,
    ) -> None:
        """Initialize the Tool Manager with pre-formatted tool lists."""
        # Store the raw tool data (optional, for get_tool)
        self.tools: Dict[str, FormattedTool] = initial_tools_dict or {}

        # Store the pre-formatted lists
        self._formatted_tools_openai: List[Dict[str, Any]] = (
            formatted_tools_openai or []
        )
        self._formatted_tools_claude: List[Dict[str, Any]] = (
            formatted_tools_claude or []
        )

        # Direct-call tools: name → (callable, openai_schema, claude_schema)
        self._direct_tools: Dict[str, tuple] = {}

        logger.info(
            f"ToolManager initialized with {len(self._formatted_tools_openai)} OpenAI tools and {len(self._formatted_tools_claude)} Claude tools."
        )

    def get_tool(self, tool_name: str) -> FormattedTool | None:
        """Get a tool's raw information by its name."""
        tool = self.tools.get(tool_name)
        if isinstance(tool, FormattedTool):
            return tool
        # Also check direct tools
        if tool_name in self._direct_tools:
            return self._direct_tools[tool_name][0]
        logger.warning(
            f"TM: Raw tool info for '{tool_name}' not found (was initial_tools_dict provided?)."
        )
        return None

    def register_direct_tool(
        self,
        name: str,
        func: Callable,
        openai_schema: Dict[str, Any],
        claude_schema: Dict[str, Any],
        description: str = "Direct Python tool",
    ) -> None:
        """Register a direct-call Python tool.

        Direct tools are executed locally (no MCP server) and are identified
        by ``related_server="direct"`` in the FormattedTool record.

        Args:
            name: Tool name used by the LLM.
            func: Async callable to execute when the tool is called.
            openai_schema: OpenAI-format tool definition.
            claude_schema: Claude-format tool definition.
            description: Human-readable description.
        """
        fmt_tool = FormattedTool(
            input_schema=openai_schema,
            related_server="direct",
            description=description,
        )
        self._direct_tools[name] = (fmt_tool, func, openai_schema, claude_schema)
        # Also store in tools dict for get_tool() compatibility
        self.tools[name] = fmt_tool

        # Add to pre-formatted tool lists
        self._formatted_tools_openai.append(openai_schema)
        self._formatted_tools_claude.append(claude_schema)

        logger.info(f"Registered direct tool: {name}")

    def get_direct_tool(self, name: str) -> Optional[Callable]:
        """Get a direct-call tool's async function by name."""
        entry = self._direct_tools.get(name)
        if entry:
            return entry[1]
        return None

    def get_formatted_tools(
        self, mode: Literal["OpenAI", "Claude"]
    ) -> List[Dict[str, Any]] | Any:
        """Get the pre-formatted list of tools for the specified API mode."""

        if mode == "OpenAI":
            return self._formatted_tools_openai
        elif mode == "Claude":
            return self._formatted_tools_claude
