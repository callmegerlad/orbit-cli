from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from orbit.config import OrbitConfig, parse_period_to_hours
from orbit.github import GitHubClient, cutoff_for_period_hours
from orbit.models import EvidenceItem, StudioSnapshot, VentureSnapshot


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    # GitHub returns RFC3339 with trailing Z; fromisoformat handles offsets in 3.11+.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _pr_state(pr: dict[str, Any]) -> str:
    if pr.get("merged_at"):
        return "merged"
    return str(pr.get("state") or "unknown")


def _pr_to_evidence(venture: str, repo: str, pr: dict[str, Any]) -> EvidenceItem:
    return EvidenceItem(
        source_type="pull_request",
        venture=venture,
        repo=repo,
        title=str(pr.get("title") or "(no title)"),
        url=str(pr.get("html_url") or ""),
        author=(pr.get("user") or {}).get("login"),
        created_at=_parse_dt(pr.get("created_at")),
        updated_at=_parse_dt(pr.get("updated_at")),
        state=_pr_state(pr),
        labels=[lbl["name"] for lbl in (pr.get("labels") or []) if "name" in lbl],
        summary=(pr.get("body") or "")[:500] or None,
        raw_metadata={
            "number": pr.get("number"),
            "merged_at": pr.get("merged_at"),
            "draft": pr.get("draft", False),
            "requested_reviewers": [
                r.get("login") for r in (pr.get("requested_reviewers") or [])
            ],
            "comments": pr.get("comments"),
            "review_comments": pr.get("review_comments"),
        },
    )


def _issue_to_evidence(venture: str, repo: str, issue: dict[str, Any]) -> EvidenceItem:
    return EvidenceItem(
        source_type="issue",
        venture=venture,
        repo=repo,
        title=str(issue.get("title") or "(no title)"),
        url=str(issue.get("html_url") or ""),
        author=(issue.get("user") or {}).get("login"),
        created_at=_parse_dt(issue.get("created_at")),
        updated_at=_parse_dt(issue.get("updated_at")),
        state=str(issue.get("state") or "unknown"),
        labels=[lbl["name"] for lbl in (issue.get("labels") or []) if "name" in lbl],
        summary=(issue.get("body") or "")[:500] or None,
        raw_metadata={
            "number": issue.get("number"),
            "comments": issue.get("comments"),
        },
    )


def _commit_to_evidence(venture: str, repo: str, commit: dict[str, Any]) -> EvidenceItem:
    c = commit.get("commit") or {}
    author = (commit.get("author") or {}).get("login") or (c.get("author") or {}).get("name")
    msg = str(c.get("message") or "")
    title = msg.splitlines()[0][:160] if msg else "(no message)"
    return EvidenceItem(
        source_type="commit",
        venture=venture,
        repo=repo,
        title=title,
        url=str(commit.get("html_url") or ""),
        author=author,
        created_at=_parse_dt((c.get("author") or {}).get("date")),
        updated_at=_parse_dt((c.get("committer") or {}).get("date")),
        state=None,
        labels=[],
        summary=msg[:500] or None,
        raw_metadata={"sha": commit.get("sha")},
    )


def _run_to_evidence(venture: str, repo: str, run: dict[str, Any]) -> EvidenceItem:
    return EvidenceItem(
        source_type="workflow_run",
        venture=venture,
        repo=repo,
        title=str(run.get("name") or "workflow"),
        url=str(run.get("html_url") or ""),
        author=None,
        created_at=_parse_dt(run.get("created_at")),
        updated_at=_parse_dt(run.get("updated_at")),
        state=str(run.get("conclusion") or run.get("status") or "unknown"),
        labels=[],
        summary=None,
        raw_metadata={
            "run_id": run.get("id"),
            "branch": run.get("head_branch"),
            "event": run.get("event"),
        },
    )


async def _collect_repo(
    client: GitHubClient, venture: str, repo: str, since: datetime
) -> list[EvidenceItem]:
    prs_task = client.list_pull_requests(repo)
    issues_task = client.list_issues(repo, since=since)
    commits_task = client.list_commits(repo, since=since)
    run_task = client.latest_workflow_run(repo)
    prs, issues, commits, run = await asyncio.gather(
        prs_task, issues_task, commits_task, run_task
    )
    items: list[EvidenceItem] = []
    for pr in prs:
        updated = _parse_dt(pr.get("updated_at"))
        if updated is None or updated >= since or pr.get("state") == "open":
            items.append(_pr_to_evidence(venture, repo, pr))
    for issue in issues:
        items.append(_issue_to_evidence(venture, repo, issue))
    for commit in commits:
        items.append(_commit_to_evidence(venture, repo, commit))
    if run:
        items.append(_run_to_evidence(venture, repo, run))
    return items


async def collect(config: OrbitConfig, *, period: str | None = None) -> StudioSnapshot:
    """Collect evidence for every venture in `config` over the given period."""
    from orbit.runtime import require_env

    period_str = period or config.defaults.period
    hours = parse_period_to_hours(period_str)
    since = cutoff_for_period_hours(hours)
    token = require_env("GITHUB_TOKEN")

    async with GitHubClient(token) as client:
        ventures: list[VentureSnapshot] = []
        for v in config.ventures:
            repo_results = await asyncio.gather(
                *(_collect_repo(client, v.name, r, since) for r in v.repos)
            )
            evidence = [item for batch in repo_results for item in batch]
            ventures.append(
                VentureSnapshot(
                    id=v.id,
                    name=v.name,
                    stakeholder=v.stakeholder,
                    milestone=v.milestone,
                    watch_items=list(v.watch_items or []),
                    repos=list(v.repos),
                    evidence=evidence,
                )
            )

    return StudioSnapshot(
        studio_name=config.studio.name,
        period=period_str,
        generated_at=datetime.now(timezone.utc),
        ventures=ventures,
    )
