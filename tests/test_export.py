"""Tests for export modules — Markdown, JSONL, CSV, GitHub format."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from ghstars.models import EnrichedRepo
from ghstars.export.markdown import export_markdown
from ghstars.export.jsonl import export_jsonl
from ghstars.export.csv_export import export_csv
from ghstars.export.github_fmt import export_github_format, export_restar_batch


class TestMarkdownExport:
    def test_per_repo_files(self, tmp_path, multiple_enriched_repos):
        paths = export_markdown(multiple_enriched_repos, tmp_path, single_file=False)
        assert len(paths) > 0
        # Check content of first file
        content = paths[0].read_text()
        assert "---" in content
        assert "github:" in content
        assert "category:" in content

    def test_contains_user_dirs(self, tmp_path, multiple_enriched_repos):
        export_markdown(multiple_enriched_repos, tmp_path)
        user_dirs = [d for d in (tmp_path).rglob("markdown")]
        assert len(user_dirs) >= 2

    def test_unified_md_exists(self, tmp_path, multiple_enriched_repos):
        paths = export_markdown(multiple_enriched_repos, tmp_path)
        unified = [p for p in paths if p.name.endswith("_all_stars.md")]
        assert len(unified) >= 2
        content = unified[0].read_text()
        assert "GitHub Stars" in content
        assert "github.com" in content


class TestJSONLExport:
    def test_export_jsonl(self, tmp_path, multiple_enriched_repos):
        paths = export_jsonl(multiple_enriched_repos, tmp_path)
        assert len(paths) >= 2
        for p in paths:
            lines = p.read_text().strip().split("\n")
            assert len(lines) > 0
            for line in lines:
                record = json.loads(line)
                assert "id" in record
                assert "text" in record
                assert "metadata" in record
                assert "url" in record

    def test_jsonl_with_embeddings(self, tmp_path):
        r = EnrichedRepo(
            full_name="a/b", owner="a", repo="b",
            url="https://github.com/a/b",
            embedding=[0.1, 0.2, 0.3],
        )
        paths = export_jsonl([r], tmp_path, include_embeddings=True)
        for p in paths:
            record = json.loads(p.read_text().strip())
            assert "embedding" in record

    def test_jsonl_without_embeddings(self, tmp_path):
        r = EnrichedRepo(
            full_name="a/b", owner="a", repo="b",
            url="https://github.com/a/b",
        )
        paths = export_jsonl([r], tmp_path, include_embeddings=False)
        for p in paths:
            record = json.loads(p.read_text().strip())
            assert "embedding" not in record


class TestCSVExport:
    def test_export_csv(self, tmp_path, multiple_enriched_repos):
        paths = export_csv(multiple_enriched_repos, tmp_path)
        assert len(paths) >= 2
        for p in paths:
            content = p.read_text()
            lines = content.strip().split("\n")
            assert len(lines) > 1
            assert "full_name" in lines[0]
            assert "utility_score" in lines[0]

    def test_csv_columns(self, tmp_path):
        r = EnrichedRepo(
            full_name="a/b", owner="a", repo="b", url="https://github.com/a/b",
            scraped_by="testuser",
        )
        paths = export_csv([r], tmp_path)
        for p in paths:
            reader = csv.DictReader(p.open())
            rows = list(reader)
            assert len(rows) >= 1
            assert "scraped_by" in reader.fieldnames
            assert "utility_score" in reader.fieldnames


class TestGitHubFormat:
    def test_export_manifest(self, tmp_path, multiple_enriched_repos):
        paths = export_github_format(multiple_enriched_repos, tmp_path)
        assert len(paths) >= 2
        for p in paths:
            data = json.loads(p.read_text())
            assert "version" in data
            assert "user" in data
            assert "repos" in data
            assert len(data["repos"]) > 0

    def test_export_restar_batch(self, tmp_path, multiple_enriched_repos):
        paths = export_restar_batch(multiple_enriched_repos, tmp_path)
        assert len(paths) >= 2
        for p in paths:
            lines = p.read_text().strip().split("\n")
            assert len(lines) > 0
            assert "/" in lines[0]
