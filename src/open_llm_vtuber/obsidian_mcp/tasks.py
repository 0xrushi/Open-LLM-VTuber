"""RQ-serializable job functions for background Obsidian tool calls.

These are module-level functions (no closures) so RQ can serialize them
across worker processes.
"""
from __future__ import annotations

import os


def run_obsidian_tool(
    tool_name: str,
    tool_args: dict,
    vault_path: str,
    embed_base_url: str,
    embed_model: str,
) -> str:
    """Execute an Obsidian tool synchronously inside an RQ worker process."""
    os.environ.setdefault("OBSIDIAN_VAULT_PATH", vault_path)

    if tool_name == "obsidian_search":
        from open_llm_vtuber.obsidian_mcp.rag import ObsidianRAG

        rag = ObsidianRAG(
            vault_path=vault_path,
            embed_base_url=embed_base_url,
            embed_model=embed_model,
        )
        if rag.needs_reindex():
            rag.index_vault()
        query = tool_args.get("query", "")
        note_type = tool_args.get("note_type", "any")
        results = rag.search(query, n_results=8, note_type=note_type)
        if not results:
            return "No matching notes found."
        parts = [f"[{r['file']}] (score: {r['score']})\n{r['excerpt']}" for r in results]
        return "\n\n---\n\n".join(parts)

    if tool_name == "discord_search":
        from open_llm_vtuber.obsidian_mcp import server as _srv

        return _srv.discord_search(tool_args.get("query", ""))

    if tool_name == "discord_sync":
        from open_llm_vtuber.obsidian_mcp import server as _srv

        return _srv.discord_sync()

    if tool_name == "twitter_search":
        from open_llm_vtuber.obsidian_mcp import server as _srv

        return _srv.twitter_search(tool_args.get("query", ""))

    if tool_name == "twitter_sync":
        from open_llm_vtuber.obsidian_mcp import server as _srv

        return _srv.twitter_sync()

    # All other tools delegate to the CLI helper in server.py
    from open_llm_vtuber.obsidian_mcp import server as _srv

    if tool_name == "obsidian_read":
        return _srv._run_obsidian("read", f"file={tool_args.get('file_name', '')}")

    if tool_name == "obsidian_create":
        name = tool_args.get("name", "")
        folder = tool_args.get("folder", "")
        content = tool_args.get("content", "")
        if folder:
            name = f"{folder}/{name}"
        escaped = content.replace("\n", "\\n").replace('"', '\\"')
        return (
            _srv._run_obsidian("create", f"name={name}", f"content={escaped}", "silent")
            or f"Note '{name}' created."
        )

    if tool_name == "obsidian_append":
        file_name = tool_args.get("file_name", "")
        content = tool_args.get("content", "")
        escaped = content.replace("\n", "\\n").replace('"', '\\"')
        return (
            _srv._run_obsidian("append", f"file={file_name}", f"content={escaped}")
            or f"Content appended to '{file_name}'."
        )

    if tool_name == "obsidian_tasks":
        filter_ = tool_args.get("filter", "todo")
        if filter_ == "todo":
            return _srv._run_obsidian("tasks", "daily", "todo")
        if filter_ == "done":
            return _srv._run_obsidian("tasks", "daily", "done")
        return _srv._run_obsidian("tasks")

    if tool_name == "obsidian_task_add":
        task = tool_args.get("task", "")
        target = tool_args.get("target", "daily")
        escaped = f"- [ ] {task}".replace('"', '\\"')
        if target == "daily":
            return _srv._run_obsidian("daily:append", f"content={escaped}")
        return _srv._run_obsidian("append", f"file={target}", f"content={escaped}")

    if tool_name == "obsidian_daily_read":
        return _srv._run_obsidian("daily:read")

    if tool_name == "obsidian_daily_append":
        content = tool_args.get("content", "")
        escaped = content.replace("\n", "\\n").replace('"', '\\"')
        return _srv._run_obsidian("daily:append", f"content={escaped}")

    raise ValueError(f"Unknown Obsidian tool: {tool_name}")
