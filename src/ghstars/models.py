"""Pydantic data models for GitHub starred repositories and enriched metadata."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class MaturityLevel(str, Enum):
    PRODUCTION = "production-ready"
    STABLE = "stable"
    BETA = "beta"
    EXPERIMENTAL = "experimental"
    MAINTENANCE = "maintenance-only"
    ABANDONED = "abandoned"
    UNKNOWN = "unknown"


class StarredRepo(BaseModel):
    """Raw data scraped from GitHub API for a starred repository."""

    full_name: str = Field(description="owner/repo")
    owner: str
    repo: str
    url: str
    description: Optional[str] = None
    topics: list[str] = Field(default_factory=list)
    language: Optional[str] = None
    stars: int = 0
    forks: int = 0
    license: Optional[str] = None
    homepage: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    starred_at: Optional[datetime] = None  # when the user starred this repo
    readme_text: Optional[str] = None
    readme_summary: Optional[str] = None
    scraped_by: str = ""

    @property
    def combined_search_text(self) -> str:
        parts = [
            self.full_name,
            self.description or "",
            self.language or "",
            " ".join(self.topics),
        ]
        if hasattr(self, "category"):
            parts.extend([
                self.category,
                self.subcategory or "",
                self.primary_use_case or "",
                " ".join(self.secondary_use_cases),
                " ".join(self.best_for),
                " ".join(self.tags),
                self.ai_enriched_desc or "",
            ])
        return " ".join(p for p in parts if p)


class EnrichedRepo(StarredRepo):
    """Repository with LLM-generated metadata for enhanced discovery."""

    category: str = Field(default="Uncategorized", description="Primary category")
    subcategory: Optional[str] = None
    primary_use_case: Optional[str] = None
    secondary_use_cases: list[str] = Field(default_factory=list)
    utility_score: int = Field(default=0, ge=0, le=10)
    community_health: int = Field(default=0, ge=0, le=10)
    stars_rate: str = Field(default="", description="slow/steady/fast/viral")
    best_for: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    maturity_level: MaturityLevel = Field(default=MaturityLevel.UNKNOWN)
    ai_enriched_desc: Optional[str] = Field(default=None)
    related_repos: list[str] = Field(default_factory=list)
    enrichment_timestamp: Optional[datetime] = None

    embedding: Optional[list[float]] = Field(default=None, exclude=True)


class EnrichmentResult(BaseModel):
    success: int
    failed: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


class ForkResult(BaseModel):
    repo_full_name: str
    success: bool
    fork_url: Optional[str] = None
    error: Optional[str] = None


class MirrorResult(BaseModel):
    total: int
    forked: int
    failed: int
    skipped: int
    details: list[ForkResult] = Field(default_factory=list)


class SearchResult(BaseModel):
    repo: EnrichedRepo
    score: float
    match_type: str
    highlights: list[str] = Field(default_factory=list)
