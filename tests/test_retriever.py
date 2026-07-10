"""Tests for knowledge_retriever.py."""

from knowledge_retriever import KnowledgeRetriever


def test_retrieves_relevant_chunks(sample_kb):
    retriever = KnowledgeRetriever(sample_kb, allow_full_fallback=False)
    result = retriever.retrieve("What is the pricing?", top_k=1)
    assert result.chunk_count == 1
    assert "Pricing" in result.section_titles[0]
    assert result.retrieved_chars < result.full_kb_chars


def test_no_full_kb_injection_on_low_score(sample_kb):
    retriever = KnowledgeRetriever(sample_kb, min_score=0.99, allow_full_fallback=False)
    result = retriever.retrieve("xyzzy nonsense query", top_k=2)
    assert not result.used_fallback
    assert result.chunk_count == 1  # top-1 chunk returned because score < min_score


def test_allow_full_fallback_on_low_score(sample_kb):
    # With allow_full_fallback=True and a low score, it should return all chunks
    retriever = KnowledgeRetriever(sample_kb, min_score=0.99, allow_full_fallback=True)
    result = retriever.retrieve("xyzzy nonsense query", top_k=2)
    assert result.used_fallback
    assert result.chunk_count == len(retriever.chunks)


def test_metrics_populated(sample_kb):
    retriever = KnowledgeRetriever(sample_kb)
    result = retriever.retrieve("integrations with slack", top_k=2)
    assert result.total_chunks >= 1
    assert result.best_score >= 0


def test_cache_hit_on_repeated_query(sample_kb):
    """Same query twice should produce a cache hit on the second call."""
    retriever = KnowledgeRetriever(sample_kb, cache_size=8)
    result1 = retriever.retrieve("What is the pricing?", top_k=1)
    result2 = retriever.retrieve("What is the pricing?", top_k=1)

    # Results must be identical (same cached object)
    assert result1.text == result2.text
    assert result1.section_titles == result2.section_titles

    info = retriever.cache_info()
    assert info["hits"] >= 1
    assert info["currsize"] >= 1


def test_cache_miss_on_different_queries(sample_kb):
    """Different queries should each be a cache miss."""
    retriever = KnowledgeRetriever(sample_kb, cache_size=8)
    retriever.retrieve("What is the pricing?", top_k=1)
    retriever.retrieve("Tell me about integrations", top_k=1)

    info = retriever.cache_info()
    assert info["misses"] >= 2
    assert info["currsize"] >= 2


def test_empty_knowledge_base():
    """Verify retriever handles empty knowledge base gracefully."""
    retriever = KnowledgeRetriever("")
    assert len(retriever.chunks) == 0
    result = retriever.retrieve("Any query", top_k=2)
    assert result.text == ""
    assert result.chunk_count == 0
    assert result.used_fallback is True


def test_zero_vector_magnitude_cosine():
    """Verify query with no alphanumeric characters doesn't crash and returns 0 similarity."""
    # We need n > 2 to avoid <=top_k shortcut, and we use a term that appears in all chunks
    # so that IDF of the term is 0, which makes all vector values 0.
    kb = "## Section 1\ntest\n\n## Section 2\ntest\n\n## Section 3\ntest"
    retriever = KnowledgeRetriever(kb, min_score=0.01)
    # Query for "test" (which exists, so keys = {"test"}) but has idf=0, magnitude=0
    result = retriever.retrieve("test", top_k=1)
    assert result.best_score == 0.0


def test_fewer_chunks_than_top_k():
    """Verify that if KB has <= top_k chunks, it returns all of them immediately."""
    retriever = KnowledgeRetriever("## Section 1\nbody 1\n\n## Section 2\nbody 2", min_score=0.01)
    result = retriever.retrieve("anything", top_k=3)
    assert result.chunk_count == 2
    assert "Section 1" in result.section_titles
    assert "Section 2" in result.section_titles
    assert result.best_score == 1.0
