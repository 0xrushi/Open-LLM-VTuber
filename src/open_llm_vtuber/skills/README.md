# Direct-Call Skills

These are Python-callable tools that the LLM can invoke via tool calling.
They bypass the MCP server pipeline and execute locally.

## How it works

1. **Define a skill** — an async Python function in its own submodule
2. **Register it** — call `ToolManager.register_direct_tool()` with the function and schemas
3. **Execute it** — `ToolExecutor._run_direct_tool()` calls the async function directly

## Adding a new skill

### 1. Create the skill module

```python
# src/open_llm_vtuber/skills/my_skill.py
async def my_tool(query: str, limit: int = 10) -> str:
    """Search/do something and return results."""
    ...
```

### 2. Define tool schemas

```python
MY_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "my_tool",
        "description": "What the tool does.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The query."},
                "limit": {"type": "integer", "description": "Max results."},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}
```

### 3. Register it in startup wiring

In your initialization path, register it with `ToolManager`:

```python
from .skills.my_skill import MY_TOOL_SCHEMA, my_tool

tool_manager.register_direct_tool(
    name="my_tool",
    func=my_tool,
    openai_schema=MY_TOOL_SCHEMA,
    claude_schema=MY_TOOL_SCHEMA,
    description="What the tool does.",
)
```

## Existing skills

| Skill | Tools | Description |
|-------|-------|-------------|
| _None currently_ | - | Direct-call skills are optional and can be added as needed. |
