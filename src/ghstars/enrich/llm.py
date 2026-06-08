"""LLM-powered repository enrichment - generates categories, scores, tags, etc."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from ghstars.config import settings
from ghstars.models import EnrichedRepo, EnrichmentResult, MaturityLevel, StarredRepo
from ghstars.enrich.templates import ENRICH_REPO_PROMPT, ENRICH_BATCH_PROMPT, SYSTEM_PROMPT

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"


def _openai_client():
    from openai import AsyncOpenAI
    if settings.llm_provider == "deepseek":
        return AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=DEEPSEEK_BASE_URL,
        )
    return AsyncOpenAI(api_key=settings.openai_api_key)


def _anthropic_client():
    from anthropic import AsyncAnthropic
    return AsyncAnthropic(api_key=settings.anthropic_api_key)


class LLMEnricher:
    """Enriches repositories with AI-generated metadata using OpenAI, Anthropic, or Deepseek."""

    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None):
        self.provider = provider or settings.llm_provider
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

    @property
    def _is_openai_compatible(self) -> bool:
        return self.provider in ("openai", "deepseek")

    @property
    def _supports_json_format(self) -> bool:
        return self.provider == "openai"

    def _build_repo_context(self, repo: StarredRepo) -> str:
        """Build a text context string for a single repo for the LLM prompt."""
        readme = repo.readme_summary or ""
        if repo.readme_text:
            readme = repo.readme_text[:2000]
        return ENRICH_REPO_PROMPT.format(
            full_name=repo.full_name,
            url=repo.url,
            description=repo.description or "",
            topics=", ".join(repo.topics) if repo.topics else "none",
            language=repo.language or "unknown",
            stars=repo.stars,
            forks=repo.forks,
            license=repo.license or "not specified",
            homepage=repo.homepage or "none",
            readme_summary=readme,
        )

    def _parse_enrichment(self, repo: StarredRepo, raw_json: dict) -> EnrichedRepo:
        """Parse LLM JSON response into an EnrichedRepo model."""
        enriched = EnrichedRepo(
            **repo.model_dump(),
            category=raw_json.get("category", "Uncategorized"),
            subcategory=raw_json.get("subcategory"),
            primary_use_case=raw_json.get("primary_use_case"),
            secondary_use_cases=raw_json.get("secondary_use_cases", []),
            utility_score=min(max(raw_json.get("utility_score", 0) or 0, 0), 10),
            community_health=min(max(raw_json.get("community_health", 0) or 0, 0), 10),
            stars_rate=raw_json.get("stars_rate", "steady"),
            best_for=raw_json.get("best_for", []),
            tags=raw_json.get("tags", []),
            maturity_level=self._parse_maturity(raw_json.get("maturity_level", "unknown")),
            ai_enriched_desc=raw_json.get("ai_enriched_desc"),
            related_repos=raw_json.get("related_repos", []),
            enrichment_timestamp=datetime.now(timezone.utc),
        )
        return enriched

    @staticmethod
    def _parse_maturity(value: str) -> MaturityLevel:
        mapping = {
            "production-ready": MaturityLevel.PRODUCTION,
            "stable": MaturityLevel.STABLE,
            "beta": MaturityLevel.BETA,
            "experimental": MaturityLevel.EXPERIMENTAL,
            "maintenance-only": MaturityLevel.MAINTENANCE,
            "abandoned": MaturityLevel.ABANDONED,
        }
        return mapping.get(value.lower(), MaturityLevel.UNKNOWN)

    def _truncate_readme(self, text: Optional[str], max_chars: int = 1500) -> str:
        if not text:
            return "No README available."
        return text[:max_chars] + ("..." if len(text) > max_chars else "")

    def _chat_kwargs(self, max_tokens: int = 1024) -> dict:
        """Build kwargs for an OpenAI-compatible chat completion call."""
        kwargs = {
            "model": self.model,
            "temperature": 0.3,
        }
        # Use max_completion_tokens for newer OpenAI models;
        # Deepseek uses max_tokens (OpenAI-compatible but behind on this convention).
        if self.provider == "deepseek":
            kwargs["max_tokens"] = max_tokens
        else:
            kwargs["max_completion_tokens"] = max_tokens
        # JSON response format only supported by OpenAI natively
        if self._supports_json_format:
            kwargs["response_format"] = {"type": "json_object"}
        return kwargs

    async def enrich_single(self, repo: StarredRepo) -> EnrichedRepo:
        """Enrich a single repository via LLM."""
        prompt = self._build_repo_context(repo) + "\n\nReturn ONLY the JSON object:"

        if self.provider == "anthropic":
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.content[0].text
        else:
            kwargs = self._chat_kwargs(1024)
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
            response = await self.client.chat.completions.create(messages=messages, **kwargs)
            content = response.choices[0].message.content or "{}"

        try:
            data = json.loads(self._extract_json(content))
            return self._parse_enrichment(repo, data)
        except (json.JSONDecodeError, KeyError) as e:
            raise EnrichmentError(f"Failed to parse LLM response for {repo.full_name}: {e}") from e

    async def enrich_batch(self, repos: list[StarredRepo]) -> list[EnrichedRepo]:
        """Enrich a batch of repositories. Falls back to single if batch fails."""
        if not repos:
            return []

        try:
            return await self._enrich_batch_llm(repos)
        except EnrichmentError:
            pass

        # Fallback: enrich one by one
        results = []
        for repo in repos:
            try:
                enriched = await self.enrich_single(repo)
                results.append(enriched)
            except EnrichmentError:
                enriched = self._create_fallback(repo)
                results.append(enriched)
        return results

    async def _enrich_batch_llm(self, repos: list[StarredRepo]) -> list[EnrichedRepo]:
        """Send a batch of repos to the LLM at once for efficiency."""
        entries = []
        for r in repos:
            entries.append({
                "full_name": r.full_name,
                "url": r.url,
                "description": r.description or "",
                "topics": r.topics,
                "language": r.language or "unknown",
                "stars": r.stars,
                "forks": r.forks,
                "license": r.license or "not specified",
                "readme": self._truncate_readme(r.readme_text or r.readme_summary),
            })

        prompt = ENRICH_BATCH_PROMPT.format(count=len(repos), repos_json=json.dumps(entries, indent=2))
        prompt += "\n\nReturn ONLY the JSON array:"

        if self.provider == "anthropic":
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.content[0].text
        else:
            kwargs = self._chat_kwargs(4096)
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
            response = await self.client.chat.completions.create(messages=messages, **kwargs)
            content = response.choices[0].message.content or "[]"

        data = json.loads(self._extract_json(content))
        items = data if isinstance(data, list) else data.get("repos", data.get("results", []))

        results = []
        for item in items:
            full_name = item.get("full_name", "")
            repo = next((r for r in repos if r.full_name == full_name), None)
            if repo:
                results.append(self._parse_enrichment(repo, item))

        return results

    def _create_fallback(self, repo: StarredRepo) -> EnrichedRepo:
        """Create a minimally enriched repo when LLM fails."""
        return EnrichedRepo(
            **repo.model_dump(),
            category="Uncategorized",
            utility_score=0,
            community_health=0,
            stars_rate="steady",
            maturity_level=MaturityLevel.UNKNOWN,
            enrichment_timestamp=datetime.now(timezone.utc),
        )

    @staticmethod
    def _extract_json(text: str) -> str:
        """Extract JSON from LLM response, stripping markdown fences."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines)
        return text.strip()


class EnrichmentError(Exception):
    """Error during LLM enrichment."""
