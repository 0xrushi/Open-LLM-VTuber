"""Integration tests for the Obsidian MCP server and RAG module.

Unit tests mock subprocess — always run.
CLI integration tests skip if `obsidian` binary is not in PATH.
RAG integration tests skip if the embedding server is not reachable.
"""

import os
import subprocess
import unittest
from unittest.mock import MagicMock, patch

# Target under test
from src.open_llm_vtuber.obsidian_mcp import server as obs_server
from src.open_llm_vtuber.obsidian_mcp.server import (
    _run_obsidian,
    obsidian_append,
    obsidian_create,
    obsidian_daily_append,
    obsidian_daily_read,
    obsidian_read,
    obsidian_task_add,
    obsidian_tasks,
)

VAULT_PATH = os.environ.get(
    "OBSIDIAN_VAULT_PATH", "/Users/bread/Documents/subsidian/453792"
)
EMBED_BASE_URL = os.environ.get("EMBED_BASE_URL", "https://llm.emberfang.xyz/v1")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text-v1.5")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CLI_PATH = os.environ.get(
    "OBSIDIAN_CLI_PATH",
    "/Applications/Obsidian.app/Contents/MacOS/obsidian-cli",
)


def _cli_available() -> bool:
    try:
        result = subprocess.run(
            [_CLI_PATH, "help"], capture_output=True, text=True, timeout=5
        )
        output = result.stdout + result.stderr
        return "not enabled" not in output
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _embed_server_available() -> bool:
    try:
        import urllib.request
        urllib.request.urlopen(f"{EMBED_BASE_URL}/models", timeout=3)
        return True
    except Exception:
        return False


def _make_completed_process(stdout="", stderr="", returncode=0):
    p = MagicMock()
    p.stdout = stdout
    p.stderr = stderr
    p.returncode = returncode
    return p


# ---------------------------------------------------------------------------
# Unit tests — _run_obsidian subprocess wiring
# ---------------------------------------------------------------------------

class TestRunObsidian(unittest.TestCase):
    def _patch(self, *args, **kwargs):
        return patch("src.open_llm_vtuber.obsidian_mcp.server.subprocess.run", *args, **kwargs)

    def test_builds_correct_command(self):
        with self._patch(return_value=_make_completed_process("ok")) as mock_run:
            result = _run_obsidian("daily:read")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[1:], ["daily:read"])
        self.assertIn("obsidian", cmd[0])
        self.assertEqual(result, "ok")

    def test_passes_multiple_args(self):
        with self._patch(return_value=_make_completed_process("done")) as mock_run:
            _run_obsidian("tasks", "daily", "todo")
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[1:], ["tasks", "daily", "todo"])
        self.assertIn("obsidian", cmd[0])

    def test_returns_stdout_stripped(self):
        with self._patch(return_value=_make_completed_process("  hello world  \n")):
            result = _run_obsidian("daily:read")
        self.assertEqual(result, "hello world")

    def test_returns_error_string_on_nonzero_exit_with_stderr(self):
        with self._patch(return_value=_make_completed_process("", "something broke", 1)):
            result = _run_obsidian("read", "file=missing")
        self.assertTrue(result.startswith("Error:"))
        self.assertIn("something broke", result)

    def test_returns_empty_on_nonzero_exit_without_stderr(self):
        # returncode != 0 but stderr is empty — treat as empty output
        with self._patch(return_value=_make_completed_process("", "", 1)):
            result = _run_obsidian("read", "file=missing")
        self.assertEqual(result, "")

    def test_handles_file_not_found(self):
        with self._patch(side_effect=FileNotFoundError):
            result = _run_obsidian("daily:read")
        self.assertIn("obsidian CLI not found", result)

    def test_handles_timeout(self):
        with self._patch(side_effect=subprocess.TimeoutExpired("obsidian", 15)):
            result = _run_obsidian("daily:read")
        self.assertIn("timed out", result)

    def test_handles_generic_exception(self):
        with self._patch(side_effect=OSError("permission denied")):
            result = _run_obsidian("daily:read")
        self.assertIn("Error running obsidian CLI", result)
        self.assertIn("permission denied", result)


# ---------------------------------------------------------------------------
# Unit tests — each tool function
# ---------------------------------------------------------------------------

