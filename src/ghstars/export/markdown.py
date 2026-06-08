"""Markdown export - per-user Obsidian-compatible .md files + unified index."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from slugify import slugify

from ghstars.models import EnrichedRepo


def export_markdown(repos: list[EnrichedRepo], output_dir: Path, single_file: bool = False) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    created = []

    users = _group_by_user(repos)
    for username, user_repos in users.items():
        user_dir = output_dir / username / "markdown"
        user_dir.mkdir(parents=True, exist_ok=True)

        if single_file:
            content = _build_unified_md(username, user_repos)
            path = user_dir / f"{username}_stars.md"
            path.write_text(content)
            created.append(path)
        else:
            for repo in user_repos:
                content = _build_repo_md(repo)
                filename = f"{slugify(repo.full_name)}.md"
                path = user_dir / filename
                path.write_text(content)
                created.append(path)

            unified = _build_unified_md(username, user_repos)
            unified_path = user_dir / f"{username}_all_stars.md"
            unified_path.write_text(unified)
            created.append(unified_path)

    return created


def _group_by_user(repos: list[EnrichedRepo]) -> dict[str, list[EnrichedRepo]]:
    groups: dict[str, list[EnrichedRepo]] = {}
    for r in repos:
        key = r.scraped_by or "unknown"
        groups.setdefault(key, []).append(r)
    return groups


def _build_unified_md(username: str, repos: list[EnrichedRepo]) -> str:
    """Single unified markdown file with all repos and GitHub links."""
    lines = [
        f"# GitHub Stars — {username}",
        f"*{len(repos)} starred repositories*",
        f"*Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*",
        "",
        "## All Repositories",
        "",
    ]
    for repo in sorted(repos, key=lambda r: r.stars, reverse=True):
        desc = repo.description or repo.ai_enriched_desc or ""
        desc_short = desc[:120] + ("..." if len(desc) > 120 else "")
        cat = f" `{repo.category}`" if repo.category and repo.category != "Uncategorized" else ""
        lang = f" ({repo.language})" if repo.language else ""
        lines.extend([
            f"- **[{repo.full_name}]({repo.url})** ⭐{repo.stars}{lang}{cat}",
            f"  {desc_short}",
            "",
        ])
    return "\n".join(lines)


def _build_frontmatter(repo: EnrichedRepo) -> str:
    fm = {
        "github": repo.full_name,
        "url": repo.url,
        "category": repo.category,
        "subcategory": repo.subcategory or "",
        "language": repo.language or "",
        "stars": repo.stars,
        "forks": repo.forks,
        "utility_score": repo.utility_score,
        "community_health": repo.community_health,
        "maturity_level": repo.maturity_level.value,
        "stars_rate": repo.stars_rate,
        "license": repo.license or "",
        "topics": repo.topics,
        "best_for": repo.best_for,
        "tags": repo.tags,
        "primary_use_case": repo.primary_use_case or "",
        "scraped_by": repo.scraped_by,
        "enriched": repo.enrichment_timestamp.isoformat() if repo.enrichment_timestamp else "",
    }
    lines = ["---"]
    for key, value in fm.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - \"{item}\"")
        elif isinstance(value, str) and any(c in value for c in '":{}[]&*#?|<>`'):
            lines.append(f'{key}: "{value}"')
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def _build_repo_md(repo: EnrichedRepo) -> str:
    parts = [_build_frontmatter(repo)]
    parts.append(f"\n# {repo.full_name}\n")
    parts.append(f"**GitHub:** [{repo.url}]({repo.url})")
    parts.append(f"**Stars:** {repo.stars} | **Forks:** {repo.forks} | **Language:** {repo.language or 'N/A'}")
    parts.append(f"**License:** {repo.license or 'Not specified'}\n")
    if repo.description:
        parts.append(f"## Description\n\n{repo.description}\n")
    if repo.ai_enriched_desc:
        parts.append(f"## AI Summary\n\n{repo.ai_enriched_desc}\n")
    parts.append("## Metadata\n")
    parts.append(f"- **Category:** {repo.category}")
    if repo.subcategory:
        parts.append(f"- **Subcategory:** {repo.subcategory}")
    parts.append(f"- **Utility Score:** {repo.utility_score}/10")
    parts.append(f"- **Community Health:** {repo.community_health}/10")
    parts.append(f"- **Maturity:** {repo.maturity_level.value}")
    parts.append(f"- **Stars Growth:** {repo.stars_rate}")
    if repo.primary_use_case:
        parts.append(f"\n### Primary Use Case\n\n{repo.primary_use_case}\n")
    if repo.secondary_use_cases:
        parts.append("### Secondary Use Cases\n")
        for uc in repo.secondary_use_cases:
            parts.append(f"- {uc}")
        parts.append("")
    if repo.best_for:
        parts.append("### Best For\n")
        for bf in repo.best_for:
            parts.append(f"- {bf}")
        parts.append("")
    if repo.tags:
        parts.append("### Tags\n")
        parts.append(" ".join(f"`{t}`" for t in repo.tags))
        parts.append("")
    if repo.related_repos:
        parts.append("### Related Repositories\n")
        for rr in repo.related_repos:
            parts.append(f"- [{rr}](https://github.com/{rr})")
        parts.append("")
    if repo.topics:
        parts.append("### GitHub Topics\n")
        parts.append(" ".join(f"`{t}`" for t in repo.topics))
        parts.append("")
    return "\n".join(parts)
