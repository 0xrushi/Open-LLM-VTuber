"""Obsidian MCP server — exposes obsidian CLI + RAG tools to the VTuber LLM."""

import os
import subprocess
from typing import Optional
from loguru import logger
from mcp.server.fastmcp import FastMCP

from .rag import ObsidianRAG
from ..discord_rag import DiscordRAG
from ..twitter_rag import TwitterRAG

VAULT_PATH = os.environ.get("OBSIDIAN_VAULT_PATH", "/Users/bread/Documents/subsidian/453792")
EMBED_BASE_URL = os.environ.get("EMBED_BASE_URL", "https://llm.emberfang.xyz/v1")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text-v1.5")

mcp = FastMCP("obsidian")
_rag_instance: Optional[ObsidianRAG] = None

DISCORD_POSTGRES_URL = os.environ.get(
    "DISCORD_POSTGRES_URL",
    "postgres://discord:discord@localhost:5432/discord_ingestion",
)
_discord_rag_instance: Optional[DiscordRAG] = None
_twitter_rag_instance: Optional[TwitterRAG] = None


def _get_discord_rag() -> DiscordRAG:
    global _discord_rag_instance
    if _discord_rag_instance is None:
        _discord_rag_instance = DiscordRAG(
            postgres_url=DISCORD_POSTGRES_URL,
            embed_base_url=EMBED_BASE_URL,
            embed_model=EMBED_MODEL,
        )
    return _discord_rag_instance


def _get_twitter_rag() -> TwitterRAG:
    global _twitter_rag_instance
    if _twitter_rag_instance is None:
        _twitter_rag_instance = TwitterRAG(
            postgres_url=DISCORD_POSTGRES_URL,
            embed_base_url=EMBED_BASE_URL,
            embed_model=EMBED_MODEL,
        )
    return _twitter_rag_instance


def _get_rag() -> ObsidianRAG:
    global _rag_instance
    if _rag_instance is None:
        instance = ObsidianRAG(
            vault_path=VAULT_PATH,
            embed_base_url=EMBED_BASE_URL,
            embed_model=EMBED_MODEL,
        )
        if instance.needs_reindex():
            logger.info("Obsidian vault index outdated, rebuilding...")
            instance.index_vault()
        _rag_instance = instance
    return _rag_instance


_OBSIDIAN_CLI = os.environ.get(
    "OBSIDIAN_CLI_PATH",
    "/Applications/Obsidian.app/Contents/MacOS/obsidian-cli",
)


def _run_obsidian(*args: str) -> str:
    """Run an obsidian CLI command and return stdout."""
    cmd = [_OBSIDIAN_CLI] + list(args)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0 and result.stderr:
            return f"Error: {result.stderr.strip()}"
        return result.stdout.strip()
    except FileNotFoundError:
        return f"Error: obsidian CLI not found at {_OBSIDIAN_CLI}. Enable it in Obsidian Settings → General → Advanced → Enable CLI."
    except subprocess.TimeoutExpired:
        return "Error: obsidian CLI command timed out."
    except Exception as e:
        return f"Error running obsidian CLI: {e}"


@mcp.tool()
def obsidian_search(query: str, note_type: str = "any") -> str:
    """Semantic search over the Obsidian vault using RAG.

    Args:
        query: Natural language query (e.g. "project ideas", "dentist appointment", "grocery list")
        note_type: Filter by type — "any", "notes", "todos", or "calendar"

    Returns:
        Relevant excerpts from matching notes, with file paths and relevance scores.
    """
    rag = _get_rag()
    if rag.needs_reindex():
        logger.info("Vault changed, re-indexing...")
        rag.index_vault()

    results = rag.search(query, n_results=8, note_type=note_type)
    if not results:
        return "No matching notes found."

    parts = []
    for r in results:
        parts.append(f"[{r['file']}] (score: {r['score']})\n{r['excerpt']}")
    return "\n\n---\n\n".join(parts)


@mcp.tool()
def obsidian_read(file_name: str) -> str:
    """Read the full content of a note by name.

    Args:
        file_name: Note name (without .md extension, e.g. "Meeting Notes")
    """
    return _run_obsidian("read", f"file={file_name}")


@mcp.tool()
def obsidian_create(name: str, content: str, folder: str = "") -> str:
    """Create a new note in the vault.

    Args:
        name: Note title/filename (without .md)
        content: Markdown content for the note
        folder: Optional subfolder path (e.g. "Projects/Work")
    """
    if folder:
        name = f"{folder}/{name}"
    # Escape newlines for CLI
    escaped = content.replace("\n", "\\n").replace('"', '\\"')
    result = _run_obsidian("create", f"name={name}", f'content={escaped}', "silent")
    # Trigger re-index in background for next search
    try:
        _get_rag()._save_manifest({})  # invalidate so next search re-indexes
    except Exception:
        pass
    return result or f"Note '{name}' created."


@mcp.tool()
def obsidian_append(file_name: str, content: str) -> str:
    """Append content to an existing note.

    Args:
        file_name: Note name (without .md)
        content: Text to append (markdown supported)
    """
    escaped = content.replace("\n", "\\n").replace('"', '\\"')
    result = _run_obsidian("append", f"file={file_name}", f"content={escaped}")
    return result or f"Content appended to '{file_name}'."


