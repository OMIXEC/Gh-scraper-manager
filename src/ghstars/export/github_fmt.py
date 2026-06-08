"""GitHub-compatible export - per-user re-star manifests."""

from __future__ import annotations

import json
from pathlib import Path

from ghstars.models import EnrichedRepo


def export_github_format(repos: list[EnrichedRepo], output_dir: Path) -> list[Path]:
    created = []
    users = _group_by_user(repos)
    for username, user_repos in users.items():
        user_dir = output_dir / username / "github"
        user_dir.mkdir(parents=True, exist_ok=True)
        path = user_dir / "stars_manifest.json"
        manifest = {
            "version": 1,
            "user": username,
            "total_repos": len(user_repos),
            "repos": [
                {"full_name": repo.full_name, "url": repo.url, "stars": repo.stars,
                 "language": repo.language, "category": repo.category}
                for repo in user_repos
            ],
        }
        with open(path, "w") as f:
            json.dump(manifest, f, indent=2, default=str)
        created.append(path)
    return created


def export_restar_batch(repos: list[EnrichedRepo], output_dir: Path) -> list[Path]:
    created = []
    users = _group_by_user(repos)
    for username, user_repos in users.items():
        user_dir = output_dir / username / "github"
        user_dir.mkdir(parents=True, exist_ok=True)
        path = user_dir / "restar_list.txt"
        with open(path, "w") as f:
            for repo in user_repos:
                f.write(f"{repo.full_name}\n")
        created.append(path)
    return created


def _group_by_user(repos: list[EnrichedRepo]) -> dict[str, list[EnrichedRepo]]:
    groups: dict[str, list[EnrichedRepo]] = {}
    for r in repos:
        key = r.scraped_by or "unknown"
        groups.setdefault(key, []).append(r)
    return groups
