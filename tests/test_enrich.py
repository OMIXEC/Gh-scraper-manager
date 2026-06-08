"""Tests for LLM enrichment module — provider routing, parsing, templates."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ghstars.enrich.llm import (
    LLMEnricher,
    EnrichmentError,
    _openai_client,
    _anthropic_client,
)
from ghstars.models import EnrichedRepo, MaturityLevel, StarredRepo
from ghstars.enrich.templates import (
    ENRICH_BATCH_PROMPT,
    ENRICH_REPO_PROMPT,
    SYSTEM_PROMPT,
)


class TestPromptTemplates:
    def test_system_prompt_is_non_empty(self):
        assert len(SYSTEM_PROMPT) > 50

    def test_enrich_repo_prompt_formatting(self):
        prompt = ENRICH_REPO_PROMPT.format(
            full_name="a/b",
            url="https://github.com/a/b",
            description="test",
            topics="t1, t2",
            language="Python",
            stars=100,
            forks=10,
            license="MIT",
            homepage="",
            readme_summary="readme",
        )
        assert "a/b" in prompt
        assert "t1, t2" in prompt
        assert "Python" in prompt
        assert "100" in prompt

    def test_enrich_batch_prompt_formatting(self):
        prompt = ENRICH_BATCH_PROMPT.format(
            count=2,
            repos_json=json.dumps([{"full_name": "a/b"}, {"full_name": "c/d"}]),
        )
        assert "2" in prompt
        assert "a/b" in prompt
        assert "c/d" in prompt


class TestParseEnrichment:
    def test_parse_valid_json(self, sample_starred_repo):
        enricher = LLMEnricher(provider="openai", model="gpt-4o-mini")
        raw = {
            "category": "Backend",
            "subcategory": "API Framework",
            "primary_use_case": "Building REST APIs",
            "secondary_use_cases": ["GraphQL server", "WebSocket endpoint"],
            "utility_score": 8,
            "community_health": 7,
            "stars_rate": "fast",
            "best_for": ["Backend devs", "Microservices teams"],
            "tags": ["api", "rest", "fastapi"],
            "maturity_level": "production-ready",
            "ai_enriched_desc": "A production-ready API framework.",
            "related_repos": ["tiangolo/fastapi", "encode/starlette"],
        }
        result = enricher._parse_enrichment(sample_starred_repo, raw)
        assert result.category == "Backend"
        assert result.subcategory == "API Framework"
        assert result.utility_score == 8
        assert result.maturity_level == MaturityLevel.PRODUCTION
        assert len(result.secondary_use_cases) == 2
        assert len(result.related_repos) == 2

    def test_parse_minimal_json(self, sample_starred_repo):
        enricher = LLMEnricher(provider="openai")
        raw = {}
        result = enricher._parse_enrichment(sample_starred_repo, raw)
        assert result.category == "Uncategorized"
        assert result.utility_score == 0
        assert result.community_health == 0
        assert result.maturity_level == MaturityLevel.UNKNOWN

    def test_parse_clamps_utility_score(self, sample_starred_repo):
        enricher = LLMEnricher(provider="openai")
        result = enricher._parse_enrichment(sample_starred_repo, {"utility_score": 15})
        assert result.utility_score == 10
        result = enricher._parse_enrichment(sample_starred_repo, {"utility_score": -5})
        assert result.utility_score == 0

    def test_parse_null_score(self, sample_starred_repo):
        enricher = LLMEnricher(provider="openai")
        result = enricher._parse_enrichment(sample_starred_repo, {"utility_score": None})
        assert result.utility_score == 0


class TestParseMaturity:
    def test_all_maturity_levels(self):
        mapping = {
            "production-ready": MaturityLevel.PRODUCTION,
            "stable": MaturityLevel.STABLE,
            "beta": MaturityLevel.BETA,
            "experimental": MaturityLevel.EXPERIMENTAL,
            "maintenance-only": MaturityLevel.MAINTENANCE,
            "abandoned": MaturityLevel.ABANDONED,
            "unknown": MaturityLevel.UNKNOWN,
            "SOMETHING_WEIRD": MaturityLevel.UNKNOWN,
            "": MaturityLevel.UNKNOWN,
        }
        enricher = LLMEnricher(provider="openai")
        for raw, expected in mapping.items():
            assert enricher._parse_maturity(raw) == expected


class TestExtractJSON:
    def test_plain_json(self):
        text = '{"key": "value"}'
        result = LLMEnricher._extract_json(text)
        assert json.loads(result) == {"key": "value"}

    def test_markdown_fenced_json(self):
        text = '```json\n{"key": "value"}\n```'
        result = LLMEnricher._extract_json(text)
        assert json.loads(result) == {"key": "value"}

    def test_markdown_fenced_no_lang(self):
        text = '```\n{"key": "value"}\n```'
        result = LLMEnricher._extract_json(text)
        assert json.loads(result) == {"key": "value"}

    def test_whitespace(self):
        text = '  \n  {"key": "value"}  \n  '
        result = LLMEnricher._extract_json(text)
        assert json.loads(result) == {"key": "value"}


class TestBuildRepoContext:
    def test_basic_context(self, sample_starred_repo):
        enricher = LLMEnricher(provider="openai")
        ctx = enricher._build_repo_context(sample_starred_repo)
        assert "test-org/test-repo" in ctx
        assert "testing, python, cli" in ctx
        assert "Python" in ctx
        assert "1000" in ctx
        assert "MIT License" in ctx

    def test_context_with_readme(self):
        r = StarredRepo(
            full_name="a/b", owner="a", repo="b", url="https://github.com/a/b",
            readme_text="x" * 3000, readme_summary="short summary",
        )
        enricher = LLMEnricher(provider="openai")
        ctx = enricher._build_repo_context(r)
        # Should truncate long readmes
        assert len(ctx) > 0


class TestTruncateReadme:
    def test_none_readme(self):
        enricher = LLMEnricher(provider="openai")
        result = enricher._truncate_readme(None)
        assert result == "No README available."

    def test_empty_readme(self):
        enricher = LLMEnricher(provider="openai")
        result = enricher._truncate_readme("")
        assert result == "No README available."

    def test_short_readme(self):
        enricher = LLMEnricher(provider="openai")
        result = enricher._truncate_readme("short")
        assert result == "short"

    def test_long_readme(self):
        enricher = LLMEnricher(provider="openai")
        result = enricher._truncate_readme("a" * 2000)
        assert len(result) == 1503
        assert result.endswith("...")


class TestChatKwargs:
    def test_openai_kwargs(self):
        enricher = LLMEnricher(provider="openai", model="gpt-4o-mini")
        kw = enricher._chat_kwargs(512)
        assert kw["model"] == "gpt-4o-mini"
        assert kw["temperature"] == 0.3
        assert "max_completion_tokens" in kw
        assert kw["max_completion_tokens"] == 512
        assert "max_tokens" not in kw
        assert "response_format" in kw

    def test_deepseek_kwargs(self):
        enricher = LLMEnricher(provider="deepseek", model="deepseek-v4-flash")
        kw = enricher._chat_kwargs(512)
        assert kw["model"] == "deepseek-v4-flash"
        assert "max_tokens" in kw
        assert kw["max_tokens"] == 512
        assert "max_completion_tokens" not in kw
        assert "response_format" not in kw


class TestProviderProperties:
    def test_openai_compatible(self):
        e = LLMEnricher(provider="openai")
        assert e._is_openai_compatible
        assert e._supports_json_format

    def test_deepseek_compatible(self):
        e = LLMEnricher(provider="deepseek")
        assert e._is_openai_compatible
        assert not e._supports_json_format

    def test_anthropic_not_openai_compatible(self):
        e = LLMEnricher(provider="anthropic")
        assert not e._is_openai_compatible


class TestEnrichmentError:
    def test_error_message(self):
        e = EnrichmentError("test message")
        assert str(e) == "test message"


class TestCreateFallback:
    def test_creates_minimal_enriched(self, sample_starred_repo):
        enricher = LLMEnricher(provider="openai")
        result = enricher._create_fallback(sample_starred_repo)
        assert result.category == "Uncategorized"
        assert result.utility_score == 0
        assert result.community_health == 0
        assert result.maturity_level == MaturityLevel.UNKNOWN
        assert result.stars_rate == "steady"
        assert result.enrichment_timestamp is not None
