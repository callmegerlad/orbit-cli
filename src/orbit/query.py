from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from orbit.models import EvidenceItem, StudioSnapshot, VentureSnapshot


@dataclass(frozen=True)
class PrSummary:
    number: int | None
    title: str
    url: str
    state: str
    comments: int
    review_comments: int

    @property
    def total_comments(self) -> int:
        return self.comments + self.review_comments


@dataclass(frozen=True)
class CommitSummary:
    sha: str | None
    title: str
    url: str
    repo: str


@dataclass
class MyVentureActivity:
    venture_id: str | None
    venture_name: str
    repos: list[str]
    last_touched: datetime | None = None
    prs_merged: list[PrSummary] = field(default_factory=list)
    prs_open: list[PrSummary] = field(default_factory=list)
    prs_closed: list[PrSummary] = field(default_factory=list)
    commits: list[CommitSummary] = field(default_factory=list)

    @property
    def has_activity(self) -> bool:
        return bool(self.prs_merged or self.prs_open or self.prs_closed or self.commits)

    @property
    def commit_repo_breakdown(self) -> list[tuple[str, int]]:
        counts = Counter(c.repo for c in self.commits)
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


@dataclass
class MyActivity:
    user: str
    period: str
    ventures: list[MyVentureActivity]


@dataclass
class StatusVentureContext:
    """Per-venture facts the studio status LLM call may use.

    Counts and signal lists are pre-computed deterministically. The LLM is
    instructed to use them verbatim and to pick the 2-3 most salient facts
    per venture, plus infer a one-phrase theme from open-PR titles.
    """

    venture_id: str | None
    venture_name: str
    repos: list[str]
    confidence: str
    signal_flags: list[str]
    open_pr_count: int
    merged_pr_count: int
    stale_pr_count: int
    critical_issue_count: int
    commit_count: int
    contributors: list[str]
    ci_unhealthy: bool
    low_activity: bool
    open_pr_titles: list[str]


@dataclass
class StatusContext:
    studio_name: str
    period: str
    ventures: list[StatusVentureContext]


@dataclass
class CatchupContext:
    """Everything the catchup LLM call needs for one venture.

    Splits evidence into 'changes_by_others' (what happened while you were
    away) and 'your_open_work' (so the LLM can flag potential conflicts).
    Counts and contributor breakdowns are pre-computed deterministically.
    """

    venture_id: str | None
    venture_name: str
    repos: list[str]
    user: str
    period: str
    your_last_touched: datetime | None

    commit_count: int
    merged_pr_count: int
    open_pr_count: int
    contributors: list[str]
    label_counts: list[tuple[str, int]]

    changes_by_others: list[EvidenceItem]
    your_open_work: list[EvidenceItem]
    your_open_issue_count: int


# --- builders ---------------------------------------------------------------


def _pr_summary(item: EvidenceItem) -> PrSummary:
    md = item.raw_metadata
    return PrSummary(
        number=md.get("number"),
        title=item.title,
        url=item.url,
        state=str(item.state or "unknown"),
        comments=int(md.get("comments") or 0),
        review_comments=int(md.get("review_comments") or 0),
    )


def _commit_summary(item: EvidenceItem) -> CommitSummary:
    return CommitSummary(
        sha=str(item.raw_metadata.get("sha") or "") or None,
        title=item.title,
        url=item.url,
        repo=item.repo,
    )


def _matches_user(author: str | None, user: str) -> bool:
    if not author:
        return False
    return author.lower() == user.lower()


def _filter_ventures(
    snapshot: StudioSnapshot, refs: list[str] | None
) -> list[VentureSnapshot]:
    """Restrict a snapshot's ventures to the supplied id/name refs, in order.

    Refs match either the venture id or the exact name. Unknown refs raise
    KeyError so the caller can surface a clean error message.
    """
    if not refs:
        return list(snapshot.ventures)

    by_ref: dict[str, VentureSnapshot] = {}
    for v in snapshot.ventures:
        if v.id:
            by_ref[v.id] = v
        by_ref[v.name] = v

    selected: list[VentureSnapshot] = []
    seen: set[str] = set()
    for ref in refs:
        venture = by_ref.get(ref)
        if venture is None:
            raise KeyError(ref)
        key = venture.id or venture.name
        if key in seen:
            continue
        seen.add(key)
        selected.append(venture)
    return selected


