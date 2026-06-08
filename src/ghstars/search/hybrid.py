"""Hybrid search orchestrator - keyword + vector search with result fusion."""

from __future__ import annotations

from typing import Optional

from ghstars.config import settings
from ghstars.models import EnrichedRepo, SearchResult
from ghstars.search.db import RepoDatabase
from ghstars.search.embedder import Embedder


class HybridSearchEngine:
    """Combines FTS5 keyword search with vector similarity for hybrid retrieval."""

    def __init__(self, db: RepoDatabase, embedder: Optional[Embedder] = None):
        self.db = db
        if embedder is None:
            self.embedder = Embedder(hf_token=settings.hf_token)
        else:
            self.embedder = embedder

    def search(
        self, query: str, limit: int = 20, keyword_weight: float = 0.3,
        category: Optional[str] = None, min_score: int = 0,
        language: Optional[str] = None,
        scraped_by: Optional[str] = None,
    ) -> list[SearchResult]:
        """Execute hybrid search: keyword + vector with reciprocal rank fusion.

        Args:
            query: Natural language search query.
            limit: Maximum number of results.
            keyword_weight: Weight of keyword results (0.0-1.0).
            category: Optional filter by category.
            min_score: Minimum utility_score filter.
            language: Optional filter by programming language.
            scraped_by: Optional filter by the user who starred the repo.

        Returns:
            List of SearchResult with scores and match info.
        """
        query_embedding = self.embedder.embed_text(query)

        results = self.db.hybrid_search(
            query=query,
            query_embedding=query_embedding,
            limit=limit,
            keyword_weight=keyword_weight,
            category=category,
            min_score=min_score,
            language=language,
            scraped_by=scraped_by,
        )

        search_results = []
        for repo, score in results:
            match_type = self._determine_match_type(repo, query)
            highlights = self._find_highlights(repo, query)
            search_results.append(SearchResult(
                repo=repo,
                score=round(score, 4),
                match_type=match_type,
                highlights=highlights,
            ))

        return search_results

    def quick_keyword(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Fast keyword-only search (no embeddings)."""
        results = self.db.keyword_search(query, limit=limit)
        return [
            SearchResult(repo=repo, score=round(score, 4), match_type="keyword", highlights=[])
            for repo, score in results
        ]

    def search_similar(
        self, full_name: str, limit: int = 10,
    ) -> list[SearchResult]:
        """Find repos similar to a given repo via vector search."""
        repo = self.db.get_repo(full_name)
        if not repo:
            return []

        query_embedding = self.embedder.embed_text(repo.combined_search_text)
        results = self.db.vector_search(query_embedding, limit=limit + 1)

        search_results = []
        for r, score in results:
            if r.full_name == full_name:
                continue
            search_results.append(SearchResult(
                repo=r, score=round(score, 4), match_type="vector", highlights=[],
            ))

        return search_results[:limit]

    def build_index(self, repos: list[EnrichedRepo], progress_callback=None) -> None:
        """Index all repos in the database: store records + generate embeddings."""
        texts = [r.combined_search_text for r in repos]

        from rich.progress import Progress
        with Progress() as progress:
            task = progress.add_task("Building embeddings...", total=len(texts))
            embeddings = self.embedder.embed_texts(texts)
            progress.update(task, completed=len(texts))

        for repo, embedding in zip(repos, embeddings):
            repo.embedding = embedding
            self.db.upsert(repo)
            self.db.upsert_embedding(repo.full_name, embedding)
            if progress_callback:
                progress_callback()

    @staticmethod
    def _determine_match_type(repo: EnrichedRepo, query: str) -> str:
        """Determine what type of match this is."""
        query_lower = query.lower()
        if query_lower in repo.full_name.lower():
            return "exact_name"
        if query_lower in repo.tags or query_lower in repo.topics:
            return "tag_match"
        if query_lower in (repo.description or "").lower():
            return "description"
        if repo.category and query_lower in repo.category.lower():
            return "category"
        return "semantic"

    @staticmethod
    def _find_highlights(repo: EnrichedRepo, query: str) -> list[str]:
        """Extract text fragments matching query terms."""
        highlights = []
        terms = query.lower().split()
        search_text = repo.combined_search_text.lower()

        for term in terms:
            idx = search_text.find(term)
            if idx >= 0:
                start = max(0, idx - 20)
                end = min(len(search_text), idx + len(term) + 40)
                fragment = search_text[start:end].strip()
                highlights.append(f"...{fragment}...")

        return highlights[:3]
