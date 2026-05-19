"""
Skill → MCP URL registry.

Skills listed here are wired directly as MCPServerStreamableHTTP toolsets,
giving the pydantic-ai agent native access to all tools the skill exposes.

Skills NOT in this registry fall back to the pi subprocess tool, which runs
pi with the skill loaded and calls it as a black-box tool.

You can extend SKILL_MCP at runtime:
    from pi_agent_py.registry import SKILL_MCP
    SKILL_MCP["my-skill"] = "http://127.0.0.1:9999/mcp"
"""

SKILL_MCP: dict[str, str] = {
    "browseros-pi": "http://127.0.0.1:9003/mcp",
}
