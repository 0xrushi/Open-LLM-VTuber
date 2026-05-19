"""ObsidianRAG — index and semantically search an Obsidian vault using ChromaDB."""

import hashlib
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from loguru import logger
from ..rag_base import HybridRAGBase

CACHE_DIR = Path.home() / ".cache" / "obsidian_mcp_rag"
MANIFEST_FILE = CACHE_DIR / "manifest.json"
COLLECTION_NAME = "obsidian_vault"
CHUNK_SIZE = 800  # characters per chunk
CHUNK_OVERLAP = 100


def _chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start += size - overlap
    return chunks


def _file_hash(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


class ObsidianRAG(HybridRAGBase):
    """Semantic search over an Obsidian vault using ChromaDB + nomic embeddings."""

    def __init__(
        self,
        vault_path: str,
        embed_base_url: str = "https://llm.emberfang.xyz/v1",
        embed_model: str = "nomic-embed-text-v1.5",
        embed_api_key: str = "not-needed",
    ):
        self.vault_path = Path(vault_path)
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

    def _load_manifest(self) -> Dict[str, str]:
        if MANIFEST_FILE.exists():
            try:
                return json.loads(MANIFEST_FILE.read_text())
            except Exception:
                pass
        return {}

    def _save_manifest(self, manifest: Dict[str, str]):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        MANIFEST_FILE.write_text(json.dumps(manifest))

    def _vault_files(self) -> List[Path]:
        return sorted(self.vault_path.rglob("*.md"))

    def needs_reindex(self) -> bool:
        manifest = self._load_manifest()
        for f in self._vault_files():
            rel = str(f.relative_to(self.vault_path))
            if manifest.get(rel) != _file_hash(f):
                return True
        # check for deleted files
        current = {str(f.relative_to(self.vault_path)) for f in self._vault_files()}
        if set(manifest.keys()) - current:
            return True
        return False

    def index_vault(self, force: bool = False):
        """Index all markdown files in the vault. Skips unchanged files unless force=True."""
        _, collection = self._get_chroma()
        manifest = self._load_manifest()
        files = self._vault_files()

        if not files:
            logger.warning(f"No .md files found in vault: {self.vault_path}")
            return

        updated_manifest = {}
        batch_ids: List[str] = []
        batch_docs: List[str] = []
        batch_metas: List[Dict[str, Any]] = []
        BATCH = 32

        for f in files:
            rel = str(f.relative_to(self.vault_path))
            fhash = _file_hash(f)
            updated_manifest[rel] = fhash

            if not force and manifest.get(rel) == fhash:
                continue

            try:
                text = f.read_text(encoding="utf-8", errors="ignore").strip()
            except Exception as e:
                logger.warning(f"Could not read {f}: {e}")
                continue

            if not text:
                continue

            # Remove old chunks for this file
            try:
                collection.delete(where={"source": rel})
            except Exception:
                pass

            chunks = _chunk_text(text)
            for i, chunk in enumerate(chunks):
                chunk_id = f"{rel}::chunk{i}"
                batch_ids.append(chunk_id)
                batch_docs.append(chunk)
                batch_metas.append({"source": rel, "chunk": i, "total_chunks": len(chunks)})

                if len(batch_ids) >= BATCH:
                    embeds = self._embed(batch_docs)
                    collection.upsert(
                        ids=batch_ids,
                        documents=batch_docs,
                        embeddings=embeds,
                        metadatas=batch_metas,
                    )
                    batch_ids, batch_docs, batch_metas = [], [], []

        if batch_ids:
            embeds = self._embed(batch_docs)
            collection.upsert(
                ids=batch_ids,
                documents=batch_docs,
                embeddings=embeds,
                metadatas=batch_metas,
            )

        self._save_manifest(updated_manifest)
        logger.info(f"Vault indexed: {len(files)} files")

    def search(
        self,
        query: str,
        n_results: int = 8,
        note_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Semantic search over indexed vault. Returns list of {file, excerpt, score}."""
        _, collection = self._get_chroma()

        if collection.count() == 0:
            logger.info("RAG index empty, building now...")
            self.index_vault()

        where = None
        if note_type and note_type != "any":
            type_folder_map = {
                "notes": "Notes",
                "todos": "Tasks",
                "calendar": "Calendar",
            }
            folder = type_folder_map.get(note_type.lower())
            if folder:
                where = {"source": {"$contains": folder}}
        output = []
        ranked = self._hybrid_query(
            collection=collection,
            query=query,
            n_results=n_results,
            where=where,
        )
        for doc, meta, semantic, hybrid in ranked:
            output.append({
                "file": meta.get("source", ""),
                "excerpt": doc,
                "score": round(hybrid, 4),
                "semantic_score": round(semantic, 4),
            })

        return output
