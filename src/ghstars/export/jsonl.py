"""JSONL export - per-user, RAG-optimized line-delimited JSON."""

from __future__ import annotations

import json
from pathlib import Path

from ghstars.models import EnrichedRepo


def export_jsonl(repos: list[EnrichedRepo], output_dir: Path, include_embeddings: bool = False) -> list[Path]:
    created = []
    users = _group_by_user(repos)
    for username, user_repos in users.items():
        user_dir = output_dir / username / "jsonl"
        user_dir.mkdir(parents=True, exist_ok=True)
        path = user_dir / "stars.jsonl"
        with open(path, "w") as f:
            for repo in user_repos:
                record = {
                    "id": repo.full_name,
                    "url": repo.url,
                    "title": repo.full_name,
                    "text": repo.combined_search_text,
                    "metadata": {
                        "scraped_by": repo.scraped_by,
                        "category": repo.category,
                        "subcategory": repo.subcategory,
                        "language": repo.language,
                        "stars": repo.stars,
                        "forks": repo.forks,
                        "utility_score": repo.utility_score,
                        "community_health": repo.community_health,
                        "maturity_level": repo.maturity_level.value,
                        "stars_rate": repo.stars_rate,
                        "primary_use_case": repo.primary_use_case,
                        "best_for": repo.best_for,
                        "tags": repo.tags,
                        "topics": repo.topics,
                        "license": repo.license,
                        "ai_enriched_desc": repo.ai_enriched_desc,
                        "related_repos": repo.related_repos,
                        "enrichment_timestamp": repo.enrichment_timestamp.isoformat() if repo.enrichment_timestamp else None,
                    },
                }
                if include_embeddings and repo.embedding:
                    record["embedding"] = repo.embedding
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        created.append(path)
    return created


def _group_by_user(repos: list[EnrichedRepo]) -> dict[str, list[EnrichedRepo]]:
    groups: dict[str, list[EnrichedRepo]] = {}
    for r in repos:
        key = r.scraped_by or "unknown"
        groups.setdefault(key, []).append(r)
    return groups
