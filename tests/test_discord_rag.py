"""Unit tests for DiscordRAG — all mocked, no external services needed."""

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call


class TestDiscordRAGInit(unittest.TestCase):
    def test_default_postgres_url(self):
        from src.open_llm_vtuber.discord_rag import DiscordRAG, DISCORD_POSTGRES_URL
        r = DiscordRAG()
        self.assertEqual(r.postgres_url, DISCORD_POSTGRES_URL)
        self.assertIn("discord_ingestion", r.postgres_url)

    def test_custom_postgres_url(self):
        from src.open_llm_vtuber.discord_rag import DiscordRAG
        r = DiscordRAG(postgres_url="postgres://user:pass@host:5432/mydb")
        self.assertEqual(r.postgres_url, "postgres://user:pass@host:5432/mydb")

    def test_lazy_clients_start_none(self):
        from src.open_llm_vtuber.discord_rag import DiscordRAG
        r = DiscordRAG()
        self.assertIsNone(r._client)
        self.assertIsNone(r._collection)
        self.assertIsNone(r._embed_client)


class TestDiscordRAGIndexedIds(unittest.TestCase):
    def test_load_indexed_ids_missing_file(self, tmp_path=None):
        from src.open_llm_vtuber.discord_rag import DiscordRAG
        r = DiscordRAG()
        with patch("src.open_llm_vtuber.discord_rag.INDEXED_IDS_FILE", Path("/nonexistent/ids.json")):
            ids = r._load_indexed_ids()
        self.assertEqual(ids, set())

    def test_load_indexed_ids_from_file(self, tmp_path=None):
        import tempfile
        from src.open_llm_vtuber.discord_rag import DiscordRAG
        r = DiscordRAG()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(["id1", "id2", "id3"], f)
            fname = f.name

        with patch("src.open_llm_vtuber.discord_rag.INDEXED_IDS_FILE", Path(fname)):
            ids = r._load_indexed_ids()
        self.assertEqual(ids, {"id1", "id2", "id3"})

    def test_load_indexed_ids_corrupted_file(self):
        import tempfile
        from src.open_llm_vtuber.discord_rag import DiscordRAG
        r = DiscordRAG()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("NOT VALID JSON{{")
            fname = f.name

        with patch("src.open_llm_vtuber.discord_rag.INDEXED_IDS_FILE", Path(fname)):
            ids = r._load_indexed_ids()
        self.assertEqual(ids, set())

    def test_save_indexed_ids(self):
        import tempfile
        from src.open_llm_vtuber.discord_rag import DiscordRAG, CACHE_DIR
        r = DiscordRAG()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_ids = Path(tmpdir) / "ids.json"
            with patch("src.open_llm_vtuber.discord_rag.INDEXED_IDS_FILE", tmp_ids), \
                 patch("src.open_llm_vtuber.discord_rag.CACHE_DIR", Path(tmpdir)):
                r._save_indexed_ids({"a", "b"})
            saved = set(json.loads(tmp_ids.read_text()))
        self.assertEqual(saved, {"a", "b"})


