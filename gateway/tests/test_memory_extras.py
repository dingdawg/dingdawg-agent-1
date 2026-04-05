"""Tests for memory extras: vector, keyword, hybrid, chunker.

Comprehensive coverage of:
- VectorMemory: add, search, count, delete, in-memory DB, cosine sim
- KeywordMemory: add, search, count, delete, FTS5, BM25 ranking
- HybridMemory: add to both, search merged, dedup, weight config
- HybridConfig: validation, weight redistribution
- TextChunker: chunk, overlap, edge cases (empty, short, long sentence)
- Chunk: offset tracking, index assignment
- Standalone functions: chunk_text, search_keywords, index_entry
"""

from __future__ import annotations

import pytest

from isg_agent.memory.vector import (
    VectorMemory,
    VectorSearchResult,
    _cosine_similarity,
    _hash_embed,
)
from isg_agent.memory.keyword import (
    KeywordMemory,
    KeywordSearchResult,
    index_entry,
    search_keywords,
)
from isg_agent.memory.hybrid import (
    HybridConfig,
    HybridMemory,
    HybridSearchResult,
    _normalise_keyword_scores,
    search_hybrid,
)
from isg_agent.memory.chunker import (
    Chunk,
    TextChunker,
    chunk_text,
    _split_sentences,
    _split_long_sentence,
)


# ===================================================================
# VectorMemory tests
# ===================================================================


class TestHashEmbed:
    """Tests for the _hash_embed helper."""

    def test_returns_correct_dimension(self) -> None:
        vec = _hash_embed("hello world", dim=128)
        assert len(vec) == 128

    def test_default_dimension(self) -> None:
        vec = _hash_embed("test")
        assert len(vec) == 256

    def test_deterministic(self) -> None:
        a = _hash_embed("same text")
        b = _hash_embed("same text")
        assert a == b

    def test_different_text_different_vectors(self) -> None:
        a = _hash_embed("hello")
        b = _hash_embed("goodbye")
        assert a != b

    def test_normalised(self) -> None:
        vec = _hash_embed("normalisation test")
        norm = sum(v * v for v in vec) ** 0.5
        assert abs(norm - 1.0) < 1e-6

    def test_empty_text(self) -> None:
        vec = _hash_embed("")
        # Empty text should still return a vector (all zeros normalised = all zeros)
        assert len(vec) == 256


class TestCosineSimilarity:
    """Tests for the _cosine_similarity helper."""

    def test_identical_vectors(self) -> None:
        a = [1.0, 0.0, 0.0]
        assert abs(_cosine_similarity(a, a) - 1.0) < 1e-6

    def test_orthogonal_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert abs(_cosine_similarity(a, b)) < 1e-6

    def test_opposite_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert abs(_cosine_similarity(a, b) + 1.0) < 1e-6

    def test_zero_vector(self) -> None:
        a = [0.0, 0.0]
        b = [1.0, 0.0]
        assert _cosine_similarity(a, b) == 0.0


