"""Tests for SQLite database operations — CRUD, search, multi-user, incremental."""

import json

import pytest

from ghstars.models import EnrichedRepo, MaturityLevel, StarredRepo
from ghstars.search.db import RepoDatabase


class TestDatabaseInit:
    def test_initialize(self, temp_db):
        tables = temp_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [r[0] for r in tables]
        assert "repos" in table_names
        assert "repos_fts" in table_names
        assert "repos_vec" in table_names or any("repos_vec" in t for t in table_names)
        assert "scrape_meta" in table_names

    def test_in_memory(self, temp_db):
        assert temp_db.conn is not None
        assert temp_db.count() == 0


class TestUpsertAndGet:
    def test_upsert_single(self, temp_db, sample_enriched_repo):
        temp_db.upsert(sample_enriched_repo)
        assert temp_db.count() == 1

    def test_get_existing(self, temp_db, sample_enriched_repo):
        temp_db.upsert(sample_enriched_repo)
        r = temp_db.get_repo("awesome-org/cool-project", "testuser")
        assert r is not None
        assert r.full_name == "awesome-org/cool-project"
        assert r.utility_score == 9

    def test_get_nonexistent(self, temp_db):
        r = temp_db.get_repo("nonexistent/repo", "testuser")
        assert r is None

    def test_upsert_update(self, temp_db, sample_enriched_repo):
        temp_db.upsert(sample_enriched_repo)
        updated = EnrichedRepo(**sample_enriched_repo.model_dump())
        updated.stars = 9999
        updated.utility_score = 10
        temp_db.upsert(updated)
        r = temp_db.get_repo("awesome-org/cool-project", "testuser")
        assert r.stars == 9999
        assert r.utility_score == 10

    def test_upsert_roundtrip_types(self, temp_db, sample_enriched_repo):
        temp_db.upsert(sample_enriched_repo)
        r = temp_db.get_repo("awesome-org/cool-project", "testuser")
        assert isinstance(r.maturity_level, MaturityLevel)
        assert r.maturity_level == MaturityLevel.PRODUCTION
        assert isinstance(r.topics, list)
        assert isinstance(r.tags, list)
        assert isinstance(r.best_for, list)
        assert isinstance(r.related_repos, list)
        assert r.utility_score == 9
        assert r.community_health == 8
        assert r.stars_rate == "fast"

    def test_upsert_empty_lists(self, temp_db):
        r = EnrichedRepo(full_name="a/b", owner="a", repo="b", url="https://github.com/a/b")
        temp_db.upsert(r)
        result = temp_db.get_repo("a/b")
        assert result.topics == []
        assert result.tags == []

    def test_upsert_datetime_serialization(self, temp_db):
        from datetime import datetime, timezone
        r = EnrichedRepo(
            full_name="a/b", owner="a", repo="b", url="https://github.com/a/b",
            created_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
            enrichment_timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        temp_db.upsert(r)
        result = temp_db.get_repo("a/b")
        assert result.created_at is not None
        assert result.created_at.year == 2023
        assert result.enrichment_timestamp is not None
        assert result.enrichment_timestamp.year == 2024


class TestMultiUser:
    def test_multi_user_storage(self, temp_db):
        for uname in ("alice", "bob"):
            r = EnrichedRepo(
                full_name=f"{uname}/repo", owner=uname, repo="repo",
                url=f"https://github.com/{uname}/repo",
                scraped_by=uname,
            )
            temp_db.upsert(r)

        assert temp_db.count() == 2
        assert temp_db.count(scraped_by="alice") == 1
        assert temp_db.count(scraped_by="bob") == 1

    def test_get_users(self, temp_db):
        for uname in ("alice", "bob", "charlie"):
            r = EnrichedRepo(
                full_name=f"{uname}/x", owner=uname, repo="x",
                url=f"https://github.com/{uname}/x",
                scraped_by=uname,
            )
            temp_db.upsert(r)
        users = temp_db.get_users()
        assert len(users) == 3
        assert "alice" in users

    def test_same_repo_different_users(self, temp_db):
        r1 = EnrichedRepo(full_name="shared/repo", owner="shared", repo="repo", url="https://github.com/shared/repo", scraped_by="user1")
        r2 = EnrichedRepo(full_name="shared/repo", owner="shared", repo="repo", url="https://github.com/shared/repo", scraped_by="user2")
        temp_db.upsert(r1)
        temp_db.upsert(r2)
        assert temp_db.count() == 2
        assert temp_db.get_repo("shared/repo", "user1") is not None
        assert temp_db.get_repo("shared/repo", "user2") is not None


class TestGetAll:
    def test_get_all_repos(self, populated_db):
        repos = populated_db.get_all_repos()
        assert len(repos) == 20

    def test_filter_by_user(self, populated_db):
        repos = populated_db.get_all_repos(scraped_by="testuser")
        assert len(repos) == 15

    def test_filter_by_user_other(self, populated_db):
        repos = populated_db.get_all_repos(scraped_by="otheruser")
        assert len(repos) == 5

    def test_enriched_only(self, populated_db):
        repos = populated_db.get_all_repos(enriched_only=True)
        assert len(repos) == 20


class TestKeywordSearch:
    def test_search_by_name(self, populated_db):
        results = populated_db.keyword_search("org0")
        assert len(results) >= 1
        assert results[0][0].full_name == "org0/repo0"

    def test_search_by_description(self, populated_db):
        results = populated_db.keyword_search("Repository")
        assert len(results) > 0

    def test_search_filter_by_category(self, populated_db):
        results = populated_db.keyword_search("Repository", category="Frontend")
        assert len(results) > 0
        for repo, _ in results:
            assert repo.category == "Frontend"

    def test_search_filter_by_language(self, populated_db):
        results = populated_db.keyword_search("Repository", language="Python")
        assert len(results) > 0
        for repo, _ in results:
            assert repo.language == "Python"

    def test_search_filter_min_score(self, populated_db):
        results = populated_db.keyword_search("Repository", min_score=5)
        for repo, _ in results:
            assert repo.utility_score >= 5

    def test_search_no_results(self, populated_db):
        results = populated_db.keyword_search("xyznonexistent123")
        assert len(results) == 0

    def test_search_limit(self, populated_db):
        results = populated_db.keyword_search("Repository", limit=3)
        assert len(results) <= 3


class TestStats:
    def test_stats(self, populated_db):
        stats = populated_db.get_stats()
        assert stats["total_repos"] == 20
        assert stats["enriched_repos"] == 20

    def test_stats_per_user(self, populated_db):
        stats = populated_db.get_stats(scraped_by="testuser")
        assert stats["total_repos"] == 15
        assert stats["enriched_repos"] == 15
        assert stats["total_stars"] > 0

    def test_categories(self, populated_db):
        cats = populated_db.get_categories()
        assert len(cats) >= 3

    def test_languages(self, populated_db):
        langs = populated_db.get_languages()
        assert len(langs) >= 3
        assert "Python" in langs


class TestIncrementalTracking:
    def test_get_last_scrape_never_scraped(self, temp_db):
        at, count = temp_db.get_last_scrape("unknown_user")
        assert at is None
        assert count == 0

    def test_set_and_get_last_scrape(self, temp_db):
        temp_db.set_last_scrape("testuser", 100)
        at, count = temp_db.get_last_scrape("testuser")
        assert at is not None
        assert count == 100

    def test_set_last_scrape_overwrites(self, temp_db):
        temp_db.set_last_scrape("testuser", 50)
        temp_db.set_last_scrape("testuser", 200)
        _, count = temp_db.get_last_scrape("testuser")
        assert count == 200
