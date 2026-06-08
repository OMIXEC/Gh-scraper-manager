"""GitHub repository mirroring - fork starred repos to a target account."""

from __future__ import annotations

import asyncio
from typing import Optional

import httpx

from ghstars.models import EnrichedRepo, ForkResult, MirrorResult


class MirrorError(Exception):
    """Error during mirroring/forking."""


class GitHubMirror:
    """Forks repositories from source to a target GitHub account."""

    def __init__(self, target_token: str, max_concurrency: int = 3):
        self.client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {target_token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "gh-stars-manager/0.1.0",
            },
            timeout=httpx.Timeout(60.0),
            follow_redirects=True,
        )
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def close(self):
        await self.client.aclose()

    async def mirror_repos(self, repos: list[EnrichedRepo], restar: bool = False) -> MirrorResult:
        """Fork all repos to the target account.

        Args:
            repos: List of repos to fork.
            restar: If True, also star each forked repo on the target account.

        Returns:
            MirrorResult with summary and per-repo details.
        """
        details = []
        for repo in repos:
            async with self._semaphore:
                result = await self._fork_repo(repo.full_name)
                if result.success and restar:
                    await self._star_repo(repo.full_name)
                details.append(result)

        return MirrorResult(
            total=len(repos),
            forked=sum(1 for r in details if r.success),
            failed=sum(1 for r in details if not r.success and r.error),
            skipped=sum(1 for r in details if not r.success and not r.error),
            details=details,
        )

    async def _fork_repo(self, full_name: str) -> ForkResult:
        """Fork a single repository via REST API."""
        owner, repo_name = full_name.split("/")

        try:
            resp = await self.client.post(
                f"https://api.github.com/repos/{owner}/{repo_name}/forks",
                json={"default_branch_only": True},
            )

            if resp.status_code == 202:
                # Fork accepted, poll for completion
                fork_url = resp.json().get("html_url", "")
                await self._wait_for_fork(full_name)
                return ForkResult(repo_full_name=full_name, success=True, fork_url=fork_url)

            elif resp.status_code == 404:
                return ForkResult(repo_full_name=full_name, success=False, error="Repository not found")

            elif resp.status_code == 403:
                return ForkResult(repo_full_name=full_name, success=False, error="Rate limited or forbidden")

            else:
                error = resp.json().get("message", f"HTTP {resp.status_code}")
                return ForkResult(repo_full_name=full_name, success=False, error=error)

        except httpx.HTTPError as e:
            return ForkResult(repo_full_name=full_name, success=False, error=str(e))

    async def _wait_for_fork(self, full_name: str, max_wait: int = 30):
        """Wait for fork to complete, polling the repo."""
        owner, repo_name = full_name.split("/")
        for _ in range(max_wait):
            await asyncio.sleep(1)
            try:
                resp = await self.client.get(f"https://api.github.com/repos/{owner}/{repo_name}")
                if resp.status_code == 200:
                    return
            except httpx.HTTPError:
                pass

    async def _star_repo(self, full_name: str):
        """Star a repository for the authenticated user."""
        owner, repo_name = full_name.split("/")
        try:
            await self.client.put(
                f"https://api.github.com/user/starred/{owner}/{repo_name}",
                headers={"Content-Length": "0"},
            )
        except httpx.HTTPError:
            pass

    async def restar_repos(
        self, full_names: list[str], progress_callback=None
    ) -> tuple[int, int]:
        """Star a list of repos on the target account.

        Args:
            full_names: List of 'owner/repo' strings.
            progress_callback: Optional callback for progress updates.

        Returns:
            Tuple of (succeeded, failed).
        """
        succeeded = 0
        failed = 0

        async def _star_one(name: str):
            nonlocal succeeded, failed
            async with self._semaphore:
                owner, repo = name.split("/")
                try:
                    resp = await self.client.put(
                        f"https://api.github.com/user/starred/{owner}/{repo}",
                        headers={"Content-Length": "0"},
                    )
                    if resp.status_code in (204, 304):
                        succeeded += 1
                    else:
                        failed += 1
                except httpx.HTTPError:
                    failed += 1
                if progress_callback:
                    progress_callback()

        await asyncio.gather(*[_star_one(name) for name in full_names])
        return succeeded, failed