def build_my_activity(
    snapshot: StudioSnapshot,
    user: str,
    *,
    venture_refs: list[str] | None = None,
) -> MyActivity:
    """Build a per-venture summary of `user`'s activity in the snapshot.

    `venture_refs` optionally restricts the output to a subset of ventures,
    matched by id or exact name. Order is preserved.
    """
    if not user:
        raise ValueError("user must be a non-empty string")

    selected = _filter_ventures(snapshot, venture_refs)

    ventures: list[MyVentureActivity] = []
    for v in selected:
        mine = [e for e in v.evidence if _matches_user(e.author, user)]
        prs_merged: list[PrSummary] = []
        prs_open: list[PrSummary] = []
        prs_closed: list[PrSummary] = []
        commits: list[CommitSummary] = []
        last_touched: datetime | None = None

        for item in mine:
            ts = item.updated_at or item.created_at
            if ts and (last_touched is None or ts > last_touched):
                last_touched = ts
            if item.source_type == "pull_request":
                summary = _pr_summary(item)
                if summary.state == "merged":
                    prs_merged.append(summary)
                elif summary.state == "open":
                    prs_open.append(summary)
                else:
                    prs_closed.append(summary)
            elif item.source_type == "commit":
                commits.append(_commit_summary(item))

        ventures.append(
            MyVentureActivity(
                venture_id=v.id,
                venture_name=v.name,
                repos=list(v.repos),
                last_touched=last_touched,
                prs_merged=prs_merged,
                prs_open=prs_open,
                prs_closed=prs_closed,
                commits=commits,
            )
        )

    return MyActivity(user=user, period=snapshot.period, ventures=ventures)


YOUR_OPEN_WORK_CAP = 5
STATUS_OPEN_PR_TITLE_CAP = 8


def build_status(
    snapshot: StudioSnapshot,
    *,
    venture_refs: list[str] | None = None,
) -> StatusContext:
    """Build a portfolio-level status view, one entry per venture.

    Reuses the snapshot's already-annotated risk signals and confidence
    levels rather than recomputing them. The caller is expected to have
    run `annotate_snapshot` first (the CLI does this in `_resolve_snapshot`).
    """
    selected = _filter_ventures(snapshot, venture_refs)

    contexts: list[StatusVentureContext] = []
    for v in selected:
        signal_flags = [s.flag for s in v.signals]
        stale_pr_count = sum(1 for s in v.signals if s.flag == "review_backlog")
        critical_issue_count = sum(1 for s in v.signals if s.flag == "delivery_risk")
        ci_unhealthy = any(s.flag == "ci_unhealthy" for s in v.signals)
        low_activity = any(s.flag == "low_activity" for s in v.signals)

        open_prs: list[EvidenceItem] = []
        contributors: set[str] = set()
        for item in v.evidence:
            if item.author:
                contributors.add(item.author)
            if (
                item.source_type == "pull_request"
                and item.state == "open"
                and not item.raw_metadata.get("draft")
            ):
                open_prs.append(item)

        open_prs.sort(
            key=lambda i: (
                i.updated_at or i.created_at or datetime.min.replace(tzinfo=timezone.utc)
            ),
            reverse=True,
        )
        open_pr_titles = [item.title for item in open_prs[:STATUS_OPEN_PR_TITLE_CAP]]

        contexts.append(
            StatusVentureContext(
                venture_id=v.id,
                venture_name=v.name,
                repos=list(v.repos),
                confidence=v.confidence,
                signal_flags=signal_flags,
                open_pr_count=len(open_prs),
                merged_pr_count=v.merged_pr_count,
                stale_pr_count=stale_pr_count,
                critical_issue_count=critical_issue_count,
                commit_count=v.commit_count,
                contributors=sorted(contributors),
                ci_unhealthy=ci_unhealthy,
                low_activity=low_activity,
                open_pr_titles=open_pr_titles,
            )
        )

    return StatusContext(
        studio_name=snapshot.studio_name,
        period=snapshot.period,
        ventures=contexts,
    )


def _is_user_open_pr(item: EvidenceItem, user: str) -> bool:
    return (
        item.source_type == "pull_request"
        and item.state == "open"
        and _matches_user(item.author, user)
    )


