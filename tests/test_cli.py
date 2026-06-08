"""Tests for CLI commands — invocation and argument parsing."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from ghstars.cli import app
from ghstars.models import EnrichedRepo, MaturityLevel


runner = CliRunner()


class TestCLIBase:
    """Smoke tests — verify CLI loads and basic commands exist."""

    def test_cli_no_args_shows_commands(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "scrape" in result.stdout
        assert "enrich" in result.stdout
        assert "export" in result.stdout
        assert "search" in result.stdout
        assert "chat" in result.stdout

    def test_version(self):
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "gh-stars-manager" in result.stdout

    def test_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "scrape" in result.stdout


class TestScrapeCommand:
    @patch("ghstars.cli.GitHubClient")
    @patch("ghstars.cli.RepoDatabase")
    def test_scrape_invalid_input(self, mock_db, mock_client):
        mock_instance = MagicMock()
        mock_instance.resolve_user = AsyncMock(return_value=None)
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_client.return_value.__aexit__ = AsyncMock()
        mock_client.return_value = mock_instance

        result = runner.invoke(app, ["scrape", "nonexistent_user_xyz_123"])
        # Should exit with error
        assert result.exit_code == 1

    @patch("ghstars.cli.GitHubClient")
    @patch("ghstars.cli.RepoDatabase")
    def test_scrape_resolves_user(self, mock_db, mock_client):
        mock_instance = MagicMock()
        mock_instance.resolve_user = AsyncMock(return_value="testuser")
        mock_instance.fetch_starred_repos = AsyncMock(return_value=[])

        async def async_close():
            pass
        mock_instance.close = async_close
        mock_client.return_value = mock_instance

        mock_db_instance = MagicMock()
        mock_db_instance.initialize = MagicMock()
        mock_db_instance.upsert = MagicMock()
        mock_db_instance.get_stats = MagicMock(return_value={
            "total_repos": 0, "enriched_repos": 0,
            "avg_utility_score": 0, "total_stars": 0,
        })
        mock_db.return_value = mock_db_instance

        result = runner.invoke(app, ["scrape", "testuser", "--max", "5"])
        assert result.exit_code == 0
        mock_instance.resolve_user.assert_called_once()
        mock_instance.fetch_starred_repos.assert_called_once()


class TestStatusCommand:
    @patch("ghstars.cli.RepoDatabase")
    def test_status_empty_db(self, mock_db):
        mock_db_instance = MagicMock()
        mock_db_instance.initialize = MagicMock()
        mock_db_instance.get_stats = MagicMock(return_value={
            "total_repos": 0, "enriched_repos": 0,
            "avg_utility_score": 0, "total_stars": 0,
        })
        mock_db_instance.get_users = MagicMock(return_value=[])
        mock_db_instance.get_categories = MagicMock(return_value=[])
        mock_db_instance.get_languages = MagicMock(return_value=[])
        mock_db.return_value = mock_db_instance

        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0

    @patch("ghstars.cli.RepoDatabase")
    def test_status_with_user(self, mock_db):
        mock_db_instance = MagicMock()
        mock_db_instance.initialize = MagicMock()
        mock_db_instance.get_stats = MagicMock(return_value={
            "total_repos": 10, "enriched_repos": 8,
            "avg_utility_score": 5.5, "total_stars": 5000,
        })
        mock_db_instance.get_users = MagicMock(return_value=["testuser"])
        mock_db_instance.get_categories = MagicMock(return_value=["Frontend", "Backend"])
        mock_db_instance.get_languages = MagicMock(return_value=["Python"])
        mock_db.return_value = mock_db_instance

        result = runner.invoke(app, ["status", "--user", "testuser"])
        assert result.exit_code == 0


class TestEnrichCommand:
    @patch("ghstars.cli.settings")
    @patch("ghstars.cli.RepoDatabase")
    def test_enrich_no_api_key(self, mock_db, mock_settings):
        mock_settings.llm_api_key = False
        mock_settings.llm_provider = "openai"

        result = runner.invoke(app, ["enrich"])
        # Should fail with error about missing API key
        assert result.exit_code == 1

    @patch("ghstars.cli.settings")
    @patch("ghstars.cli.RepoDatabase")
    @patch("ghstars.cli.LLMEnricher")
    def test_enrich_no_repos(self, mock_enricher, mock_db, mock_settings):
        mock_settings.llm_api_key = "sk-test"
        mock_settings.llm_provider = "openai"
        mock_settings.llm_model = "gpt-4o-mini"

        mock_db_instance = MagicMock()
        mock_db_instance.initialize = MagicMock()
        mock_db_instance.get_all_repos = MagicMock(return_value=[])
        mock_db_instance.get_users = MagicMock(return_value=[])
        mock_db.return_value = mock_db_instance

        result = runner.invoke(app, ["enrich"])
        assert result.exit_code == 0
        assert "No repos to enrich" in result.stdout


class TestExportCommand:
    @patch("ghstars.cli.RepoDatabase")
    def test_export_no_repos(self, mock_db, tmp_path):
        mock_db_instance = MagicMock()
        mock_db_instance.initialize = MagicMock()
        mock_db_instance.get_all_repos = MagicMock(return_value=[])
        mock_db.return_value = mock_db_instance

        result = runner.invoke(app, ["export", "--format", "all", "--output", str(tmp_path)])
        assert result.exit_code == 0

    @patch("ghstars.cli.RepoDatabase")
    @patch("ghstars.cli.export_markdown")
    @patch("ghstars.cli.export_jsonl")
    @patch("ghstars.cli.export_csv")
    @patch("ghstars.cli.export_github_format")
    @patch("ghstars.cli.export_restar_batch")
    def test_export_all_formats(self, mock_restar, mock_ghfmt, mock_csv,
                                 mock_jsonl, mock_md, mock_db, tmp_path):
        repo = EnrichedRepo(
            full_name="a/b", owner="a", repo="b",
            url="https://github.com/a/b",
            category="Test", scraped_by="testuser",
        )
        mock_db_instance = MagicMock()
        mock_db_instance.initialize = MagicMock()
        mock_db_instance.get_all_repos = MagicMock(return_value=[repo])
        mock_db_instance.get_users = MagicMock(return_value=["testuser"])
        mock_db.return_value = mock_db_instance

        mock_md.return_value = [tmp_path / "test.md"]
        mock_jsonl.return_value = [tmp_path / "test.jsonl"]
        mock_csv.return_value = [tmp_path / "test.csv"]
        mock_ghfmt.return_value = [tmp_path / "test.json"]
        mock_restar.return_value = [tmp_path / "test.txt"]

        result = runner.invoke(app, ["export", "--format", "all", "--output", str(tmp_path)])
        assert result.exit_code == 0


class TestSearchCommand:
    @patch("ghstars.cli.RepoDatabase")
    def test_search_empty_db(self, mock_db):
        mock_db_instance = MagicMock()
        mock_db_instance.initialize = MagicMock()
        mock_db_instance.count = MagicMock(return_value=0)
        mock_db.return_value = mock_db_instance

        result = runner.invoke(app, ["search", "test query", "--keyword-only"])
        assert result.exit_code == 0
        assert "No repos indexed" in result.stdout


class TestChatCommand:
    @patch("ghstars.cli.settings")
    @patch("ghstars.cli.RepoDatabase")
    def test_chat_no_api_key(self, mock_db, mock_settings):
        mock_settings.llm_api_key = False
        mock_settings.llm_provider = "openai"

        result = runner.invoke(app, ["chat", "test task"])
        assert result.exit_code == 1


class TestInfoCommand:
    @patch("ghstars.cli.RepoDatabase")
    def test_info_repo_not_found(self, mock_db):
        mock_db_instance = MagicMock()
        mock_db_instance.initialize = MagicMock()
        mock_db_instance.get_repo = MagicMock(return_value=None)
        mock_db.return_value = mock_db_instance

        result = runner.invoke(app, ["info", "nonexistent/repo"])
        assert result.exit_code == 0
        assert "not found" in result.stdout

    @patch("ghstars.cli.RepoDatabase")
    def test_info_repo_found(self, mock_db):
        repo = EnrichedRepo(
            full_name="test/repo", owner="test", repo="repo",
            url="https://github.com/test/repo",
            description="A test repo", language="Python", stars=100,
            category="Test", utility_score=7, maturity_level=MaturityLevel.STABLE,
            scraped_by="testuser",
        )
        mock_db_instance = MagicMock()
        mock_db_instance.initialize = MagicMock()
        mock_db_instance.get_repo = MagicMock(return_value=repo)
        mock_db.return_value = mock_db_instance

        result = runner.invoke(app, ["info", "test/repo"])
        assert result.exit_code == 0
        assert "test/repo" in result.stdout
