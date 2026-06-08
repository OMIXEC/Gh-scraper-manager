"""Tests for Pydantic data models."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ghstars.models import (
    EnrichedRepo,
    EnrichmentResult,
    ForkResult,
    MaturityLevel,
    MirrorResult,
    SearchResult,
    StarredRepo,
)


class TestMaturityLevel:
    def test_enum_values(self):
        assert MaturityLevel.PRODUCTION == "production-ready"
        assert MaturityLevel.STABLE == "stable"
        assert MaturityLevel.BETA == "beta"
        assert MaturityLevel.EXPERIMENTAL == "experimental"
        assert MaturityLevel.MAINTENANCE == "maintenance-only"
        assert MaturityLevel.ABANDONED == "abandoned"
        assert MaturityLevel.UNKNOWN == "unknown"

    def test_enum_from_string(self):
        assert MaturityLevel("production-ready") == MaturityLevel.PRODUCTION
        assert MaturityLevel("stable") == MaturityLevel.STABLE


class TestStarredRepo:
    def test_minimal_creation(self):
        r = StarredRepo(
            full_name="a/b",
            owner="a",
            repo="b",
            url="https://github.com/a/b",
        )
        assert r.full_name == "a/b"
        assert r.stars == 0
        assert r.topics == []
        assert r.scraped_by == ""
        assert r.description is None

    def test_full_creation(self, sample_starred_repo):
        r = sample_starred_repo
        assert r.full_name == "test-org/test-repo"
        assert r.stars == 1000
        assert r.topics == ["testing", "python", "cli"]
        assert r.language == "Python"
        assert r.license == "MIT License"
        assert r.scraped_by == "testuser"

    def test_combined_search_text_basic(self, sample_starred_repo):
        text = sample_starred_repo.combined_search_text
        assert "test-org/test-repo" in text
        assert "A test repository" in text
        assert "Python" in text
        assert "testing" in text

    def test_combined_search_text_with_readme(self):
        r = StarredRepo(
            full_name="x/y",
            owner="x",
            repo="y",
            url="https://github.com/x/y",
            description="desc",
            readme_text="# README",
            readme_summary="summary",
        )
        text = r.combined_search_text
        assert "desc" in text

    def test_serialization(self, sample_starred_repo):
        data = sample_starred_repo.model_dump()
        assert data["full_name"] == "test-org/test-repo"


class TestEnrichedRepo:
    def test_inherits_starred_repo(self, sample_enriched_repo):
        r = sample_enriched_repo
        assert r.full_name == "awesome-org/cool-project"
        assert r.stars == 5000
        assert r.category == "Frontend"
        assert r.utility_score == 9
        assert r.maturity_level == MaturityLevel.PRODUCTION

    def test_combined_search_text_enriched(self, sample_enriched_repo):
        text = sample_enriched_repo.combined_search_text
        assert "Frontend" in text
        assert "React UI Framework" in text
        assert "react" in text
        assert "Building modern web" in text

    def test_utility_score_bounds(self):
        r = EnrichedRepo(full_name="a/b", owner="a", repo="b", url="https://github.com/a/b", utility_score=5)
        assert r.utility_score == 5

        with pytest.raises(ValidationError):
            EnrichedRepo(full_name="a/b", owner="a", repo="b", url="https://github.com/a/b", utility_score=11)

    def test_default_values(self):
        r = EnrichedRepo(full_name="a/b", owner="a", repo="b", url="https://github.com/a/b")
        assert r.category == "Uncategorized"
        assert r.utility_score == 0
        assert r.community_health == 0
        assert r.maturity_level == MaturityLevel.UNKNOWN
        assert r.stars_rate == ""
        assert r.tags == []
        assert r.best_for == []

    def test_embedding_excluded_from_dump(self):
        r = EnrichedRepo(full_name="a/b", owner="a", repo="b", url="https://github.com/a/b", embedding=[0.1, 0.2, 0.3])
        data = r.model_dump()
        assert "embedding" not in data

    def test_enrichment_timestamp(self, sample_enriched_repo):
        r = sample_enriched_repo
        assert r.enrichment_timestamp is not None
        assert r.enrichment_timestamp.year == 2024


class TestResultModels:
    def test_enrichment_result(self):
        r = EnrichmentResult(success=5, failed=2, skipped=1)
        assert r.success == 5
        assert r.failed == 2
        assert r.skipped == 1
        assert r.errors == []

    def test_enrichment_result_with_errors(self):
        r = EnrichmentResult(success=0, failed=1, skipped=0, errors=["Bad JSON"])
        assert r.errors == ["Bad JSON"]

    def test_fork_result_success(self):
        r = ForkResult(repo_full_name="a/b", success=True, fork_url="https://github.com/target/b")
        assert r.success
        assert r.fork_url == "https://github.com/target/b"
        assert r.error is None

    def test_fork_result_failure(self):
        r = ForkResult(repo_full_name="a/b", success=False, error="Rate limited")
        assert not r.success
        assert r.error == "Rate limited"

    def test_mirror_result(self):
        r = MirrorResult(total=10, forked=8, failed=2, skipped=0)
        assert r.total == 10
        assert r.forked == 8
        assert r.details == []

    def test_search_result(self, sample_enriched_repo):
        r = SearchResult(repo=sample_enriched_repo, score=0.95, match_type="exact_name", highlights=["hit1"])
        assert r.score == 0.95
        assert r.match_type == "exact_name"
        assert r.highlights == ["hit1"]
        assert r.repo.full_name == "awesome-org/cool-project"
