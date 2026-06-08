"""Shared test fixtures for ghstars test suite."""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ghstars.models import (
    EnrichedRepo,
    ForkResult,
    MaturityLevel,
    MirrorResult,
    SearchResult,
    StarredRepo,
)
from ghstars.search.db import RepoDatabase


@pytest.fixture
def sample_starred_repo() -> StarredRepo:
    return StarredRepo(
        full_name="test-org/test-repo",
        owner="test-org",
        repo="test-repo",
        url="https://github.com/test-org/test-repo",
        description="A test repository for unit tests",
        topics=["testing", "python", "cli"],
        language="Python",
        stars=1000,
        forks=50,
        license="MIT License",
        homepage="https://test-repo.example.com",
        created_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        starred_at=datetime(2024, 5, 31, tzinfo=timezone.utc),
        readme_text="# Test Repo\n\nThis is a test.",
        readme_summary="A test repository for unit tests",
        scraped_by="testuser",
    )


@pytest.fixture
def sample_enriched_repo() -> EnrichedRepo:
    return EnrichedRepo(
        full_name="awesome-org/cool-project",
        owner="awesome-org",
        repo="cool-project",
        url="https://github.com/awesome-org/cool-project",
        description="An awesome project",
        topics=["awesome", "cool"],
        language="TypeScript",
        stars=5000,
        forks=200,
        license="Apache License 2.0",
        category="Frontend",
        subcategory="React UI Framework",
        primary_use_case="Building modern web applications with React",
        secondary_use_cases=["Dashboard builder", "Admin panel generator"],
        utility_score=9,
        community_health=8,
        stars_rate="fast",
        best_for=["Frontend developers", "Startup teams"],
        tags=["react", "ui", "framework", "typescript", "web"],
        maturity_level=MaturityLevel.PRODUCTION,
        ai_enriched_desc="Cool Project is a production-ready React UI framework for building modern web apps.",
        related_repos=["vercel/next.js", "remix-run/remix"],
        enrichment_timestamp=datetime(2024, 6, 1, tzinfo=timezone.utc),
        scraped_by="testuser",
    )


@pytest.fixture
def multiple_enriched_repos() -> list[EnrichedRepo]:
    repos = []
    categories = ["Frontend", "Backend", "DevOps", "ML/AI", "Security"]
    languages = ["TypeScript", "Python", "Go", "Rust", "Java"]
    for i in range(20):
        repos.append(EnrichedRepo(
            full_name=f"org{i}/repo{i}",
            owner=f"org{i}",
            repo=f"repo{i}",
            url=f"https://github.com/org{i}/repo{i}",
            description=f"Repository {i} for testing",
            topics=[f"topic{i}", f"tag{i}"],
            language=languages[i % len(languages)],
            stars=i * 100,
            forks=i * 5,
            license="MIT License",
            category=categories[i % len(categories)],
            subcategory=f"Subcategory {i % 5}",
            primary_use_case=f"Use case {i}",
            secondary_use_cases=[f"Secondary {i}", f"Alt {i}"],
            utility_score=min(i % 11, 10),
            community_health=min((i + 2) % 11, 10),
            stars_rate="steady" if i % 3 == 0 else "fast" if i % 3 == 1 else "slow",
            best_for=[f"team{i}"],
            tags=[f"tag-{i}"],
            maturity_level=MaturityLevel.PRODUCTION if i % 3 == 0 else MaturityLevel.STABLE,
            ai_enriched_desc=f"AI description for repo {i}",
            related_repos=[f"related/repo{i}"],
            enrichment_timestamp=datetime(2024, 6, 1, tzinfo=timezone.utc),
            scraped_by="testuser" if i < 15 else "otheruser",
        ))
    return repos


@pytest.fixture
def temp_db() -> RepoDatabase:
    """In-memory database for isolated tests."""
    db = RepoDatabase(Path(":memory:"))
    db.initialize()
    return db


@pytest.fixture
def temp_file_db(tmp_path) -> RepoDatabase:
    """File-based database that cleans up after test."""
    db = RepoDatabase(tmp_path / "test.db")
    db.initialize()
    return db


@pytest.fixture
def populated_db(temp_file_db, multiple_enriched_repos) -> RepoDatabase:
    """Database pre-populated with 20 repos across 2 users."""
    for repo in multiple_enriched_repos:
        temp_file_db.upsert(repo)
    return temp_file_db


@pytest.fixture
def search_results(sample_enriched_repo) -> list[SearchResult]:
    return [
        SearchResult(repo=sample_enriched_repo, score=0.934, match_type="exact_name", highlights=["...awesome-org/cool-project..."]),
    ]
