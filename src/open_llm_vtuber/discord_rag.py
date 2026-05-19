"""DiscordRAG — index Discord messages from Postgres into ChromaDB for semantic search."""

import json
import os
from pathlib import Path
from typing import List, Dict, Any
from loguru import logger
from .rag_base import HybridRAGBase

CACHE_DIR = Path.home() / ".cache" / "discord_rag"
INDEXED_IDS_FILE = CACHE_DIR / "indexed_ids.json"
COLLECTION_NAME = "discord_messages"

DISCORD_POSTGRES_URL = os.environ.get(
    "DISCORD_POSTGRES_URL",
    "postgres://discord:discord@localhost:5432/discord_ingestion",
)


class DiscordRAG(HybridRAGBase):
    """Semantic search over Discord messages using ChromaDB + nomic embeddings."""

    def __init__(
        self,
        postgres_url: str = DISCORD_POSTGRES_URL,
        embed_base_url: str = "https://llm.emberfang.xyz/v1",
        embed_model: str = "nomic-embed-text-v1.5",
        embed_api_key: str = "not-needed",
    ):
        self.postgres_url = postgres_url
        self.embed_base_url = embed_base_url
        self.embed_model = embed_model
        self.embed_api_key = embed_api_key
        self._client = None
        self._collection = None
        self._embed_client = None

    def _get_embed_client(self):
        if self._embed_client is None:
            from openai import OpenAI
            self._embed_client = OpenAI(
                base_url=self.embed_base_url,
                api_key=self.embed_api_key,
            )
        return self._embed_client

    def _get_chroma(self):
        if self._client is None:
            import chromadb
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(CACHE_DIR))
            self._collection = self._client.get_or_create_collection(
                COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
        assert self._collection is not None
        return self._client, self._collection

    def _embed(self, texts: List[str]) -> List[List[float]]:
        client = self._get_embed_client()
        response = client.embeddings.create(model=self.embed_model, input=texts)
        return [item.embedding for item in response.data]

    def _load_indexed_ids(self) -> set:
        if INDEXED_IDS_FILE.exists():
            try:
                return set(json.loads(INDEXED_IDS_FILE.read_text()))
            except Exception:
                pass
        return set()

    def _save_indexed_ids(self, ids: set):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        INDEXED_IDS_FILE.write_text(json.dumps(list(ids)))

    def sync(self, limit: int = 10000) -> int:
        """Fetch messages from Discord Postgres and index new ones into ChromaDB.

        Idempotent — already-indexed message IDs are skipped.
        Returns number of newly indexed messages.
        """
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError:
            logger.error("psycopg not installed. Run: uv add 'psycopg[binary]'")
            return 0

        _, collection = self._get_chroma()
        indexed_ids = self._load_indexed_ids()

        try:
            with psycopg.connect(self.postgres_url, row_factory=dict_row) as conn:
                rows = conn.execute(
                    "SELECT id, content, author_name, timestamp, channel_id, guild_name, channel_name "
                    "FROM messages WHERE content IS NOT NULL AND content != '' "
                    "ORDER BY timestamp DESC LIMIT %s",
                    (limit,),
                ).fetchall()

                # Fetch link details (url + description) keyed by message_id
                link_rows = conn.execute(
                    "SELECT message_id, url, platform, description "
                    "FROM social_links WHERE status = 'done' AND description IS NOT NULL"
                ).fetchall()
        except Exception as e:
            logger.error(f"Discord Postgres connection failed: {e}")
            return 0

        # Build a lookup: message_id → list of {url, platform, description}
        links_by_msg: Dict[str, List[Dict[str, Any]]] = {}
        for lr in link_rows:
            mid = lr.get("message_id")
            if not mid:
                continue
            links_by_msg.setdefault(mid, []).append({
                "url": lr["url"] or "",
                "platform": lr["platform"] or "",
                "description": lr["description"] or "",
            })

        new_rows = [r for r in rows if r["id"] not in indexed_ids]
        if not new_rows:
            logger.info("Discord RAG: no new messages to index")
            return 0

        BATCH = 32
        indexed_count = 0
        batch_ids: List[str] = []
        batch_docs: List[str] = []
        batch_metas: List[Dict[str, Any]] = []

        for row in new_rows:
            content = (row["content"] or "").strip()
            if not content:
                continue

            # Append any associated link details so they're searchable
            msg_links = links_by_msg.get(row["id"], [])
            link_parts = []
            for lk in msg_links:
                parts = [f"Link: {lk['url']}"]
                if lk["platform"]:
                    parts.append(f"Platform: {lk['platform']}")
                if lk["description"]:
                    parts.append(f"Summary: {lk['description']}")
                link_parts.append(" | ".join(parts))

            full_doc = content
            if link_parts:
                full_doc = content + "\n" + "\n".join(link_parts)
            if row.get("guild_name"):
                full_doc += f"\nServer: {row['guild_name']}"
            if row.get("channel_name"):
                full_doc += f"\nChannel: {row['channel_name']}"
            if row.get("author_name"):
                full_doc += f"\nPerson: {row['author_name']}"

            urls = " ".join(lk["url"] for lk in msg_links)

            batch_ids.append(row["id"])
            batch_docs.append(full_doc)
            batch_metas.append({
                "author": row["author_name"] or "",
                "person_name": row["author_name"] or "",
                "timestamp": row["timestamp"] or "",
                "channel_id": row["channel_id"] or "",
                "channel_name": row.get("channel_name") or "",
                "server_name": row.get("guild_name") or "",
                "urls": urls,
            })

            if len(batch_ids) >= BATCH:
                embeds = self._embed(batch_docs)
                collection.upsert(
                    ids=batch_ids,
                    documents=batch_docs,
                    embeddings=embeds,
                    metadatas=batch_metas,
                )
                indexed_ids.update(batch_ids)
                indexed_count += len(batch_ids)
                batch_ids, batch_docs, batch_metas = [], [], []

        if batch_ids:
            embeds = self._embed(batch_docs)
            collection.upsert(
                ids=batch_ids,
                documents=batch_docs,
                embeddings=embeds,
                metadatas=batch_metas,
            )
            indexed_ids.update(batch_ids)
            indexed_count += len(batch_ids)

        self._save_indexed_ids(indexed_ids)
        logger.info(f"Discord RAG: indexed {indexed_count} new messages")
        return indexed_count

    def search(self, query: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """Semantic search over indexed Discord messages.

        Returns list of {content, author, timestamp, channel_id, score}.
        Auto-syncs from Postgres if the index is empty.
        """
        _, collection = self._get_chroma()

        if collection.count() == 0:
            logger.info("Discord RAG index empty, syncing from Postgres...")
            self.sync()
            if collection.count() == 0:
                return []

        output = []
        ranked = self._hybrid_query(collection, query=query, n_results=n_results)
        for doc, meta, semantic, hybrid in ranked:
            output.append({
                "content": doc,
                "author": meta.get("author", ""),
                "person_name": meta.get("person_name", meta.get("author", "")),
                "timestamp": meta.get("timestamp", ""),
                "channel_id": meta.get("channel_id", ""),
                "channel_name": meta.get("channel_name", ""),
                "server_name": meta.get("server_name", ""),
                "urls": meta.get("urls", ""),
                "score": round(hybrid, 4),
                "semantic_score": round(semantic, 4),
            })

        return output