class TestVectorMemory:
    """Tests for VectorMemory CRUD operations."""

    async def test_add_returns_id(self) -> None:
        vm = VectorMemory(db_path=":memory:")
        try:
            row_id = await vm.add("Hello world")
            assert row_id > 0
        finally:
            await vm.close()

    async def test_add_with_metadata(self) -> None:
        vm = VectorMemory(db_path=":memory:")
        try:
            row_id = await vm.add("tagged entry", metadata={"source": "test"})
            assert row_id > 0
        finally:
            await vm.close()

    async def test_count(self) -> None:
        vm = VectorMemory(db_path=":memory:")
        try:
            assert await vm.count() == 0
            await vm.add("first")
            await vm.add("second")
            assert await vm.count() == 2
        finally:
            await vm.close()

    async def test_delete(self) -> None:
        vm = VectorMemory(db_path=":memory:")
        try:
            row_id = await vm.add("deletable")
            assert await vm.count() == 1
            assert await vm.delete(row_id) is True
            assert await vm.count() == 0
        finally:
            await vm.close()

    async def test_delete_nonexistent(self) -> None:
        vm = VectorMemory(db_path=":memory:")
        try:
            assert await vm.delete(9999) is False
        finally:
            await vm.close()

    async def test_search_returns_results(self) -> None:
        vm = VectorMemory(db_path=":memory:")
        try:
            await vm.add("Python programming language")
            await vm.add("JavaScript web development")
            await vm.add("Python data science with pandas")
            results = await vm.search("Python programming")
            assert len(results) > 0
            assert isinstance(results[0], VectorSearchResult)
            assert results[0].similarity >= results[-1].similarity
        finally:
            await vm.close()

    async def test_search_top_k(self) -> None:
        vm = VectorMemory(db_path=":memory:")
        try:
            for i in range(10):
                await vm.add(f"Entry number {i} with some text")
            results = await vm.search("entry", top_k=3)
            assert len(results) <= 3
        finally:
            await vm.close()

    async def test_search_empty_db(self) -> None:
        vm = VectorMemory(db_path=":memory:")
        try:
            results = await vm.search("anything")
            assert results == []
        finally:
            await vm.close()

    async def test_search_similarity_range(self) -> None:
        vm = VectorMemory(db_path=":memory:")
        try:
            await vm.add("exact match text here")
            results = await vm.search("exact match text here")
            assert len(results) == 1
            # Self-similarity should be very high (hash-based, so ~1.0)
            assert results[0].similarity > 0.5
        finally:
            await vm.close()

    async def test_close_resets_state(self) -> None:
        vm = VectorMemory(db_path=":memory:")
        await vm.add("test")
        await vm.close()
        # After close, re-init should work
        assert vm._initialized is False


# ===================================================================
# KeywordMemory tests
# ===================================================================


class TestKeywordMemory:
    """Tests for KeywordMemory FTS5 CRUD operations."""

    async def test_add_returns_id(self) -> None:
        km = KeywordMemory(db_path=":memory:")
        try:
            row_id = await km.add("Hello keyword world")
            assert row_id > 0
        finally:
            await km.close()

    async def test_add_with_metadata(self) -> None:
        km = KeywordMemory(db_path=":memory:")
        try:
            row_id = await km.add("tagged", metadata={"tag": "v1"})
            assert row_id > 0
        finally:
            await km.close()

    async def test_count(self) -> None:
        km = KeywordMemory(db_path=":memory:")
        try:
            assert await km.count() == 0
            await km.add("first entry")
            await km.add("second entry")
            assert await km.count() == 2
        finally:
            await km.close()

    async def test_delete(self) -> None:
        km = KeywordMemory(db_path=":memory:")
        try:
            row_id = await km.add("deletable entry")
            assert await km.delete(row_id) is True
            assert await km.count() == 0
        finally:
            await km.close()

    async def test_delete_nonexistent(self) -> None:
        km = KeywordMemory(db_path=":memory:")
        try:
            assert await km.delete(9999) is False
        finally:
            await km.close()

    async def test_search_basic(self) -> None:
        km = KeywordMemory(db_path=":memory:")
        try:
            await km.add("Python is a programming language")
            await km.add("JavaScript runs in browsers")
            await km.add("Python data science is popular")
            results = await km.search("Python")
            assert len(results) >= 1
            assert isinstance(results[0], KeywordSearchResult)
            # All results should mention Python
            for r in results:
                assert "python" in r.content.lower()
        finally:
            await km.close()

    async def test_search_empty_query(self) -> None:
        km = KeywordMemory(db_path=":memory:")
        try:
            await km.add("some text")
            results = await km.search("")
            assert results == []
        finally:
            await km.close()

    async def test_search_no_match(self) -> None:
        km = KeywordMemory(db_path=":memory:")
        try:
            await km.add("apples and oranges")
            results = await km.search("zyxwvutsrq")
            assert results == []
        finally:
            await km.close()

    async def test_search_top_k(self) -> None:
        km = KeywordMemory(db_path=":memory:")
        try:
            for i in range(10):
                await km.add(f"Document {i} about testing and quality")
            results = await km.search("testing", top_k=3)
            assert len(results) <= 3
        finally:
            await km.close()

    async def test_search_rank_positive(self) -> None:
        """BM25 rank should be non-negative after negation."""
        km = KeywordMemory(db_path=":memory:")
        try:
            await km.add("Python programming language")
            results = await km.search("Python")
            assert len(results) == 1
            assert results[0].rank >= 0
        finally:
            await km.close()

    async def test_search_empty_db(self) -> None:
        km = KeywordMemory(db_path=":memory:")
        try:
            results = await km.search("anything")
            assert results == []
        finally:
            await km.close()

    async def test_close_resets(self) -> None:
        km = KeywordMemory(db_path=":memory:")
        await km.add("test")
        await km.close()
        assert km._initialized is False