def build_catchup(
    snapshot: StudioSnapshot,
    *,
    user: str,
    venture_ref: str,
) -> CatchupContext:
    """Build a single-venture catchup context for `user`.

    Splits evidence into changes-by-others vs. user's open work. All counts
    are computed here, before the LLM is called, so the model can only ever
    paraphrase them.
    """
    if not user:
        raise ValueError("user must be a non-empty string")

    [venture] = _filter_ventures(snapshot, [venture_ref])

    changes_by_others: list[EvidenceItem] = []
    your_evidence: list[EvidenceItem] = []
    your_last_touched: datetime | None = None
    contributors: set[str] = set()
    label_tally: Counter[str] = Counter()
    commit_count = 0
    merged_pr_count = 0
    open_pr_count = 0
    your_open_issue_count = 0

    for item in venture.evidence:
        is_user = _matches_user(item.author, user)
        if is_user:
            your_evidence.append(item)
            ts = item.updated_at or item.created_at
            if ts and (your_last_touched is None or ts > your_last_touched):
                your_last_touched = ts
            if item.source_type == "issue" and item.state == "open":
                your_open_issue_count += 1
            continue

        changes_by_others.append(item)
        if item.author:
            contributors.add(item.author)
        if item.source_type == "commit":
            commit_count += 1
        elif item.source_type == "pull_request":
            if item.state == "merged":
                merged_pr_count += 1
            elif item.state == "open":
                open_pr_count += 1
        elif item.source_type == "issue" and item.state == "open":
            for label in item.labels:
                label_tally[label] += 1

    your_open_prs = [item for item in your_evidence if _is_user_open_pr(item, user)]
    your_open_prs.sort(
        key=lambda i: (i.updated_at or i.created_at or datetime.min.replace(tzinfo=timezone.utc)),
        reverse=True,
    )

    return CatchupContext(
        venture_id=venture.id,
        venture_name=venture.name,
        repos=list(venture.repos),
        user=user,
        period=snapshot.period,
        your_last_touched=your_last_touched,
        commit_count=commit_count,
        merged_pr_count=merged_pr_count,
        open_pr_count=open_pr_count,
        contributors=sorted(contributors),
        label_counts=sorted(
            label_tally.items(), key=lambda item: (-item[1], item[0])
        ),
        changes_by_others=changes_by_others,
        your_open_work=your_open_prs[:YOUR_OPEN_WORK_CAP],
        your_open_issue_count=your_open_issue_count,
    )


# --- humanisation -----------------------------------------------------------


def _humanise_age(when: datetime, *, now: datetime) -> str:
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    delta = now - when
    seconds = delta.total_seconds()
    if seconds < 0:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return "just now" if minutes < 1 else f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    if days < 30:
        return f"{days} day{'s' if days != 1 else ''} ago"
    months = days // 30
    return f"{months} month{'s' if months != 1 else ''} ago"


# --- rendering --------------------------------------------------------------


def _comment_suffix(pr: PrSummary) -> str:
    total = pr.total_comments
    if total == 0:
        return ""
    return f", {total} comment{'s' if total != 1 else ''}"


def _pr_line(pr: PrSummary, *, label: str) -> Text:
    number = f"#{pr.number}" if pr.number is not None else "(no number)"
    line = Text()
    line.append(f"  {number} ", style="bold cyan")
    line.append(f"({label}{_comment_suffix(pr)}) ", style="dim")
    line.append(pr.title)
    return line


def _venture_panel(venture: MyVentureActivity, *, now: datetime) -> Panel:
    body: list[Text] = []
    repos_line = Text()
    repos_line.append("Repos: ", style="dim")
    repos_line.append(", ".join(venture.repos) or "(none)")
    body.append(repos_line)

    touched = Text()
    touched.append("Last touched: ", style="dim")
    if venture.last_touched is None:
        touched.append("no activity in this period", style="yellow")
    else:
        touched.append(_humanise_age(venture.last_touched, now=now))
    body.append(touched)

    if not venture.has_activity:
        return Panel(
            Group(*body),
            title=Text(venture.venture_name, style="bold"),
            border_style="dim",
            padding=(0, 1),
        )

    if venture.prs_merged or venture.prs_open or venture.prs_closed:
        body.append(Text("Your PRs:", style="dim"))
        for pr in venture.prs_merged:
            body.append(_pr_line(pr, label="merged"))
        for pr in venture.prs_open:
            body.append(_pr_line(pr, label="open"))
        for pr in venture.prs_closed:
            body.append(_pr_line(pr, label=pr.state or "closed"))

    if venture.commits:
        commit_line = Text()
        commit_line.append("Your commits: ", style="dim")
        breakdown = venture.commit_repo_breakdown
        commit_line.append(f"{len(venture.commits)} commit")
        if len(venture.commits) != 1:
            commit_line.append("s")
        if len(breakdown) == 1:
            commit_line.append(f" in {breakdown[0][0]}")
        else:
            parts = ", ".join(f"{repo} ({count})" for repo, count in breakdown)
            commit_line.append(f" across {parts}")
        body.append(commit_line)

    return Panel(
        Group(*body),
        title=Text(venture.venture_name, style="bold"),
        border_style="cyan",
        padding=(0, 1),
    )


def render_my_activity(activity: MyActivity, *, now: datetime | None = None) -> Group:
    """Build a Rich Group ready for `console.print(...)`."""
    when = now or datetime.now(timezone.utc)
    header = Text()
    header.append(f"Activity for @{activity.user} ", style="bold")
    header.append(f"(last {activity.period})", style="dim")
    panels = [_venture_panel(v, now=when) for v in activity.ventures]
    return Group(header, Text(""), *panels)
