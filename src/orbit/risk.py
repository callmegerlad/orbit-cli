from __future__ import annotations

from datetime import datetime, timezone

from orbit.models import EvidenceItem, RiskFlag, RiskSignal, VentureSnapshot

REVIEW_BACKLOG_DAYS = 2
LOW_ACTIVITY_COMMITS = 3
BLOCKER_LABELS = frozenset({"blocker", "urgent", "critical", "p0"})


def _hours_since(dt: datetime | None) -> float:
    if dt is None:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600


def _signal(flag: RiskFlag, venture: str, reason: str, *, repo: str | None = None,
            urls: list[str] | None = None) -> RiskSignal:
    return RiskSignal(
        flag=flag, venture=venture, repo=repo, reason=reason, evidence_urls=urls or []
    )


def detect_signals(snapshot: VentureSnapshot) -> list[RiskSignal]:
    """Return all risk signals that apply to a venture's collected evidence."""
    signals: list[RiskSignal] = []

    for item in snapshot.evidence:
        if item.source_type == "pull_request" and item.state == "open":
            if item.raw_metadata.get("draft"):
                continue
            age_h = _hours_since(item.created_at)
            if age_h > REVIEW_BACKLOG_DAYS * 24:
                signals.append(
                    _signal(
                        "review_backlog",
                        snapshot.name,
                        repo=item.repo,
                        reason=(
                            f"PR {_pr_ref(item)} open for "
                            f"{int(age_h / 24)} days without approval"
                        ),
                        urls=[item.url],
                    )
                )

        if item.source_type == "issue" and item.state == "open":
            if any(lbl.lower() in BLOCKER_LABELS for lbl in item.labels):
                signals.append(
                    _signal(
                        "delivery_risk",
                        snapshot.name,
                        repo=item.repo,
                        reason=f"Issue {_issue_ref(item)} labelled blocker/urgent",
                        urls=[item.url],
                    )
                )

        if item.source_type == "workflow_run" and item.state == "failure":
            signals.append(
                _signal(
                    "ci_unhealthy",
                    snapshot.name,
                    repo=item.repo,
                    reason=f"Latest CI run on {item.repo} failed",
                    urls=[item.url],
                )
            )

    if snapshot.merged_pr_count == 0 and snapshot.commit_count < LOW_ACTIVITY_COMMITS:
        signals.append(
            _signal(
                "low_activity",
                snapshot.name,
                reason=(
                    f"{snapshot.merged_pr_count} merged PRs and "
                    f"{snapshot.commit_count} commits in period"
                ),
            )
        )

    return signals


def _pr_ref(item: EvidenceItem) -> str:
    n = item.raw_metadata.get("number")
    return f"#{n}" if n else item.title


def _issue_ref(item: EvidenceItem) -> str:
    n = item.raw_metadata.get("number")
    return f"#{n}" if n else item.title
