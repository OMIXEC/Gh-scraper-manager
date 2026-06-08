"""Tests for hybrid search engine and embedder."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from ghstars.models import EnrichedRepo, MaturityLevel, SearchResult
from ghstars.search.embedder import Embedder
from ghstars.search.hybrid import HybridSearchEngine


class TestEmbedder:
    def test_init_default_model(self):
        emb = Embedder()
        assert emb.model_name == "all-MiniLM-L6-v2"

    def test_init_custom_model(self):
        emb = Embedder(model_name="paraphrase-MiniLM-L3-v2")
        assert emb.model_name == "paraphrase-MiniLM-L3-v2"

    def test_embed_text_returns_list_of_floats(self):
        """Test with actual model (will download on first run)."""
        emb = Embedder()
        vec = emb.embed_text("hello world")
        assert isinstance(vec, list)
        assert all(isinstance(v, float) for v in vec)
        assert len(vec) == emb.dimension

    def test_embed_texts_batch(self):
        emb = Embedder()
        texts = ["hello", "world", "test"]
        vecs = emb.embed_texts(texts)
        assert len(vecs) == 3
        for vec in vecs:
            assert isinstance(vec, list)
            assert len(vec) == emb.dimension

    def test_similarity_identical(self):
        emb = Embedder()
        vec = emb.embed_text("hello world")
        sim = emb.similarity(vec, vec)
        assert pytest.approx(sim, 0.01) == 1.0

    def test_similarity_orthogonal(self):
        emb = Embedder()
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [0.0, 1.0, 0.0]
        sim = emb.similarity(vec_a, vec_b)
        assert sim == 0.0

    def test_similarity_symmetric(self):
        emb = Embedder()
        vec_a = emb.embed_text("python programming")
        vec_b = emb.embed_text("java programming")
        sim_ab = emb.similarity(vec_a, vec_b)
        sim_ba = emb.similarity(vec_b, vec_a)
        assert pytest.approx(sim_ab, 0.001) == sim_ba


class TestHybridSearchEngineInit:
    def test_default_init(self, temp_db):
        engine = HybridSearchEngine(temp_db)
        assert engine.db is temp_db
        assert isinstance(engine.embedder, Embedder)

    def test_custom_embedder(self, temp_db):
        emb = Embedder()
        engine = HybridSearchEngine(temp_db, embedder=emb)
        assert engine.embedder is emb


class TestDetermineMatchType:
    @pytest.fixture
    def engine(self, temp_db):
        return HybridSearchEngine(temp_db)

    def test_exact_name_match(self, engine, sample_enriched_repo):
        mt = engine._determine_match_type(sample_enriched_repo, "cool-project")
        assert mt == "exact_name"

    def test_tag_match(self, engine):
        repo = EnrichedRepo(full_name="a/b", owner="a", repo="b", url="https://github.com/a/b",
                            tags=["python", "cli"], topics=["testing"])
        mt = engine._determine_match_type(repo, "python")
        assert mt == "tag_match"

    def test_description_match(self, engine):
        repo = EnrichedRepo(full_name="a/b", owner="a", repo="b", url="https://github.com/a/b",
                            description="A fast HTTP client")
        mt = engine._determine_match_type(repo, "http")
        assert mt == "description"

    def test_category_match(self, engine):
        repo = EnrichedRepo(full_name="a/b", owner="a", repo="b", url="https://github.com/a/b",
                            category="DevOps")
        mt = engine._determine_match_type(repo, "devops")
        assert mt == "category"

    def test_semantic_fallback(self, engine):
        repo = EnrichedRepo(full_name="a/b", owner="a", repo="b", url="https://github.com/a/b")
        mt = engine._determine_match_type(repo, "completely unrelated")
        assert mt == "semantic"


class TestFindHighlights:
    def test_finds_highlight(self, temp_db):
        engine = HybridSearchEngine(temp_db)
        repo = EnrichedRepo(
            full_name="a/b", owner="a", repo="b", url="https://github.com/a/b",
            description="A fast HTTP client for Python",
            ai_enriched_desc="Great for web scraping",
            topics=["http", "client"],
        )
        highlights = engine._find_highlights(repo, "http")
        assert len(highlights) > 0
        assert "http" in highlights[0].lower()

    def test_no_highlights_for_missing_term(self, temp_db):
        engine = HybridSearchEngine(temp_db)
        repo = EnrichedRepo(full_name="a/b", owner="a", repo="b", url="https://github.com/a/b")
        highlights = engine._find_highlights(repo, "xyznonexistent")
        assert len(highlights) == 0

    def test_max_three_highlights(self, temp_db):
        engine = HybridSearchEngine(temp_db)
        repo = EnrichedRepo(
            full_name="a/b", owner="a", repo="b", url="https://github.com/a/b",
            description="python python python python python",
        )
        highlights = engine._find_highlights(repo, "python")
        assert len(highlights) <= 3


class TestQuickKeyword:
    def test_quick_keyword_search(self, populated_db):
        engine = HybridSearchEngine(populated_db)
        results = engine.quick_keyword("org1", limit=5)
        assert len(results) >= 1
        assert isinstance(results[0], SearchResult)
        assert results[0].match_type == "keyword"


class TestSearch:
    def test_hybrid_search(self, populated_db):
        engine = HybridSearchEngine(populated_db)
        results = engine.search("repository for testing", limit=10)
        assert len(results) > 0
        assert isinstance(results[0], SearchResult)
        assert results[0].score > 0

    def test_search_with_category_filter(self, populated_db):
        engine = HybridSearchEngine(populated_db)
        results = engine.search("repository", category="Frontend", limit=10)
        for r in results:
            assert r.repo.category == "Frontend"

    def test_search_with_min_score(self, populated_db):
        engine = HybridSearchEngine(populated_db)
        results = engine.search("repository", min_score=5, limit=10)
        for r in results:
            assert r.repo.utility_score >= 5

    def test_search_similar(self, populated_db):
        engine = HybridSearchEngine(populated_db)
        results = engine.search_similar("org0/repo0", limit=5)
        assert isinstance(results, list)