class TestObsidianTools(unittest.TestCase):
    def _patch_run(self, return_value=""):
        return patch(
            "src.open_llm_vtuber.obsidian_mcp.server._run_obsidian",
            return_value=return_value,
        )

    # --- obsidian_read ---

    def test_read_passes_file_arg(self):
        with self._patch_run("content") as m:
            result = obsidian_read("My Note")
        m.assert_called_once_with("read", "file=My Note")
        self.assertEqual(result, "content")

    # --- obsidian_create ---

    def test_create_no_folder(self):
        with self._patch_run() as m:
            obsidian_create("Test Note", "# Hello")
        args = m.call_args[0]
        self.assertEqual(args[0], "create")
        self.assertIn("name=Test Note", args)
        self.assertIn("silent", args)

    def test_create_with_folder_prefixes_name(self):
        with self._patch_run() as m:
            obsidian_create("Test Note", "content", folder="Projects/Work")
        args = m.call_args[0]
        self.assertIn("name=Projects/Work/Test Note", args)

    def test_create_escapes_newlines_in_content(self):
        with self._patch_run() as m:
            obsidian_create("Note", "line1\nline2")
        content_arg = [a for a in m.call_args[0] if a.startswith("content=")][0]
        self.assertIn("\\n", content_arg)
        self.assertNotIn("\n", content_arg)

    def test_create_escapes_double_quotes_in_content(self):
        with self._patch_run() as m:
            obsidian_create("Note", 'say "hello"')
        content_arg = [a for a in m.call_args[0] if a.startswith("content=")][0]
        self.assertIn('\\"', content_arg)

    def test_create_returns_fallback_when_cli_returns_empty(self):
        with self._patch_run(""):
            result = obsidian_create("MyNote", "content")
        self.assertIn("MyNote", result)

    # --- obsidian_append ---

    def test_append_passes_file_and_content(self):
        with self._patch_run("ok") as m:
            result = obsidian_append("My Note", "new line")
        m.assert_called_once_with("append", "file=My Note", "content=new line")
        self.assertEqual(result, "ok")

    def test_append_escapes_newlines(self):
        with self._patch_run() as m:
            obsidian_append("Note", "a\nb")
        content_arg = m.call_args[0][2]
        self.assertIn("\\n", content_arg)

    def test_append_returns_fallback_when_empty(self):
        with self._patch_run(""):
            result = obsidian_append("My Note", "x")
        self.assertIn("My Note", result)

    # --- obsidian_tasks ---

    def test_tasks_todo_filter(self):
        with self._patch_run() as m:
            obsidian_tasks("todo")
        m.assert_called_once_with("tasks", "daily", "todo")

    def test_tasks_done_filter(self):
        with self._patch_run() as m:
            obsidian_tasks("done")
        m.assert_called_once_with("tasks", "daily", "done")

    def test_tasks_all_filter(self):
        with self._patch_run() as m:
            obsidian_tasks("all")
        m.assert_called_once_with("tasks")

    def test_tasks_default_is_todo(self):
        with self._patch_run() as m:
            obsidian_tasks()
        m.assert_called_once_with("tasks", "daily", "todo")

    # --- obsidian_task_add ---

    def test_task_add_daily_appends_to_daily(self):
        with self._patch_run() as m:
            obsidian_task_add("Buy milk", "daily")
        args = m.call_args[0]
        self.assertEqual(args[0], "daily:append")
        self.assertIn("- [ ] Buy milk", args[1])

    def test_task_add_named_note_appends_to_file(self):
        with self._patch_run() as m:
            obsidian_task_add("Fix bug", "Project Notes")
        args = m.call_args[0]
        self.assertEqual(args[0], "append")
        self.assertIn("file=Project Notes", args)
        content_arg = [a for a in args if "- [ ]" in a][0]
        self.assertIn("Fix bug", content_arg)

    def test_task_add_escapes_quotes_in_task(self):
        with self._patch_run() as m:
            obsidian_task_add('Say "hello"', "daily")
        content_arg = m.call_args[0][1]
        self.assertIn('\\"', content_arg)

    # --- obsidian_daily_read / obsidian_daily_append ---

    def test_daily_read_calls_daily_read(self):
        with self._patch_run("today's note") as m:
            result = obsidian_daily_read()
        m.assert_called_once_with("daily:read")
        self.assertEqual(result, "today's note")

    def test_daily_append_calls_daily_append(self):
        with self._patch_run() as m:
            obsidian_daily_append("- [ ] Call mom")
        m.assert_called_once_with("daily:append", "content=- [ ] Call mom")

    def test_daily_append_escapes_newlines(self):
        with self._patch_run() as m:
            obsidian_daily_append("line1\nline2")
        content_arg = m.call_args[0][1]
        self.assertIn("\\n", content_arg)


