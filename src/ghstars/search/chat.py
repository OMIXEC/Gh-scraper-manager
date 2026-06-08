"""RAG-powered interactive chat - query your stars with LLM recommendations."""

from __future__ import annotations

import json
from typing import Optional

from ghstars.config import settings
from ghstars.enrich.llm import _openai_client, _anthropic_client
from ghstars.models import SearchResult

CHAT_SYSTEM_PROMPT = """You are a repository recommendation expert. Given the user's task description 
and a list of their starred GitHub repositories with metadata, recommend the best 
repos for their specific need.

Analyze the repos and provide:
1. **Top Recommendations** (ranked, most useful first)
2. **Why each is recommended** (specific features/traits matching the user's task)
3. **How to use them** (brief practical guidance per repo)
4. **Alternative combinations** (repos that work well together for this task)

Prioritize repos with high utility_score, community_health, and production-ready maturity.
Consider language familiarity if the user mentions one.
Be direct and practical — every recommendation should have a concrete reason."""


CHAT_USER_TEMPLATE = """Task: {task}

Here are the user's top {k} matching starred repos, ranked by relevance:

{repos_json}

Based on this task, provide your expert recommendations. Focus on the most useful repos.
If there's a clear #1, lead with it. For each recommended repo, explain exactly why it fits 
this task and how to get started using it.

Format your response as:
## Best Pick: {{{{top_repo_name}}}}
[why this is the best choice, how to use it]

## Also Recommended
- **{{{{repo_name}}}}** (Score: {{utility}}/10, Language: {{language}})
  Why: [1-2 sentences]
  Usage: [1-2 sentences]

## Combination Strategy
[2-3 repos that work well together for this task and why]"""


class StarChat:
    """LLM-powered chat for querying the star database with recommendations."""

    def __init__(self, model: Optional[str] = None):
        self.provider = settings.llm_provider
        self.model = model or settings.llm_model
        self._client = None

    @property
    def client(self):
        if self._client is None:
            if self.provider == "anthropic":
                self._client = _anthropic_client()
            else:
                self._client = _openai_client()
        return self._client

    def _format_repos(self, results: list[SearchResult], top_k: int) -> str:
        """Format search results as structured JSON for the LLM prompt."""
        entries = []
        for i, sr in enumerate(results[:top_k]):
            r = sr.repo
            entries.append({
                "rank": i + 1,
                "repo": r.full_name,
                "url": r.url,
                "stars": r.stars,
                "language": r.language,
                "category": r.category,
                "description": r.description or "",
                "ai_summary": r.ai_enriched_desc or "",
                "primary_use_case": r.primary_use_case or "",
                "utility_score": r.utility_score,
                "community_health": r.community_health,
                "maturity": r.maturity_level.value,
                "best_for": r.best_for,
                "tags": r.tags,
                "topics": r.topics,
                "relevance_score": round(r.score, 4),
                "match_type": sr.match_type,
            })
        return json.dumps(entries, indent=2)

    async def chat(
        self, task: str, results: list[SearchResult],
        top_k: int = 15, top_p: float = 0.9,
    ) -> str:
        """Generate LLM recommendations based on search results.

        Args:
            task: The user's task description (e.g. "I need a Python CLI framework")
            results: Hybrid search results from the star database
            top_k: How many top repos to include in the LLM context
            top_p: For future use with nucleus sampling

        Returns:
            Markdown-formatted recommendation response.
        """
        # Deduplicate and rank by score
        seen = set()
        deduped = []
        for sr in results:
            if sr.repo.full_name not in seen:
                seen.add(sr.repo.full_name)
                deduped.append(sr)

        repos_json = self._format_repos(deduped, top_k)
        user_prompt = CHAT_USER_TEMPLATE.format(task=task, k=min(top_k, len(deduped)), repos_json=repos_json)

        if self.provider == "anthropic":
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=CHAT_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return response.content[0].text
        else:
            kwargs: dict = {"model": self.model, "temperature": 0.4}
            if self.provider == "deepseek":
                kwargs["max_tokens"] = 2048
            else:
                kwargs["max_completion_tokens"] = 2048

            response = await self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": CHAT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                **kwargs,
            )
            return response.choices[0].message.content or "No response generated."
