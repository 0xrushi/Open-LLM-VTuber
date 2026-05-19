import unittest
from unittest.mock import MagicMock, patch


class TestObsidianWorkerSelection(unittest.TestCase):
    @patch("src.open_llm_vtuber.obsidian_mcp.worker.Queue")
    @patch("src.open_llm_vtuber.obsidian_mcp.worker.Redis")
    @patch("src.open_llm_vtuber.obsidian_mcp.worker.SimpleWorker")
    @patch("src.open_llm_vtuber.obsidian_mcp.worker.Worker")
    @patch("src.open_llm_vtuber.obsidian_mcp.worker.platform.system", return_value="Darwin")
    def test_main_uses_simple_worker_on_macos(
        self,
        _mock_system,
        mock_worker,
        mock_simple_worker,
        mock_redis,
        mock_queue,
    ):
        from src.open_llm_vtuber.obsidian_mcp.worker import main

        mock_conn = MagicMock()
        mock_redis.from_url.return_value = mock_conn
        mock_queue.side_effect = [MagicMock(), MagicMock()]

        main()

        mock_simple_worker.assert_called_once()
        mock_simple_worker.return_value.work.assert_called_once()
        mock_worker.assert_not_called()

    @patch("src.open_llm_vtuber.obsidian_mcp.worker.Queue")
    @patch("src.open_llm_vtuber.obsidian_mcp.worker.Redis")
    @patch("src.open_llm_vtuber.obsidian_mcp.worker.SimpleWorker")
    @patch("src.open_llm_vtuber.obsidian_mcp.worker.Worker")
    @patch("src.open_llm_vtuber.obsidian_mcp.worker.platform.system", return_value="Linux")
    def test_main_uses_worker_on_non_macos(
        self,
        _mock_system,
        mock_worker,
        mock_simple_worker,
        mock_redis,
        mock_queue,
    ):
        from src.open_llm_vtuber.obsidian_mcp.worker import main

        mock_conn = MagicMock()
        mock_redis.from_url.return_value = mock_conn
        mock_queue.side_effect = [MagicMock(), MagicMock()]

        main()

        mock_worker.assert_called_once()
        mock_worker.return_value.work.assert_called_once()
        mock_simple_worker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