# ---------------------------------------------------------------------------
# CLI integration tests — require `obsidian` binary in PATH
# ---------------------------------------------------------------------------

@unittest.skipUnless(_cli_available(), "obsidian CLI not enabled — go to Obsidian Settings → General → Advanced → Enable CLI")
class TestObsidianCLILive(unittest.TestCase):
    """Tests that exercise the real obsidian CLI. Obsidian app must be open."""

    def test_daily_read_returns_string(self):
        result = obsidian_daily_read()
        self.assertIsInstance(result, str)
        self.assertNotIn("Error:", result[:20])

    def test_tasks_todo_returns_string(self):
        result = obsidian_tasks("todo")
        self.assertIsInstance(result, str)

    def test_task_add_and_verify(self):
        import time
        marker = f"integration-test-{int(time.time())}"
        add_result = obsidian_task_add(marker, "daily")
        self.assertNotIn("Error:", str(add_result)[:20])

        # Read back daily note and check marker appears
        daily = obsidian_daily_read()
        self.assertIn(marker, daily, "Added task not found in daily note")

    def test_create_read_and_cleanup(self):
        import time
        note_name = f"_integration_test_{int(time.time())}"
        content = "# Integration Test\nThis note was created by the test suite."

        create_result = obsidian_create(note_name, content)
        self.assertNotIn("Error:", str(create_result)[:20])

        read_result = obsidian_read(note_name)
        self.assertIn("Integration Test", read_result)

        # Cleanup: append a deletion note (we can't delete via CLI, so just mark it)
        obsidian_append(note_name, "\n> [!NOTE] Safe to delete — created by integration tests.")

    def test_append_to_daily(self):
        import time
        marker = f"append-test-{int(time.time())}"
        result = obsidian_daily_append(f"- append test marker: {marker}")
        self.assertNotIn("Error:", str(result)[:20])

        daily = obsidian_daily_read()
        self.assertIn(marker, daily)


# ---------------------------------------------------------------------------
# RAG integration tests — require embedding server at EMBED_BASE_URL
# ---------------------------------------------------------------------------

@unittest.skipUnless(_embed_server_available(), f"Embedding server not reachable at {EMBED_BASE_URL}")
class TestObsidianRAGLive(unittest.TestCase):
    """Tests that exercise the real RAG indexer against the local vault."""

    @classmethod
    def setUpClass(cls):
        from src.open_llm_vtuber.obsidian_mcp.rag import ObsidianRAG
        cls.rag = ObsidianRAG(
            vault_path=VAULT_PATH,
            embed_base_url=EMBED_BASE_URL,
            embed_model=EMBED_MODEL,
        )

    def test_vault_path_exists(self):
        import os
        self.assertTrue(os.path.isdir(VAULT_PATH), f"Vault not found: {VAULT_PATH}")

    def test_index_vault_runs_without_error(self):
        # Force a fresh index of a small slice — don't force full re-index in CI
        self.rag.index_vault(force=False)  # incremental is fine

    def test_search_returns_results(self):
        results = self.rag.search("notes", n_results=3)
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)

    def test_search_result_schema(self):
        results = self.rag.search("project", n_results=2)
        self.assertTrue(len(results) > 0)
        r = results[0]
        self.assertIn("file", r)
        self.assertIn("excerpt", r)
        self.assertIn("score", r)
        self.assertIsInstance(r["file"], str)
        self.assertIsInstance(r["excerpt"], str)
        self.assertIsInstance(r["score"], float)

    def test_search_score_in_range(self):
        results = self.rag.search("calendar event", n_results=5)
        for r in results:
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 1.0)

    def test_search_note_type_filter_any(self):
        results = self.rag.search("test", n_results=3, note_type="any")
        self.assertIsInstance(results, list)

    def test_needs_reindex_returns_bool(self):
        result = self.rag.needs_reindex()
        self.assertIsInstance(result, bool)

    def test_obsidian_search_tool_returns_string(self):
        # Resets the global singleton to use test config
        import src.open_llm_vtuber.obsidian_mcp.server as s
        original = s._rag_instance
        s._rag_instance = self.rag
        try:
            result = obs_server.obsidian_search("project notes")
            self.assertIsInstance(result, str)
            self.assertNotEqual(result, "")
        finally:
            s._rag_instance = original

    def test_obsidian_search_no_results_message(self):
        # Extremely specific query unlikely to match anything
        result = obs_server.obsidian_search(
            "xyzzy_nonexistent_token_9999999", note_type="any"
        )
        # Either returns results or the "no matching" message — not an error
        self.assertIsInstance(result, str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
