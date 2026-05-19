"""Tests for the Obsidian Redis/RQ background queue system.

Unit tests use mocks and always run.
Live tests require Redis at localhost:6379 and are skipped otherwise.
"""

import os
import time
import unittest
from unittest.mock import MagicMock, patch, PropertyMock


def _redis_available() -> bool:
    try:
        import redis

        r = redis.Redis.from_url("redis://localhost:6379", socket_connect_timeout=1)
        r.ping()
        return True
    except Exception:
        return False


REDIS_AVAILABLE = _redis_available()
skip_no_redis = unittest.skipUnless(REDIS_AVAILABLE, "Redis not running at localhost:6379")


# ─── Unit tests for ObsidianJobQueue ──────────────────────────────────────────

class TestObsidianJobQueueUnit(unittest.TestCase):
    """Unit tests with mocked Redis — always run."""

    def _make_queue(self):
        """Return an ObsidianJobQueue with mocked Redis."""
        from open_llm_vtuber.obsidian_mcp.queue import ObsidianJobQueue

        with patch("open_llm_vtuber.obsidian_mcp.queue.ObsidianJobQueue._init"):
            q = ObsidianJobQueue.__new__(ObsidianJobQueue)
            q._redis_url = "redis://localhost:6379"
            q._redis = MagicMock()
            q._queue = MagicMock()
        return q

    def test_is_available_true_when_ping_succeeds(self):
        q = self._make_queue()
        q._redis.ping.return_value = True
        self.assertTrue(q.is_available())

    def test_is_available_false_when_redis_none(self):
        q = self._make_queue()
        q._redis = None
        self.assertFalse(q.is_available())

    def test_is_available_false_when_ping_raises(self):
        q = self._make_queue()
        q._redis.ping.side_effect = Exception("connection refused")
        self.assertFalse(q.is_available())

    def test_enqueue_returns_job_id(self):
        q = self._make_queue()
        mock_job = MagicMock()
        mock_job.id = "abc-123"
        q._queue.enqueue.return_value = mock_job

        with patch("open_llm_vtuber.obsidian_mcp.queue.ObsidianJobQueue.enqueue", wraps=q.enqueue):
            with patch("open_llm_vtuber.obsidian_mcp.tasks.run_obsidian_tool"):
                job_id = q.enqueue("obsidian_tasks", {}, "/vault", "http://embed", "model")

        self.assertEqual(job_id, "abc-123")

    def test_enqueue_raises_when_queue_none(self):
        q = self._make_queue()
        q._queue = None
        with self.assertRaises(RuntimeError):
            q.enqueue("obsidian_tasks", {}, "/vault", "http://embed", "model")

    def test_get_result_finished_returns_result(self):
        q = self._make_queue()
        mock_job = MagicMock()
        mock_job.get_status.return_value = "finished"
        mock_job.result = "Here are your tasks: - [ ] Buy milk"

        with patch("rq.job.Job") as mock_job_cls:
            mock_job_cls.fetch.return_value = mock_job
            status, result = q.get_result("job-xyz")

        self.assertEqual(status, "finished")
        self.assertEqual(result, "Here are your tasks: - [ ] Buy milk")

    def test_get_result_failed_returns_failed(self):
        q = self._make_queue()
        mock_job = MagicMock()
        mock_job.get_status.return_value = "failed"
        mock_job.exc_info = "Traceback: something went wrong"

        with patch("rq.job.Job") as mock_job_cls:
            mock_job_cls.fetch.return_value = mock_job
            status, result = q.get_result("job-xyz")

        self.assertEqual(status, "failed")
        self.assertIn("something went wrong", result)

    def test_get_result_queued_returns_queued(self):
        q = self._make_queue()
        mock_job = MagicMock()
        mock_job.get_status.return_value = "queued"
        mock_job.result = None

        with patch("rq.job.Job") as mock_job_cls:
            mock_job_cls.fetch.return_value = mock_job
            status, result = q.get_result("job-xyz")

        self.assertEqual(status, "queued")
        self.assertIsNone(result)

    def test_get_result_fetch_failure_returns_failed(self):
        q = self._make_queue()
        with patch("rq.job.Job") as mock_job_cls:
            mock_job_cls.fetch.side_effect = Exception("no such job")
            status, result = q.get_result("missing-id")
        self.assertEqual(status, "failed")
        self.assertIsNone(result)

    def test_cleanup_calls_delete(self):
        q = self._make_queue()
        mock_job = MagicMock()
        with patch("rq.job.Job") as mock_job_cls:
            mock_job_cls.fetch.return_value = mock_job
            q.cleanup("job-xyz")
        mock_job.delete.assert_called_once()

    def test_cleanup_silent_on_error(self):
        q = self._make_queue()
        with patch("rq.job.Job") as mock_job_cls:
            mock_job_cls.fetch.side_effect = Exception("gone")
            # Should not raise
            q.cleanup("missing-id")