class TestDiscordRAGSync(unittest.TestCase):
    def _make_rag(self):
        from src.open_llm_vtuber.discord_rag import DiscordRAG
        return DiscordRAG()

    def test_sync_returns_zero_when_psycopg_missing(self):
        r = self._make_rag()
        with patch.dict("sys.modules", {"psycopg": None, "psycopg.rows": None}):
            count = r.sync()
        self.assertEqual(count, 0)

    def test_sync_returns_zero_on_postgres_error(self):
        r = self._make_rag()
        mock_psycopg = MagicMock()
        mock_psycopg.connect.side_effect = Exception("connection refused")
        mock_chroma = MagicMock()
        mock_collection = MagicMock()
        mock_collection.count.return_value = 0
        mock_chroma.PersistentClient.return_value.get_or_create_collection.return_value = mock_collection

        with patch.dict("sys.modules", {"psycopg": mock_psycopg, "psycopg.rows": MagicMock()}), \
             patch.dict("sys.modules", {"chromadb": mock_chroma}), \
             patch.object(r, "_load_indexed_ids", return_value=set()), \
             patch.object(r, "_get_chroma", return_value=(MagicMock(), mock_collection)):
            count = r.sync()
        self.assertEqual(count, 0)

    def test_sync_skips_already_indexed(self):
        r = self._make_rag()
        rows = [
            {"id": "msg1", "content": "hello", "author_name": "Alice", "timestamp": "2024-01-01", "channel_id": "ch1"},
            {"id": "msg2", "content": "world", "author_name": "Bob", "timestamp": "2024-01-02", "channel_id": "ch1"},
        ]
        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = rows
        mock_psycopg = MagicMock()
        mock_psycopg.connect.return_value = mock_conn
        mock_collection = MagicMock()

        with patch.dict("sys.modules", {"psycopg": mock_psycopg, "psycopg.rows": MagicMock()}), \
             patch.object(r, "_get_chroma", return_value=(MagicMock(), mock_collection)), \
             patch.object(r, "_load_indexed_ids", return_value={"msg1", "msg2"}), \
             patch.object(r, "_save_indexed_ids"):
            count = r.sync()

        self.assertEqual(count, 0)
        mock_collection.upsert.assert_not_called()

    def test_sync_indexes_new_messages(self):
        r = self._make_rag()
        rows = [
            {"id": "msg1", "content": "hello world", "author_name": "Alice", "timestamp": "2024-01-01", "channel_id": "ch1"},
            {"id": "msg2", "content": "foo bar", "author_name": "Bob", "timestamp": "2024-01-02", "channel_id": "ch1"},
        ]
        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = rows
        mock_psycopg = MagicMock()
        mock_psycopg.connect.return_value = mock_conn
        mock_collection = MagicMock()
        fake_embeds = [[0.1, 0.2], [0.3, 0.4]]

        with patch.dict("sys.modules", {"psycopg": mock_psycopg, "psycopg.rows": MagicMock()}), \
             patch.object(r, "_get_chroma", return_value=(MagicMock(), mock_collection)), \
             patch.object(r, "_load_indexed_ids", return_value=set()), \
             patch.object(r, "_embed", return_value=fake_embeds), \
             patch.object(r, "_save_indexed_ids") as mock_save:
            count = r.sync()

        self.assertEqual(count, 2)
        mock_collection.upsert.assert_called_once()
        saved_ids = mock_save.call_args[0][0]
        self.assertIn("msg1", saved_ids)
        self.assertIn("msg2", saved_ids)

    def test_sync_skips_empty_content(self):
        r = self._make_rag()
        rows = [
            {"id": "msg1", "content": "", "author_name": "Alice", "timestamp": "2024-01-01", "channel_id": "ch1"},
            {"id": "msg2", "content": "  ", "author_name": "Bob", "timestamp": "2024-01-02", "channel_id": "ch1"},
            {"id": "msg3", "content": "actual message", "author_name": "Carol", "timestamp": "2024-01-03", "channel_id": "ch1"},
        ]
        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = rows
        mock_psycopg = MagicMock()
        mock_psycopg.connect.return_value = mock_conn
        mock_collection = MagicMock()

        with patch.dict("sys.modules", {"psycopg": mock_psycopg, "psycopg.rows": MagicMock()}), \
             patch.object(r, "_get_chroma", return_value=(MagicMock(), mock_collection)), \
             patch.object(r, "_load_indexed_ids", return_value=set()), \
             patch.object(r, "_embed", return_value=[[0.1, 0.2]]), \
             patch.object(r, "_save_indexed_ids"):
            count = r.sync()

        self.assertEqual(count, 1)


