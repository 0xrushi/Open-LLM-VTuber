"""Shared hybrid retrieval utilities for Chroma-backed RAG classes."""

import re
from typing import Any, Callable, Dict, List, Optional, Tuple
import json


class HybridRAGBase:
    """Base class providing semantic + lexical hybrid retrieval.

    Subclasses are expected to implement:
    - _embed(texts: List[str]) -> List[List[float]]
    """

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return re.findall(r"[a-z0-9_]+", (text or "").lower())

    @classmethod
    def _lexical_score(cls, query: str, doc: str, meta: Dict[str, Any]) -> float:
        query_norm = (query or "").strip().lower()
        corpus = f"{doc or ''}\n{meta or {}}".lower()
        if not query_norm or not corpus:
            return 0.0

        q_tokens = cls._tokenize(query_norm)
        if not q_tokens:
            return 0.0

        # Exact phrase helps "chonkie" style lookups.
        phrase_bonus = 0.6 if query_norm in corpus else 0.0
        token_hits = sum(1 for tok in q_tokens if tok in corpus)
        token_score = 0.4 * (token_hits / len(q_tokens))
        return min(1.0, phrase_bonus + token_score)

    def _hybrid_query(
        self,
        collection: Any,
        query: str,
        n_results: int,
        where: Optional[Dict[str, Any]] = None,
        meta_filter: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> List[Tuple[str, Dict[str, Any], float, float]]:
        """Return ranked (doc, meta, semantic_similarity, hybrid_score) tuples."""
        count = max(1, collection.count())
        fetch_k = min(max(n_results * 20, 80), count)
        query_embed = self._embed([query])[0]

        kwargs: Dict[str, Any] = {
            "query_embeddings": [query_embed],
            "n_results": fetch_k,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        results = collection.query(**kwargs)
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        dists = results.get("distances", [[]])[0]

        rescored: List[Tuple[float, str, Dict[str, Any], float]] = []
        seen_keys: set[str] = set()
        for doc, meta, dist in zip(docs, metas, dists):
            meta = meta or {}
            if meta_filter and not meta_filter(meta):
                continue
            semantic = max(0.0, 1 - float(dist))
            lexical = self._lexical_score(query, doc or "", meta)
            hybrid = (0.75 * semantic) + (0.25 * lexical)
            key = self._result_key(doc or "", meta)
            seen_keys.add(key)
            rescored.append((hybrid, doc or "", meta, semantic))

        # Lexical fallback over a bounded corpus window to rescue exact-keyword misses.
        # Useful when embeddings fail to rank niche terms (e.g. repo names).
        scan_cap = min(count, 5000)
        if scan_cap > 0:
            try:
                corpus = collection.get(limit=scan_cap, include=["documents", "metadatas"])
                c_docs = corpus.get("documents", []) or []
                c_metas = corpus.get("metadatas", []) or []
                for doc, meta in zip(c_docs, c_metas):
                    meta = meta or {}
                    if meta_filter and not meta_filter(meta):
                        continue
                    key = self._result_key(doc or "", meta)
                    if key in seen_keys:
                        continue
                    lexical = self._lexical_score(query, doc or "", meta)
                    if lexical <= 0:
                        continue
                    # No semantic score for fallback rows; allow strong lexical matches
                    # to outrank noisy semantic neighbors.
                    hybrid = 0.6 * lexical
                    rescored.append((hybrid, doc or "", meta, 0.0))
            except Exception:
                # Fall back to semantic-only candidates if full-corpus scan isn't supported.
                pass

        rescored.sort(key=lambda x: x[0], reverse=True)
        return [(doc, meta, semantic, hybrid) for hybrid, doc, meta, semantic in rescored[:n_results]]
    @staticmethod
    def _result_key(doc: str, meta: Dict[str, Any]) -> str:
        """Stable key for deduping semantic and lexical-fallback candidates."""
        try:
            meta_s = json.dumps(meta or {}, sort_keys=True, default=str)
        except Exception:
            meta_s = str(meta or {})
        return f"{doc or ''}\n{meta_s}"