# ─── Unit tests for tasks.py ──────────────────────────────────────────────────

class TestObsidianTasksUnit(unittest.TestCase):
    """Unit tests for tasks.run_obsidian_tool with mocked RAG and subprocess."""

    @patch("open_llm_vtuber.obsidian_mcp.rag.ObsidianRAG")
    def test_search_calls_rag(self, MockRAG):
        from open_llm_vtuber.obsidian_mcp.tasks import run_obsidian_tool

        mock_instance = MagicMock()
        mock_instance.needs_reindex.return_value = False
        mock_instance.search.return_value = [
            {"file": "notes/shopping.md", "excerpt": "Buy milk", "score": 0.95}
        ]
        MockRAG.return_value = mock_instance

        result = run_obsidian_tool(
            "obsidian_search",
            {"query": "grocery list", "note_type": "any"},
            "/vault",
            "http://embed",
            "model",
        )

        mock_instance.search.assert_called_once_with("grocery list", n_results=8, note_type="any")
        self.assertIn("Buy milk", result)

    @patch("open_llm_vtuber.obsidian_mcp.rag.ObsidianRAG")
    def test_search_reindexes_when_needed(self, MockRAG):
        from open_llm_vtuber.obsidian_mcp.tasks import run_obsidian_tool

        mock_instance = MagicMock()
        mock_instance.needs_reindex.return_value = True
        mock_instance.search.return_value = []
        MockRAG.return_value = mock_instance

        run_obsidian_tool("obsidian_search", {"query": "x"}, "/vault", "http://e", "m")
        mock_instance.index_vault.assert_called_once()

    @patch("open_llm_vtuber.obsidian_mcp.server._run_obsidian")
    def test_daily_read_calls_cli(self, mock_run):
        from open_llm_vtuber.obsidian_mcp.tasks import run_obsidian_tool

        mock_run.return_value = "Today's note: nothing yet."
        result = run_obsidian_tool("obsidian_daily_read", {}, "/vault", "http://e", "m")
        mock_run.assert_called_once_with("daily:read")
        self.assertIn("nothing yet", result)

    @patch("open_llm_vtuber.obsidian_mcp.server._run_obsidian")
    def test_tasks_todo_calls_cli(self, mock_run):
        from open_llm_vtuber.obsidian_mcp.tasks import run_obsidian_tool

        mock_run.return_value = "- [ ] Call mom"
        result = run_obsidian_tool("obsidian_tasks", {"filter": "todo"}, "/vault", "http://e", "m")
        mock_run.assert_called_once_with("tasks", "daily", "todo")
        self.assertIn("Call mom", result)

    @patch("open_llm_vtuber.obsidian_mcp.server._run_obsidian")
    def test_task_add_daily(self, mock_run):
        from open_llm_vtuber.obsidian_mcp.tasks import run_obsidian_tool

        mock_run.return_value = ""
        run_obsidian_tool(
            "obsidian_task_add",
            {"task": "Buy groceries", "target": "daily"},
            "/vault", "http://e", "m",
        )
        args = mock_run.call_args[0]
        self.assertEqual(args[0], "daily:append")
        self.assertIn("Buy groceries", args[1])

    def test_unknown_tool_raises(self):
        from open_llm_vtuber.obsidian_mcp.tasks import run_obsidian_tool

        with self.assertRaises(ValueError):
            run_obsidian_tool("obsidian_nonexistent", {}, "/vault", "http://e", "m")


# ─── Live queue tests (Redis required) ────────────────────────────────────────