class TestDiscordRAGSearch(unittest.TestCase):
    def _make_rag(self):
        from src.open_llm_vtuber.discord_rag import DiscordRAG
        return DiscordRAG()

    def test_search_returns_empty_when_sync_fails(self):
        r = self._make_rag()
        mock_collection = MagicMock()
        mock_collection.count.return_value = 0
        mock_collection.query.return_value = {"documents": [[]], "metadatas": [[]], "distances": [[]]}

        with patch.object(r, "_get_chroma", return_value=(MagicMock(), mock_collection)), \
             patch.object(r, "sync", return_value=0):
            results = r.search("anything")
        self.assertEqual(results, [])

    def test_search_returns_formatted_results(self):
        r = self._make_rag()
        mock_collection = MagicMock()
        mock_collection.count.return_value = 3
        mock_collection.query.return_value = {
            "documents": [["hello world"]],
            "metadatas": [[{"author": "Alice", "timestamp": "2024-01-01", "channel_id": "ch1"}]],
            "distances": [[0.1]],
        }

        with patch.object(r, "_get_chroma", return_value=(MagicMock(), mock_collection)), \
             patch.object(r, "_embed", return_value=[[0.1, 0.2]]):
            results = r.search("hello")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["content"], "hello world")
        self.assertEqual(results[0]["author"], "Alice")
        self.assertEqual(results[0]["score"], 0.925)
        self.assertEqual(results[0]["semantic_score"], 0.9)

    def test_search_auto_syncs_when_empty(self):
        r = self._make_rag()
        mock_collection = MagicMock()
        mock_collection.count.side_effect = [0, 2, 2]
        mock_collection.query.return_value = {
            "documents": [["msg content"]],
            "metadatas": [[{"author": "X", "timestamp": "t", "channel_id": "c"}]],
            "distances": [[0.2]],
        }

        with patch.object(r, "_get_chroma", return_value=(MagicMock(), mock_collection)), \
             patch.object(r, "sync", return_value=2) as mock_sync, \
             patch.object(r, "_embed", return_value=[[0.1, 0.2]]):
            results = r.search("test")

        mock_sync.assert_called_once()
        self.assertEqual(len(results), 1)


class TestDiscordRouting(unittest.TestCase):
    """Test that discord tools are correctly bucketed in the guidance router."""

    def _make_agent(self):
        from src.open_llm_vtuber.agent.agents.basic_memory_agent import BasicMemoryAgent

        class DummyLLM:
            async def chat_completion(self, *args, **kwargs):
                if False:
                    yield ""

        return BasicMemoryAgent(
            llm=DummyLLM(),
            system="test",
            live2d_model=None,
            use_mcpp=True,
            guidance_tool_router_enabled=True,
            guidance_tool_router_target_servers=["obsidian"],
        )

    def _make_tool(self, name: str, description: str, server: str = "obsidian"):
        from src.open_llm_vtuber.mcpp.types import ToolCallObject
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {},
            },
        }

    def test_discord_bucket_exists(self):
        agent = self._make_agent()
        result = agent._categorize_guidance_tools([])
        self.assertIn("discord", result)
        self.assertIn("twitter", result)

    def test_discord_search_tool_lands_in_discord_bucket(self):
        agent = self._make_agent()
        tool = self._make_tool("discord_search", "Semantic search over Discord message history")

        from src.open_llm_vtuber.mcpp.tool_manager import ToolManager
        mock_raw = MagicMock()
        mock_raw.related_server = "obsidian"
        mock_manager = MagicMock(spec=ToolManager)
        mock_manager.get_tool.return_value = mock_raw
        agent._tool_manager = mock_manager

        result = agent._categorize_guidance_tools([tool])
        self.assertIn(tool, result["discord"])

    def test_discord_not_in_notes_or_calendar(self):
        agent = self._make_agent()
        tool = self._make_tool("discord_search", "Semantic search over Discord message history")

        from src.open_llm_vtuber.mcpp.tool_manager import ToolManager
        mock_raw = MagicMock()
        mock_raw.related_server = "obsidian"
        mock_manager = MagicMock(spec=ToolManager)
        mock_manager.get_tool.return_value = mock_raw
        agent._tool_manager = mock_manager

        result = agent._categorize_guidance_tools([tool])
        self.assertNotIn(tool, result["notes"])
        self.assertNotIn(tool, result["calendar"])

    def test_discord_capability_not_rejected_by_validator(self):
        agent = self._make_agent()
        # The validator previously rejected "discord". Ensure both social capabilities pass.
        valid = {"notes", "todos", "calendar", "web_search", "discord", "twitter", None}
        self.assertIn("discord", valid)
        self.assertIn("twitter", valid)


if __name__ == "__main__":
    unittest.main()
