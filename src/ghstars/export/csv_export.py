"""CSV export - per-user, flat format for Notion/Sheets."""

from __future__ import annotations

import csv
from pathlib import Path

from ghstars.models import EnrichedRepo


def export_csv(repos: list[EnrichedRepo], output_dir: Path) -> list[Path]:
    created = []
    users = _group_by_user(repos)
    for username, user_repos in users.items():
        user_dir = output_dir / username / "csv"
        user_dir.mkdir(parents=True, exist_ok=True)
        path = user_dir / "stars.csv"
        fieldnames = [
            "full_name", "url", "description", "language", "stars", "forks", "license",
            "scraped_by", "category", "subcategory", "primary_use_case", "secondary_use_cases",
            "utility_score", "community_health", "stars_rate", "maturity_level",
            "best_for", "tags", "topics", "ai_enriched_desc", "related_repos",
            "homepage", "created_at", "updated_at", "enrichment_timestamp",
        ]
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for repo in user_repos:
                row = repo.model_dump()
                for field in ("secondary_use_cases", "best_for", "tags", "topics", "related_repos"):
                    val = row.get(field, [])
                    row[field] = "; ".join(val) if val else ""
                writer.writerow(row)
        created.append(path)
    return created


def _group_by_user(repos: list[EnrichedRepo]) -> dict[str, list[EnrichedRepo]]:
    groups: dict[str, list[EnrichedRepo]] = {}
    for r in repos:
        key = r.scraped_by or "unknown"
        groups.setdefault(key, []).append(r)
    return groups