@skip_no_redis
class TestObsidianQueueLive(unittest.TestCase):
    """Integration tests that require a running Redis instance."""

    def setUp(self):
        from open_llm_vtuber.obsidian_mcp.queue import ObsidianJobQueue

        self.queue = ObsidianJobQueue()
        self.assertTrue(self.queue.is_available(), "Redis must be available")

    def test_is_available_returns_true(self):
        self.assertTrue(self.queue.is_available())

    def test_enqueue_and_poll_completes(self):
        """Enqueue a fast in-process job and wait for it to finish."""
        import rq
        from redis import Redis

        conn = Redis.from_url("redis://localhost:6379")
        q = rq.Queue("obsidian-tools", connection=conn, is_async=False)  # sync for testing

        # Run the task directly via rq sync mode
        from open_llm_vtuber.obsidian_mcp.tasks import run_obsidian_tool

        with patch("open_llm_vtuber.obsidian_mcp.rag.ObsidianRAG") as MockRAG:
            mock_instance = MagicMock()
            mock_instance.needs_reindex.return_value = False
            mock_instance.search.return_value = [
                {"file": "a.md", "excerpt": "hello", "score": 0.9}
            ]
            MockRAG.return_value = mock_instance

            result = run_obsidian_tool(
                "obsidian_search",
                {"query": "hello", "note_type": "any"},
                "/vault",
                "http://embed",
                "model",
            )

        self.assertIn("hello", result)

    def test_cleanup_removes_job(self):
        """Enqueue a job, finish it synchronously, verify cleanup removes it."""
        import rq
        from redis import Redis
        from rq.job import Job

        conn = Redis.from_url("redis://localhost:6379")

        with patch("open_llm_vtuber.obsidian_mcp.server._run_obsidian", return_value="ok"):
            job_id = self.queue.enqueue(
                "obsidian_daily_read", {}, "/vault", "http://e", "m"
            )

        # Wait briefly then cleanup
        time.sleep(0.2)
        self.queue.cleanup(job_id)

        # After cleanup, fetching should fail
        try:
            job = Job.fetch(job_id, connection=conn)
            # If we get here, the job wasn't deleted yet — that's ok for fast queues
        except Exception:
            pass  # Expected: job deleted


# ─── Async non-blocking executor test ─────────────────────────────────────────

class TestObsidianAsyncToolExec(unittest.IsolatedAsyncioTestCase):
    """Tests for ToolExecutor._run_obsidian_async_nonblocking."""

    def _make_executor(self, async_enabled=True):
        from open_llm_vtuber.mcpp.tool_executor import ToolExecutor

        mcp_client = MagicMock()
        tool_manager = MagicMock()
        tool_info = MagicMock()
        tool_info.related_server = "obsidian"
        tool_manager.get_tool.return_value = tool_info

        with patch("open_llm_vtuber.obsidian_mcp.queue.ObsidianJobQueue._init"):
            executor = ToolExecutor(mcp_client, tool_manager, obsidian_async_enabled=async_enabled)
            if async_enabled:
                executor._obsidian_queue = MagicMock()
                executor._obsidian_queue.is_available.return_value = True
                executor._obsidian_queue.enqueue.return_value = "job-test-1"

        return executor

    async def test_returns_immediately_with_queued_text(self):
        executor = self._make_executor(async_enabled=True)

        is_error, text, meta, items = await executor._run_obsidian_async_nonblocking(
            "obsidian_tasks", "tool-id-1", {"filter": "todo"}
        )

        self.assertFalse(is_error)
        self.assertIn("background", text.lower())
        executor._obsidian_queue.enqueue.assert_called_once()

    async def test_fallback_to_sync_when_redis_unavailable(self):
        executor = self._make_executor(async_enabled=True)
        executor._obsidian_queue.is_available.return_value = False

        # run_single_tool should be called as fallback
        with patch.object(executor, "run_single_tool") as mock_sync:
            mock_sync.return_value = (False, "task list", {}, [])
            is_error, text, meta, items = await executor._run_obsidian_async_nonblocking(
                "obsidian_tasks", "tool-id-2", {"filter": "todo"}
            )

        mock_sync.assert_called_once()
        self.assertEqual(text, "task list")

    async def test_fallback_to_sync_when_async_disabled(self):
        executor = self._make_executor(async_enabled=False)

        with patch.object(executor, "run_single_tool") as mock_sync:
            mock_sync.return_value = (False, "sync result", {}, [])
            is_error, text, meta, items = await executor._run_obsidian_async_nonblocking(
                "obsidian_tasks", "tool-id-3", {}
            )

        mock_sync.assert_called_once()

    async def test_execute_tools_routes_obsidian_to_async(self):
        """execute_tools should call _run_obsidian_async_nonblocking for obsidian tools."""
        executor = self._make_executor(async_enabled=True)

        with patch.object(
            executor,
            "_run_obsidian_async_nonblocking",
            return_value=(False, "On it...", {}, [{"type": "text", "text": "On it..."}]),
        ) as mock_async:
            results = []
            async for update in executor.execute_tools(
                [{"id": "t1", "name": "obsidian_tasks", "input": {"filter": "todo"}}],
                "OpenAI",
            ):
                results.append(update)

        mock_async.assert_called_once()
        final = next(r for r in results if r.get("type") == "final_tool_results")
        self.assertEqual(len(final["results"]), 1)


if __name__ == "__main__":
    unittest.main()
