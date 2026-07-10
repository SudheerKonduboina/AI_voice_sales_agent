"""
knowledge_retriever.py -- lightweight RAG for the knowledge base.

Splits the knowledge base markdown into sections by ``## `` headers, then
retrieves only the sections relevant to the user's latest message using
simple TF-IDF cosine similarity.
"""

from __future__ import annotations

import functools
import math
import re
from collections import Counter
from dataclasses import dataclass

from logger_setup import get_logger

logger = get_logger(__name__)


@dataclass
class RetrievalResult:
    """Result of a RAG retrieval with metrics for logging and analytics."""

    text: str
    section_titles: list[str]
    chunk_count: int
    total_chunks: int
    retrieved_chars: int
    full_kb_chars: int
    best_score: float
    used_fallback: bool


class KnowledgeRetriever:
    """Chunk-and-retrieve over a markdown knowledge base."""

    def __init__(
        self,
        raw_text: str,
        min_score: float = 0.01,
        allow_full_fallback: bool = False,
        cache_size: int = 32,
    ) -> None:
        self.full_text = raw_text
        self.min_score = min_score
        self.allow_full_fallback = allow_full_fallback
        self.chunks = self._split_into_chunks(raw_text)
        self._idf: dict[str, float] = {}
        self._chunk_vectors: list[dict[str, float]] = []
        self._build_index()

        # Instance-level LRU cache for retrieve calls
        @functools.lru_cache(maxsize=cache_size)
        def _cached_retrieve(query: str, top_k: int) -> RetrievalResult:
            return self._retrieve_uncached(query, top_k)

        self._cached_retrieve = _cached_retrieve

        logger.info(
            "KnowledgeRetriever initialised with %d chunks (fallback=%s, cache_size=%d)",
            len(self.chunks),
            allow_full_fallback,
            cache_size,
        )

    @staticmethod
    def _split_into_chunks(text: str) -> list[dict[str, str]]:
        """Split markdown by ``## `` headers into titled chunks."""
        chunks: list[dict[str, str]] = []
        parts = re.split(r"(?m)^## ", text)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            lines = part.split("\n", 1)
            title = lines[0].strip()
            body = lines[1].strip() if len(lines) > 1 else ""
            chunks.append({"title": title, "body": f"## {title}\n{body}"})
        return chunks

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    def _build_index(self) -> None:
        n = len(self.chunks)
        if n == 0:
            return

        df: Counter[str] = Counter()
        chunk_tokens: list[list[str]] = []
        for chunk in self.chunks:
            tokens = self._tokenize(chunk["body"])
            chunk_tokens.append(tokens)
            for t in set(tokens):
                df[t] += 1

        self._idf = {t: math.log(n / freq) for t, freq in df.items()}
        self._chunk_vectors = []
        for tokens in chunk_tokens:
            tf = Counter(tokens)
            total = len(tokens) or 1
            vec = {t: (count / total) * self._idf.get(t, 0) for t, count in tf.items()}
            self._chunk_vectors.append(vec)

    @staticmethod
    def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
        keys = set(a) & set(b)
        if not keys:
            return 0.0
        dot = sum(a[k] * b[k] for k in keys)
        mag_a = math.sqrt(sum(v * v for v in a.values()))
        mag_b = math.sqrt(sum(v * v for v in b.values()))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    def retrieve(self, query: str, top_k: int = 2) -> RetrievalResult:
        """Return top-k relevant chunks with retrieval metrics (cached)."""
        info = self._cached_retrieve.cache_info()
        result = self._cached_retrieve(query, top_k)
        new_info = self._cached_retrieve.cache_info()
        if new_info.hits > info.hits:
            logger.info("RAG cache HIT for query=%s... (hits=%d)", query[:40], new_info.hits)
        else:
            logger.debug("RAG cache MISS for query=%s... (misses=%d)", query[:40], new_info.misses)
        return result

    def cache_info(self) -> dict:
        """Return cache statistics for benchmarking/logging."""
        info = self._cached_retrieve.cache_info()
        return {
            "hits": info.hits,
            "misses": info.misses,
            "maxsize": info.maxsize,
            "currsize": info.currsize,
        }

    def _retrieve_uncached(self, query: str, top_k: int = 2) -> RetrievalResult:
        """Return top-k relevant chunks with retrieval metrics (no cache)."""
        full_kb_chars = len(self.full_text)

        if not self.chunks:
            logger.warning("Empty knowledge base -- returning empty context")
            return RetrievalResult("", [], 0, 0, 0, full_kb_chars, 0.0, True)

        if len(self.chunks) <= top_k:
            titles = [c["title"] for c in self.chunks]
            text = "\n\n".join(c["body"] for c in self.chunks)
            logger.debug("KB has <=top_k chunks -- returning all %d sections", len(self.chunks))
            return RetrievalResult(
                text,
                titles,
                len(self.chunks),
                len(self.chunks),
                len(text),
                full_kb_chars,
                1.0,
                False,
            )

        query_tokens = self._tokenize(query)
        tf = Counter(query_tokens)
        total = len(query_tokens) or 1
        query_vec = {t: (count / total) * self._idf.get(t, 0) for t, count in tf.items()}

        scored = [(self._cosine(query_vec, cv), i) for i, cv in enumerate(self._chunk_vectors)]
        scored.sort(reverse=True)
        best_score = scored[0][0]

        if best_score < self.min_score:
            if self.allow_full_fallback:
                logger.info(
                    "No strong match (best=%.4f) -- full KB fallback enabled",
                    best_score,
                )
                return RetrievalResult(
                    self.full_text,
                    [c["title"] for c in self.chunks],
                    len(self.chunks),
                    len(self.chunks),
                    full_kb_chars,
                    full_kb_chars,
                    best_score,
                    True,
                )
            # Return top chunk only rather than entire KB
            logger.info(
                "Low match score (%.4f) -- returning top-1 chunk only (no full KB injection)",
                best_score,
            )
            top_k = 1

        selected = sorted({i for _, i in scored[:top_k]})
        titles = [self.chunks[i]["title"] for i in selected]
        text = "\n\n".join(self.chunks[i]["body"] for i in selected)

        logger.info(
            "RAG retrieved %d/%d chunks (score=%.4f) sections=%s query=%s...",
            len(selected),
            len(self.chunks),
            best_score,
            titles,
            query[:60],
        )
        return RetrievalResult(
            text,
            titles,
            len(selected),
            len(self.chunks),
            len(text),
            full_kb_chars,
            best_score,
            False,
        )
