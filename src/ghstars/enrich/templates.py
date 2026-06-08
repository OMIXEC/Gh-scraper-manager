"""Prompt templates for LLM-based repository enrichment."""

SYSTEM_PROMPT = """You are a technical repository analyst. Given information about a GitHub repository, 
generate structured enrichment metadata. Be precise, specific, and avoid generic fluff.

Return ONLY valid JSON matching the schema. No markdown, no explanation."""


ENRICH_REPO_PROMPT = """Analyze this GitHub repository and generate enrichment metadata.

Repository: {full_name}
URL: {url}
Description: {description}
Topics: {topics}
Language: {language}
Stars: {stars}
Forks: {forks}
License: {license}
Homepage: {homepage}

README Summary (first ~1000 chars):
{readme_summary}

Generate a JSON object with these fields:
{{
  "category": "Primary category (e.g., DevOps, Frontend, Backend, ML/AI, Security, CLI/Tooling, Infrastructure, Data, Mobile, Documentation, Testing, or specific domain)",
  "subcategory": "More specific subcategory (e.g., Container Orchestration, React UI Library, API Framework, etc.)",
  "primary_use_case": "One sentence describing the main problem this solves",
  "secondary_use_cases": ["shorter use cases - max 5"],
  "utility_score": <0-10 integer, how generally useful is this for most developers>,
  "community_health": <0-10 integer, based on activity/recent updates/popularity>,
  "stars_rate": "slow|steady|fast|viral",
  "best_for": ["who or what type of project/team benefits most - max 5 items"],
  "tags": ["AI-generated keyword tags for discoverability - max 10 lowercase tags"],
  "maturity_level": "production-ready|stable|beta|experimental|maintenance-only|abandoned",
  "ai_enriched_desc": "One paragraph (2-4 sentences) describing what this repo is, what it does, and why it matters. Optimized for semantic search. Use concrete terms.",
  "related_repos": ["names of 2-3 similar/alternative repos (just 'owner/repo' format)"]
}}

Guidelines:
- utility_score: 8-10 means nearly every developer should know about this; 5-7 useful for specific domains; 1-4 niche
- community_health: based on recent commits, issues activity, maintainer responsiveness if evident
- stars_rate: "viral" for 10k+ stars in <1yr; "fast" for strong growth; "steady" for consistent; "slow" otherwise
- best_for: be specific (e.g., "SRE teams managing Kubernetes clusters" not just "developers")
- tags: lowercase, hyphenated if multi-word, focus on search-relevant keywords
- ai_enriched_desc: make it information-dense for vector search quality
"""


ENRICH_BATCH_PROMPT = """Analyze these {count} GitHub repositories and generate enrichment metadata for each.

{repos_json}

For each repository, generate a JSON object with these fields:
{{
  "full_name": "owner/repo",
  "category": "Primary category",
  "subcategory": "More specific subcategory",
  "primary_use_case": "One sentence describing main problem this solves",
  "secondary_use_cases": ["use case 1", "use case 2"],
  "utility_score": <0-10>,
  "community_health": <0-10>,
  "stars_rate": "slow|steady|fast|viral",
  "best_for": ["specific audience 1", "specific audience 2"],
  "tags": ["keyword1", "keyword2"],
  "maturity_level": "production-ready|stable|beta|experimental|maintenance-only|abandoned",
  "ai_enriched_desc": "Information-dense description optimized for semantic search (2-4 sentences)",
  "related_repos": ["owner/repo1", "owner/repo2"]
}}

Return a JSON array of results, one per repository. No markdown, no explanation.
"""
