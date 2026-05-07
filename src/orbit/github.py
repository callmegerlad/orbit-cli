from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

GITHUB_API = "https://api.github.com"
USER_AGENT = "orbit-cli/0.1"


class GitHubError(Exception):
    """Raised on non-recoverable GitHub API failures."""


class GitHubClient:
    """Thin async wrapper around the GitHub REST API.

    Use as an async context manager so the underlying connection pool is
    closed deterministically.
    """

    def __init__(
        self,
        token: str,
        *,
        timeout: float = 20.0,
        max_concurrency: int = 8,
    ) -> None:
        if not token:
            raise GitHubError("GITHUB_TOKEN is required")
        self._token = token
        self._client = httpx.AsyncClient(
            base_url=GITHUB_API,
            timeout=timeout,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": USER_AGENT,
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        self._sem = asyncio.Semaphore(max_concurrency)

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        async with self._sem:
            try:
                resp = await self._client.get(path, params=params)
            except httpx.HTTPError as exc:
                raise GitHubError(f"GitHub request failed: {exc}") from exc
        if resp.status_code == 404:
            raise GitHubError(f"Not found: {path}")
        if resp.status_code == 401:
            raise GitHubError("GitHub auth failed (check GITHUB_TOKEN)")
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            raise GitHubError("GitHub rate limit exceeded")
        if resp.status_code >= 400:
            raise GitHubError(f"GitHub {resp.status_code} on {path}: {resp.text[:200]}")
        return resp.json()

    async def list_pull_requests(
        self, repo: str, *, state: str = "all", per_page: int = 50
    ) -> list[dict[str, Any]]:
        return await self._get(
            f"/repos/{repo}/pulls",
            params={"state": state, "per_page": per_page, "sort": "updated", "direction": "desc"},
        )

    async def authenticated_user(self) -> dict[str, Any]:
        return await self._get("/user")

    async def repo_info(self, repo: str) -> dict[str, Any]:
        return await self._get(f"/repos/{repo}")

    async def list_issues(
        self, repo: str, *, since: datetime, per_page: int = 50
    ) -> list[dict[str, Any]]:
        # The issues endpoint returns PRs too — caller filters them out.
        data = await self._get(
            f"/repos/{repo}/issues",
            params={
                "state": "all",
                "since": since.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                "per_page": per_page,
            },
        )
        return [item for item in data if "pull_request" not in item]

    async def list_commits(
        self, repo: str, *, since: datetime, per_page: int = 50
    ) -> list[dict[str, Any]]:
        return await self._get(
            f"/repos/{repo}/commits",
            params={
                "since": since.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                "per_page": per_page,
            },
        )

    async def latest_workflow_run(self, repo: str) -> dict[str, Any] | None:
        data = await self._get(
            f"/repos/{repo}/actions/runs",
            params={"per_page": 1, "branch": await self._default_branch(repo)},
        )
        runs = data.get("workflow_runs") or []
        return runs[0] if runs else None

    async def _default_branch(self, repo: str) -> str:
        info = await self._get(f"/repos/{repo}")
        branch = info.get("default_branch")
        if not isinstance(branch, str):
            raise GitHubError(f"Repo {repo} returned no default_branch")
        return branch


def cutoff_for_period_hours(hours: int) -> datetime:
    """The UTC datetime `hours` ago. Used as the lower bound for activity queries."""
    return datetime.now(UTC) - timedelta(hours=hours)
