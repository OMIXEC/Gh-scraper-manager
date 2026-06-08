"""GitHub API scraper - resolves users and fetches starred repositories."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Optional

import httpx

from ghstars.models import StarredRepo


GRAPHQL_ENDPOINT = "https://api.github.com/graphql"
REST_ENDPOINT = "https://api.github.com"

USER_LOOKUP_QUERY = """
query($query: String!) {
  search(query: $query, type: USER, first: 1) {
    nodes {
      ... on User {
        login
        name
        email
        avatarUrl
      }
    }
  }
}
"""

STARS_QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    starredRepositories(first: 100, after: $cursor, orderBy: {field: STARRED_AT, direction: DESC}) {
      totalCount
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        nameWithOwner
        name
        owner { login }
        url
        description
        repositoryTopics(first: 10) {
          nodes {
            topic { name }
          }
        }
        primaryLanguage { name }
        stargazerCount
        forkCount
        licenseInfo { name }
        homepageUrl
        createdAt
        updatedAt
      }
    }
  }
}
"""

README_QUERY = """
query($owner: String!, $repo: String!) {
  repository(owner: $owner, name: $repo) {
    object(expression: "HEAD:README.md") {
      ... on Blob { text }
    }
    description
  }
}
"""


class GitHubClient:
    """Async GitHub API client for scraping starred repositories."""

    def __init__(self, token: Optional[str] = None, max_concurrency: int = 5):
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "gh-stars-manager/0.1.0",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        self.token = token
        self.client = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
        )
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def close(self):
        await self.client.aclose()

    async def _graphql(self, query: str, variables: dict) -> dict:
        resp = await self.client.post(GRAPHQL_ENDPOINT, json={"query": query, "variables": variables})
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            errors = [e["message"] for e in data["errors"]]
            if any("rate limit" in e.lower() for e in errors):
                raise RateLimitError("; ".join(errors))
            raise GraphQLError("; ".join(errors))
        return data["data"]

    async def resolve_user(self, query: str) -> Optional[str]:
        """Resolve a GitHub username from email, name, or profile URL.

        Args:
            query: GitHub username, email, or profile URL.

        Returns:
            GitHub login (username) if found, None otherwise.
        """
        # Handle profile URL
        if "github.com/" in query:
            parts = query.rstrip("/").split("/")
            if len(parts) >= 1:
                return parts[-1]

        # Try GraphQL search for email/name
        try:
            data = await self._graphql(USER_LOOKUP_QUERY, {"query": query})
            nodes = data.get("search", {}).get("nodes", [])
            if nodes:
                return nodes[0]["login"]
        except (GraphQLError, httpx.HTTPError):
            pass

        # Fallback: try REST API
        try:
            resp = await self.client.get(f"{REST_ENDPOINT}/users/{query}")
            if resp.status_code == 200:
                return resp.json()["login"]
        except httpx.HTTPError:
            pass

        return None

    async def fetch_starred_repos(
        self, username: str, incremental: bool = False,
        newer_than: Optional[str] = None,
    ) -> list[StarredRepo]:
        """Fetch starred repositories for a GitHub user.

        Tries GraphQL first (requires auth), falls back to REST API.
        If incremental=True, stops when encountering repos older than newer_than.
        """
        try:
            return await self._fetch_starred_graphql(username, incremental, newer_than)
        except (GraphQLError, RateLimitError, httpx.HTTPStatusError):
            pass
        return await self._fetch_starred_rest(username, incremental, newer_than)

    async def _fetch_starred_graphql(
        self, username: str, incremental: bool = False, newer_than: Optional[str] = None
    ) -> list[StarredRepo]:
        """Fetch starred repos via GraphQL API (requires authentication)."""
        repos = []
        cursor = None
        has_next = True

        while has_next:
            variables = {"login": username, "cursor": cursor}
            data = await self._graphql(STARS_QUERY, variables)
            user_data = data.get("user")
            if not user_data:
                break

            starred = user_data["starredRepositories"]
            for node in starred["nodes"]:
                topics = [t["topic"]["name"] for t in node.get("repositoryTopics", {}).get("nodes", [])]
                license_name = None
                if node.get("licenseInfo"):
                    license_name = node["licenseInfo"]["name"]

                repos.append(StarredRepo(
                    full_name=node["nameWithOwner"],
                    owner=node["owner"]["login"],
                    repo=node["name"],
                    url=node["url"],
                    description=node.get("description"),
                    topics=topics,
                    language=node.get("primaryLanguage", {}).get("name") if node.get("primaryLanguage") else None,
                    stars=node.get("stargazerCount", 0),
                    forks=node.get("forkCount", 0),
                    license=license_name,
                    homepage=node.get("homepageUrl"),
                    created_at=node.get("createdAt"),
                    updated_at=node.get("updatedAt"),
                    scraped_by=username,
                ))

            has_next = starred["pageInfo"]["hasNextPage"]
            cursor = starred["pageInfo"]["endCursor"]

        return repos

    async def _fetch_starred_rest(
        self, username: str, incremental: bool = False, newer_than: Optional[str] = None
    ) -> list[StarredRepo]:
        """Fetch starred repos via REST API (works without auth, 60 req/hr).

        Uses star+json accept header to get starred_at timestamps.
        In incremental mode, stops when repos are older than newer_than.
        """
        repos = []
        page = 1
        stop_next = False

        while True:
            resp = await self.client.get(
                f"{REST_ENDPOINT}/users/{username}/starred",
                params={"page": page, "per_page": 100, "sort": "created", "direction": "desc"},
                headers={"Accept": "application/vnd.github.v3.star+json"},
            )

            if resp.status_code == 403 and "rate limit" in resp.text.lower():
                raise RateLimitError("REST API rate limit exceeded")
            if resp.status_code != 200:
                break

            data = resp.json()
            if not data:
                break

            for item in data:
                starred_at = item.get("starred_at")
                repo_data = item.get("repo", item)
                if incremental and newer_than and starred_at and starred_at <= newer_than:
                    stop_next = True
                    break

                repos.append(StarredRepo(
                    full_name=repo_data["full_name"],
                    owner=repo_data["owner"]["login"],
                    repo=repo_data["name"],
                    url=repo_data["html_url"],
                    description=repo_data.get("description"),
                    topics=repo_data.get("topics", []),
                    language=repo_data.get("language"),
                    stars=repo_data.get("stargazers_count", 0),
                    forks=repo_data.get("forks_count", 0),
                    license=repo_data.get("license", {}).get("name") if repo_data.get("license") else None,
                    homepage=repo_data.get("homepage"),
                    created_at=repo_data.get("created_at"),
                    updated_at=repo_data.get("updated_at"),
                    starred_at=starred_at,
                    scraped_by=username,
                ))

            if stop_next:
                break
            page += 1

        return repos

    async def fetch_readme(self, owner: str, repo: str) -> tuple[Optional[str], Optional[str]]:
        """Fetch README content and repo description via GraphQL.

        Returns:
            Tuple of (readme_text, readme_summary).
        """
        try:
            data = await self._graphql(README_QUERY, {"owner": owner, "repo": repo})
            repo_data = data.get("repository", {})
            obj = repo_data.get("object")
            readme_text = obj["text"] if obj else None
            readme_summary = repo_data.get("description")
            return readme_text, readme_summary
        except (GraphQLError, httpx.HTTPError):
            return None, None

    async def fetch_readmes_batch(
        self, repos: list[StarredRepo], progress_callback=None
    ) -> list[StarredRepo]:
        """Fetch READMEs for a batch of repos concurrently."""

        async def _fetch_one(repo: StarredRepo) -> StarredRepo:
            async with self._semaphore:
                readme, summary = await self.fetch_readme(repo.owner, repo.repo)
                repo.readme_text = readme
                repo.readme_summary = summary or repo.description
                return repo

        tasks = [_fetch_one(r) for r in repos]
        results = []
        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result)
            if progress_callback:
                progress_callback()
        return results


class RateLimitError(Exception):
    """GitHub API rate limit exceeded."""


class GraphQLError(Exception):
    """GitHub GraphQL API error."""