class TestKeywordStandaloneFunctions:
    """Tests for module-level convenience functions."""

    async def test_index_entry_and_search(self) -> None:
        """Test the standalone index_entry + search_keywords pair.

        Uses a temp file to avoid shared-cache issues with :memory:.
        """
        import tempfile
        import os
        tmpf = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmpf.close()
        try:
            row_id = await index_entry(tmpf.name, "standalone test entry")
            assert row_id > 0
            results = await search_keywords(tmpf.name, "standalone")
            assert len(results) >= 1
        finally:
            os.unlink(tmpf.name)


# ===================================================================
# HybridMemory tests
# ===================================================================


class TestHybridConfig:
    """Tests for HybridConfig validation."""

    def test_defaults(self) -> None:
        cfg = HybridConfig()
        assert cfg.vector_weight == 0.6
        assert cfg.keyword_weight == 0.4

    def test_custom_weights(self) -> None:
        cfg = HybridConfig(vector_weight=0.8, keyword_weight=0.2)
        assert cfg.vector_weight == 0.8

    def test_negative_weight_raises(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            HybridConfig(vector_weight=-0.1, keyword_weight=0.5)

    def test_both_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            HybridConfig(vector_weight=0.0, keyword_weight=0.0)

    def test_frozen(self) -> None:
        cfg = HybridConfig()
        with pytest.raises(AttributeError):
            cfg.vector_weight = 0.9  # type: ignore[misc]


class TestNormaliseKeywordScores:
    """Tests for _normalise_keyword_scores helper."""

    def test_empty_list(self) -> None:
        assert _normalise_keyword_scores([]) == []

    def test_single_result(self) -> None:
        kr = KeywordSearchResult(entry_id=1, content="t", rank=5.0)
        normed = _normalise_keyword_scores([kr])
        assert len(normed) == 1
        # Single result: all scores equal → normalised to 1.0
        assert normed[0][1] == 1.0

    def test_range_normalisation(self) -> None:
        kr1 = KeywordSearchResult(entry_id=1, content="a", rank=10.0)
        kr2 = KeywordSearchResult(entry_id=2, content="b", rank=0.0)
        normed = _normalise_keyword_scores([kr1, kr2])
        scores = {n[0].entry_id: n[1] for n in normed}
        assert scores[1] == 1.0   # max
        assert scores[2] == 0.0   # min


class TestHybridSearchResult:
    """Tests for HybridSearchResult dataclass."""

    def test_fields_stored(self) -> None:
        r = HybridSearchResult(content="test", score=0.8, source="both")
        assert r.content == "test"
        assert r.score == 0.8
        assert r.source == "both"
        assert r.vector_score == 0.0
        assert r.keyword_score == 0.0

    def test_frozen(self) -> None:
        r = HybridSearchResult(content="t", score=0.5)
        with pytest.raises(AttributeError):
            r.score = 0.9  # type: ignore[misc]


class TestHybridMemory:
    """Tests for HybridMemory integration."""

    async def test_add_both_backends(self) -> None:
        vm = VectorMemory(db_path=":memory:")
        km = KeywordMemory(db_path=":memory:")
        hm = HybridMemory(vector_memory=vm, keyword_memory=km)
        try:
            ids = await hm.add("hybrid test entry")
            assert "vector" in ids
            assert "keyword" in ids
        finally:
            await hm.close()

    async def test_add_vector_only(self) -> None:
        vm = VectorMemory(db_path=":memory:")
        hm = HybridMemory(vector_memory=vm)
        try:
            ids = await hm.add("vector only")
            assert "vector" in ids
            assert "keyword" not in ids
        finally:
            await hm.close()

    async def test_search_vector_only(self) -> None:
        vm = VectorMemory(db_path=":memory:")
        hm = HybridMemory(vector_memory=vm)
        try:
            await hm.add("Python programming language")
            results = await hm.search("Python")
            assert len(results) >= 1
            assert results[0].source == "vector"
        finally:
            await hm.close()

    async def test_search_keyword_only(self) -> None:
        km = KeywordMemory(db_path=":memory:")
        hm = HybridMemory(keyword_memory=km)
        try:
            await hm.add("Python programming language")
            results = await hm.search("Python")
            assert len(results) >= 1
            assert results[0].source == "keyword"
        finally:
            await hm.close()

    async def test_search_both_merged(self) -> None:
        vm = VectorMemory(db_path=":memory:")
        km = KeywordMemory(db_path=":memory:")
        hm = HybridMemory(vector_memory=vm, keyword_memory=km)
        try:
            await hm.add("Python programming is powerful")
            results = await hm.search("Python programming")
            assert len(results) >= 1
            # The same content should appear as "both" source
            assert any(r.source == "both" for r in results)
        finally:
            await hm.close()

    async def test_search_no_backends(self) -> None:
        hm = HybridMemory()
        results = await hm.search("anything")
        assert results == []

    async def test_search_top_k(self) -> None:
        vm = VectorMemory(db_path=":memory:")
        km = KeywordMemory(db_path=":memory:")
        hm = HybridMemory(vector_memory=vm, keyword_memory=km)
        try:
            for i in range(10):
                await hm.add(f"Document {i} about hybrid searching")
            results = await hm.search("hybrid", top_k=3)
            assert len(results) <= 3
        finally:
            await hm.close()

    async def test_config_property(self) -> None:
        cfg = HybridConfig(vector_weight=0.9, keyword_weight=0.1)
        hm = HybridMemory(config=cfg)
        assert hm.config.vector_weight == 0.9


class TestSearchHybridStandalone:
    """Tests for the standalone search_hybrid function."""

    async def test_standalone_search(self) -> None:
        vm = VectorMemory(db_path=":memory:")
        km = KeywordMemory(db_path=":memory:")
        try:
            await vm.add("standalone hybrid test")
            await km.add("standalone hybrid test")
            results = await search_hybrid(vm, km, "standalone hybrid")
            assert len(results) >= 1
        finally:
            await vm.close()
            await km.close()


# ===================================================================
# TextChunker tests
# ===================================================================


class TestSplitSentences:
    """Tests for _split_sentences helper."""

    def test_empty(self) -> None:
        assert _split_sentences("") == []

    def test_single_sentence(self) -> None:
        result = _split_sentences("Hello world.")
        assert len(result) >= 1

    def test_multiple_sentences(self) -> None:
        result = _split_sentences("First sentence. Second sentence. Third sentence.")
        assert len(result) >= 2

    def test_whitespace_only(self) -> None:
        assert _split_sentences("   ") == []


class TestSplitLongSentence:
    """Tests for _split_long_sentence helper."""

    def test_short_sentence(self) -> None:
        result = _split_long_sentence("Short text", max_chars=100)
        assert result == ["Short text"]

    def test_long_sentence(self) -> None:
        long_text = " ".join(["word"] * 50)
        result = _split_long_sentence(long_text, max_chars=30)
        assert len(result) > 1
        for fragment in result:
            assert len(fragment) <= 30

    def test_single_long_word(self) -> None:
        # A single word longer than max_chars: still returned as-is
        result = _split_long_sentence("superlongword", max_chars=5)
        assert len(result) >= 1


class TestChunk:
    """Tests for Chunk frozen dataclass."""

    def test_fields_stored(self) -> None:
        c = Chunk(text="Hello", start_offset=0, end_offset=5, index=0)
        assert c.text == "Hello"
        assert c.start_offset == 0
        assert c.end_offset == 5
        assert c.index == 0

    def test_frozen(self) -> None:
        c = Chunk(text="x", start_offset=0, end_offset=1)
        with pytest.raises(AttributeError):
            c.text = "y"  # type: ignore[misc]


class TestTextChunker:
    """Tests for TextChunker.chunk() method."""

    def test_empty_text(self) -> None:
        chunker = TextChunker(chunk_size=100, overlap=10)
        assert chunker.chunk("") == []

    def test_whitespace_only(self) -> None:
        chunker = TextChunker(chunk_size=100, overlap=10)
        assert chunker.chunk("   ") == []

    def test_short_text_single_chunk(self) -> None:
        chunker = TextChunker(chunk_size=100, overlap=10)
        chunks = chunker.chunk("Short text.")
        assert len(chunks) == 1
        assert chunks[0].text == "Short text."
        assert chunks[0].index == 0

    def test_long_text_multiple_chunks(self) -> None:
        text = ". ".join([f"Sentence number {i} with some filler text" for i in range(20)])
        chunker = TextChunker(chunk_size=100, overlap=20)
        chunks = chunker.chunk(text)
        assert len(chunks) > 1

    def test_chunk_indices_sequential(self) -> None:
        text = ". ".join([f"Sentence {i} is here now" for i in range(20)])
        chunker = TextChunker(chunk_size=80, overlap=10)
        chunks = chunker.chunk(text)
        for i, c in enumerate(chunks):
            assert c.index == i

    def test_overlap_zero(self) -> None:
        text = "First sentence. Second sentence. Third sentence. Fourth sentence."
        chunker = TextChunker(chunk_size=30, overlap=0)
        chunks = chunker.chunk(text)
        assert len(chunks) >= 2

    def test_invalid_chunk_size(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            TextChunker(chunk_size=0)

    def test_negative_overlap(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            TextChunker(chunk_size=100, overlap=-1)

    def test_overlap_ge_chunk_size(self) -> None:
        with pytest.raises(ValueError, match="less than"):
            TextChunker(chunk_size=100, overlap=100)

    def test_properties(self) -> None:
        chunker = TextChunker(chunk_size=200, overlap=50)
        assert chunker.chunk_size == 200
        assert chunker.overlap == 50


class TestChunkText:
    """Tests for the standalone chunk_text function."""

    def test_empty(self) -> None:
        assert chunk_text("") == []

    def test_basic(self) -> None:
        result = chunk_text("Hello world.", chunk_size=100, overlap=10)
        assert len(result) == 1
        assert result[0].text == "Hello world."

    def test_custom_params(self) -> None:
        text = "A. B. C. D. E. F. G. H. I. J."
        result = chunk_text(text, chunk_size=10, overlap=2)
        assert len(result) >= 1

    def test_offsets_non_negative(self) -> None:
        text = ". ".join([f"Sentence {i} is important" for i in range(10)])
        chunks = chunk_text(text, chunk_size=60, overlap=10)
        for c in chunks:
            assert c.start_offset >= 0
            assert c.end_offset >= c.start_offset