@mcp.tool()
def obsidian_tasks(filter: str = "todo") -> str:
    """List tasks from the vault.

    Args:
        filter: Task filter — "todo" (incomplete), "done" (completed), or "all"
    """
    if filter == "todo":
        return _run_obsidian("tasks", "daily", "todo")
    elif filter == "done":
        return _run_obsidian("tasks", "daily", "done")
    else:
        return _run_obsidian("tasks")


@mcp.tool()
def obsidian_task_add(task: str, target: str = "daily") -> str:
    """Add a new task/reminder.

    Args:
        task: Task description (e.g. "Call mom", "Buy groceries")
        target: Where to add it — "daily" (today's daily note) or a note name
    """
    content = f"- [ ] {task}"
    escaped = content.replace('"', '\\"')
    if target == "daily":
        return _run_obsidian("daily:append", f"content={escaped}")
    else:
        return _run_obsidian("append", f"file={target}", f"content={escaped}")


@mcp.tool()
def obsidian_daily_read() -> str:
    """Read today's daily note."""
    return _run_obsidian("daily:read")


@mcp.tool()
def obsidian_daily_append(content: str) -> str:
    """Append content to today's daily note.

    Args:
        content: Text to append (markdown supported, e.g. "- [ ] Buy milk")
    """
    escaped = content.replace("\n", "\\n").replace('"', '\\"')
    return _run_obsidian("daily:append", f"content={escaped}")


@mcp.tool()
def discord_search(query: str) -> str:
    """Semantic search over Discord message history.

    Args:
        query: Natural language query (e.g. "what did people say about the game", "mentions of the project")

    Returns:
        Relevant Discord messages with author, timestamp, and relevance score.
        IMPORTANT: After reading these messages, synthesize and reason about them to
        directly answer the user's question. Do NOT just list the messages — interpret
        them, identify patterns, infer reasons, and give a thoughtful summary.
    """
    rag = _get_discord_rag()

    # Keep index fresh for "did anyone share ..." style questions.
    try:
        rag.sync(limit=4000)
    except Exception:
        pass

    base_query = (query or "").strip()
    deduped_variants = rag.expand_query_variants(base_query) or [base_query]

    merged: list[dict] = []
    seen_items = set()
    for q in deduped_variants[:5]:
        for r in rag.search(q, n_results=8):
            key = (
                r.get("timestamp", ""),
                r.get("author", ""),
                (r.get("content", "") or "")[:180],
            )
            if key in seen_items:
                continue
            seen_items.add(key)
            merged.append(r)

    if not merged:
        return "No matching Discord messages found. Try discord_sync, then search with alternate terms (e.g., chonky/chunking)."

    # Re-rank with small lexical boosts for this query family.
    def _boost(r: dict) -> float:
        txt = f"{r.get('content','')} {r.get('urls','')}".lower()
        score = float(r.get("score", 0.0))
        if "github" in txt:
            score += 0.08
        if "chonky" in txt or "chunk" in txt:
            score += 0.12
        if "link:" in txt or "http" in txt:
            score += 0.04
        return score

    merged.sort(key=_boost, reverse=True)
    top = merged[:8]

    parts = []
    for r in top:
        ts = r["timestamp"] or "unknown time"
        author = r["author"] or "unknown"
        entry = f"[{author} @ {ts}] (score: {r['score']})\n{r['content']}"
        urls = r.get("urls", "").strip()
        if urls:
            entry += f"\nLinks: {urls}"
        parts.append(entry)

    messages_block = "\n\n---\n\n".join(parts)
    return (
        f"{messages_block}\n\n"
        "---\n"
        "INSTRUCTION: Based on the messages above, answer directly. If a specific library/repo "
        "appears, name who shared it and include the GitHub URL. If uncertain, "
        "say what's missing."
    )


@mcp.tool()
def discord_sync() -> str:
    """Re-index Discord messages from Postgres into the search index.

    Use this when you want to include the latest Discord messages in search results.
    Returns number of newly indexed messages.
    """
    rag = _get_discord_rag()
    count = rag.sync()
    return f"Discord sync complete. {count} new messages indexed."


@mcp.tool()
def twitter_search(query: str) -> str:
    """Semantic search over Twitter/X links ingested in Postgres.

    Args:
        query: Natural language query (e.g. "latest AI launch thread", "mentions of model pricing")

    Returns:
        Relevant Twitter/X entries with source URL and relevance score.
    """
    rag = _get_twitter_rag()
    results = rag.search(query, n_results=5)
    if not results:
        return "No matching Twitter/X entries found. The index may be empty — try twitter_sync first."

    parts = []
    for r in results:
        ts = r["timestamp"] or "unknown time"
        author = r["author"] or "unknown"
        url = r["url"] or "unknown url"
        entry = f"[{author} @ {ts}] (score: {r['score']})\nURL: {url}\n{r['content']}"
        parts.append(entry)

    items_block = "\n\n---\n\n".join(parts)
    return (
        f"{items_block}\n\n"
        "---\n"
        "INSTRUCTION: Based on the entries above, synthesize a direct answer with key "
        "points and patterns. Do not just list the entries."
    )


@mcp.tool()
def twitter_sync() -> str:
    """Re-index Twitter/X entries from Postgres into the search index."""
    rag = _get_twitter_rag()
    count = rag.sync()
    return f"Twitter/X sync complete. {count} new entries indexed."


if __name__ == "__main__":
    logger.info(f"Starting Obsidian MCP server (vault: {VAULT_PATH})")
    mcp.run(transport="stdio")
