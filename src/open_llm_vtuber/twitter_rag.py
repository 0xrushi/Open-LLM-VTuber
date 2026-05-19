"""TwitterRAG — index and search Twitter/X links from Postgres in ChromaDB."""

import json
import os
from pathlib import Path
from typing import List, Dict, Any

from loguru import logger
from .rag_base import HybridRAGBase

CACHE_DIR = Path.home() / ".cache" / "twitter_rag"
INDEXED_IDS_FILE = CACHE_DIR / "indexed_ids.json"
COLLECTION_NAME = "twitter_links"

DISCORD_POSTGRES_URL = os.environ.get(
    "DISCORD_POSTGRES_URL",
    "postgres://discord:discord@localhost:5432/discord_ingestion",
)


class TwitterRAG(HybridRAGBase):
    """Semantic search over Twitter items stored in discord_ingestion Postgres."""

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
        """Index Twitter/X summarized links from Postgres social_links table.

        Uses social_links rows where platform='twitter' (or 'x') and status='done'.
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
                    "SELECT sl.id AS social_link_id, sl.message_id, sl.url, sl.platform, sl.description, "
                    "m.content, m.author_name, m.timestamp, m.channel_id "
                    "FROM social_links sl "
                    "LEFT JOIN messages m ON m.id = sl.message_id "
                    "WHERE lower(sl.platform) IN ('twitter', 'x') "
                    "AND sl.status = 'done' "
                    "AND sl.description IS NOT NULL AND sl.description != '' "
                    "ORDER BY m.timestamp DESC NULLS LAST "
                    "LIMIT %s",
                    (limit,),
                ).fetchall()
        except Exception as e:
            logger.error(f"Twitter Postgres connection failed: {e}")
            return 0

        new_rows = [r for r in rows if str(r["social_link_id"]) not in indexed_ids]
        if not new_rows:
            logger.info("Twitter RAG: no new links to index")
            return 0

        BATCH = 32
        indexed_count = 0
        batch_ids: List[str] = []
        batch_docs: List[str] = []
        batch_metas: List[Dict[str, Any]] = []

        for row in new_rows:
            row_id = str(row["social_link_id"])
            url = (row.get("url") or "").strip()
            description = (row.get("description") or "").strip()
            if not description:
                continue

            doc_parts = [f"Description: {description}"]
            if url:
                doc_parts.append(f"URL: {url}")
            full_doc = "\n".join(doc_parts)

            batch_ids.append(row_id)
            batch_docs.append(full_doc)
            batch_metas.append(
                {
                    "url": url,
                    "platform": (row.get("platform") or "").lower(),
                    "author": row.get("author_name") or "",
                    "timestamp": row.get("timestamp") or "",
                    "channel_id": row.get("channel_id") or "",
                    "message_id": row.get("message_id") or "",
                }
            )

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
        logger.info(f"Twitter RAG: indexed {indexed_count} new links")
        return indexed_count

    def search(self, query: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """Semantic search over indexed Twitter links/posts."""
        _, collection = self._get_chroma()

        if collection.count() == 0:
            logger.info("Twitter RAG index empty, syncing from Postgres...")
            self.sync()
            if collection.count() == 0:
                return []

        ranked = self._hybrid_query(
            collection,
            query=query,
            n_results=n_results,
            meta_filter=lambda m: (m.get("platform", "") or "").lower() in ("twitter", "x"),
        )

        output = []
        for doc, meta, semantic, hybrid in ranked:
            platform = (meta.get("platform", "") or "").lower()
            output.append(
                {
                    "content": doc,
                    "url": meta.get("url", ""),
                    "platform": platform,
                    "author": meta.get("author", ""),
                    "timestamp": meta.get("timestamp", ""),
                    "channel_id": meta.get("channel_id", ""),
                    "message_id": meta.get("message_id", ""),
                    "score": round(hybrid, 4),
                    "semantic_score": round(semantic, 4),
                }
            )

        return output
