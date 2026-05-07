"""Tests for `orbit.query`: the deterministic 'pull' view layer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from rich.console import Console

from orbit.models import EvidenceItem, RiskSignal, StudioSnapshot, VentureSnapshot
from orbit.query import (
    build_catchup,
    build_my_activity,
    build_status,
    render_my_activity,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pr(
    *,
    venture: str,
    repo: str,
    number: int,
    author: str,
    state: str,
    title: str = "Some PR",
    comments: int = 0,
    review_comments: int = 0,
    when: datetime | None = None,
) -> EvidenceItem:
    when = when or _now()
    return EvidenceItem(
        source_type="pull_request",
        venture=venture,
        repo=repo,
        title=title,
        url=f"https://github.com/{repo}/pull/{number}",
        author=author,
        created_at=when,
        updated_at=when,
        state=state,
        raw_metadata={
            "number": number,
            "draft": False,
            "comments": comments,
            "review_comments": review_comments,
        },
    )


def _commit(
    *,
    venture: str,
    repo: str,
    sha: str,
    author: str,
    title: str = "Some commit",
    when: datetime | None = None,
) -> EvidenceItem:
    when = when or _now()
    return EvidenceItem(
        source_type="commit",
        venture=venture,
        repo=repo,
        title=title,
        url=f"https://github.com/{repo}/commit/{sha}",
        author=author,
        created_at=when,
        raw_metadata={"sha": sha},
    )


def _snapshot(*ventures: VentureSnapshot, period: str = "7d") -> StudioSnapshot:
    return StudioSnapshot(
        studio_name="Orbital Ventures",
        period=period,
        generated_at=_now(),
        ventures=list(ventures),
    )


# --- build_my_activity ------------------------------------------------------


def test_build_my_activity_filters_by_author_case_insensitively() -> None:
    helios = VentureSnapshot(
        id="helios-health",
        name="Helios Health",
        repos=["orbital-ventures/helios-api"],
        evidence=[
            _pr(venture="Helios Health", repo="orbital-ventures/helios-api",
                number=42, author="Avery", state="merged"),
            _pr(venture="Helios Health", repo="orbital-ventures/helios-api",
                number=43, author="someone-else", state="merged"),
        ],
    )

    activity = build_my_activity(_snapshot(helios), user="avery")

    assert activity.user == "avery"
    [v] = activity.ventures
    assert [pr.number for pr in v.prs_merged] == [42]


def test_build_my_activity_groups_prs_by_state_and_records_commits() -> None:
    venture = VentureSnapshot(
        id="atlas-logistics",
        name="Atlas Logistics",
        repos=["orbital-ventures/atlas-router"],
        evidence=[
            _pr(venture="Atlas Logistics", repo="orbital-ventures/atlas-router",
                number=88, author="devi", state="merged"),
            _pr(venture="Atlas Logistics", repo="orbital-ventures/atlas-router",
                number=92, author="devi", state="open", comments=2, review_comments=1),
            _pr(venture="Atlas Logistics", repo="orbital-ventures/atlas-router",
                number=70, author="devi", state="closed"),
            _commit(venture="Atlas Logistics", repo="orbital-ventures/atlas-router",
                    sha="a1b2c3d", author="devi"),
            _commit(venture="Atlas Logistics", repo="orbital-ventures/atlas-router",
                    sha="d4e5f6a", author="devi"),
        ],
    )

    activity = build_my_activity(_snapshot(venture), user="devi")
    [v] = activity.ventures

    assert [pr.number for pr in v.prs_merged] == [88]
    assert [pr.number for pr in v.prs_open] == [92]
    assert [pr.number for pr in v.prs_closed] == [70]
    assert v.prs_open[0].total_comments == 3
    assert len(v.commits) == 2


def test_build_my_activity_marks_no_activity_ventures() -> None:
    quiet = VentureSnapshot(
        id="lumen-edu",
        name="Lumen Edu",
        repos=["orbital-ventures/lumen-classroom"],
        evidence=[
            _pr(venture="Lumen Edu", repo="orbital-ventures/lumen-classroom",
                number=1, author="someone-else", state="merged"),
        ],
    )

    activity = build_my_activity(_snapshot(quiet), user="avery")
    [v] = activity.ventures
    assert v.has_activity is False
    assert v.last_touched is None


def test_build_my_activity_last_touched_is_most_recent_item() -> None:
    earlier = _now() - timedelta(days=4)
    later = _now() - timedelta(days=1)
    venture = VentureSnapshot(
        id="helios-health",
        name="Helios Health",
        repos=["orbital-ventures/helios-api"],
        evidence=[
            _pr(venture="Helios Health", repo="orbital-ventures/helios-api",
                number=1, author="avery", state="merged", when=earlier),
            _commit(venture="Helios Health", repo="orbital-ventures/helios-api",
                    sha="a1b2c3d", author="avery", when=later),
        ],
    )

    activity = build_my_activity(_snapshot(venture), user="avery")
    [v] = activity.ventures
    assert v.last_touched == later


def test_build_my_activity_commit_breakdown_counts_per_repo() -> None:
    venture = VentureSnapshot(
        id="helios-health",
        name="Helios Health",
        repos=["orbital-ventures/helios-api", "orbital-ventures/helios-portal"],
        evidence=[
            _commit(venture="Helios Health", repo="orbital-ventures/helios-api",
                    sha="a", author="avery"),
            _commit(venture="Helios Health", repo="orbital-ventures/helios-api",
                    sha="b", author="avery"),
            _commit(venture="Helios Health", repo="orbital-ventures/helios-portal",
                    sha="c", author="avery"),
        ],
    )
    [v] = build_my_activity(_snapshot(venture), user="avery").ventures
    assert v.commit_repo_breakdown == [
        ("orbital-ventures/helios-api", 2),
        ("orbital-ventures/helios-portal", 1),
    ]


def test_build_my_activity_rejects_empty_user() -> None:
    with pytest.raises(ValueError):
        build_my_activity(_snapshot(), user="")


def test_build_my_activity_filters_to_specified_venture_refs() -> None:
    helios = VentureSnapshot(
        id="helios-health", name="Helios Health",
        repos=["orbital-ventures/helios-api"], evidence=[],
    )
    atlas = VentureSnapshot(
        id="atlas-logistics", name="Atlas Logistics",
        repos=["orbital-ventures/atlas-router"], evidence=[],
    )
    lumen = VentureSnapshot(
        id="lumen-edu", name="Lumen Edu",
        repos=["orbital-ventures/lumen-classroom"], evidence=[],
    )

    activity = build_my_activity(
        _snapshot(helios, atlas, lumen),
        user="avery",
        venture_refs=["atlas-logistics", "helios-health"],
    )

    # Order follows the refs argument, not the snapshot order.
    assert [v.venture_id for v in activity.ventures] == ["atlas-logistics", "helios-health"]


def test_build_my_activity_accepts_venture_name_as_ref() -> None:
    helios = VentureSnapshot(
        id="helios-health", name="Helios Health",
        repos=["orbital-ventures/helios-api"], evidence=[],
    )
    activity = build_my_activity(
        _snapshot(helios), user="avery", venture_refs=["Helios Health"]
    )
    assert [v.venture_id for v in activity.ventures] == ["helios-health"]


def test_build_my_activity_deduplicates_repeated_refs() -> None:
    helios = VentureSnapshot(
        id="helios-health", name="Helios Health",
        repos=["orbital-ventures/helios-api"], evidence=[],
    )
    activity = build_my_activity(
        _snapshot(helios),
        user="avery",
        venture_refs=["helios-health", "Helios Health"],
    )
    assert [v.venture_id for v in activity.ventures] == ["helios-health"]


def test_build_my_activity_raises_on_unknown_venture_ref() -> None:
    helios = VentureSnapshot(
        id="helios-health", name="Helios Health",
        repos=["orbital-ventures/helios-api"], evidence=[],
    )
    with pytest.raises(KeyError):
        build_my_activity(_snapshot(helios), user="avery", venture_refs=["nope"])


# --- rendering --------------------------------------------------------------


def _render(activity, *, now: datetime | None = None) -> str:  # type: ignore[no-untyped-def]
    console = Console(record=True, width=120, color_system=None)
    console.print(render_my_activity(activity, now=now))
    return console.export_text()


def test_render_includes_user_period_and_each_venture_panel() -> None:
    helios = VentureSnapshot(
        id="helios-health", name="Helios Health",
        repos=["orbital-ventures/helios-api"],
        evidence=[
            _pr(venture="Helios Health", repo="orbital-ventures/helios-api",
                number=42, author="avery", state="merged"),
        ],
    )
    atlas = VentureSnapshot(
        id="atlas-logistics", name="Atlas Logistics",
        repos=["orbital-ventures/atlas-router"], evidence=[],
    )

    output = _render(build_my_activity(_snapshot(helios, atlas), user="avery"))

    assert "Activity for @avery" in output
    assert "(last 7d)" in output
    assert "Helios Health" in output
    assert "Atlas Logistics" in output
    assert "no activity in this period" in output


def test_render_shows_pr_state_and_comment_count() -> None:
    venture = VentureSnapshot(
        id="atlas-logistics", name="Atlas Logistics",
        repos=["orbital-ventures/atlas-router"],
        evidence=[
            _pr(venture="Atlas Logistics", repo="orbital-ventures/atlas-router",
                number=92, author="devi", state="open", comments=2, review_comments=1,
                title="Redesign dispatcher dashboard"),
        ],
    )
    output = _render(build_my_activity(_snapshot(venture), user="devi"))

    assert "#92" in output
    assert "(open, 3 comments)" in output
    assert "Redesign dispatcher dashboard" in output


def test_render_shows_humanised_last_touched() -> None:
    fixed_now = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)
    venture = VentureSnapshot(
        id="helios-health", name="Helios Health",
        repos=["orbital-ventures/helios-api"],
        evidence=[
            _commit(venture="Helios Health", repo="orbital-ventures/helios-api",
                    sha="abcdef0", author="avery",
                    when=fixed_now - timedelta(days=3, hours=2)),
        ],
    )
    output = _render(
        build_my_activity(_snapshot(venture), user="avery"),
        now=fixed_now,
    )
    assert "3 days ago" in output


def _issue(
    *,
    venture: str,
    repo: str,
    number: int,
    author: str,
    state: str,
    labels: tuple[str, ...] = (),
    title: str = "Some issue",
) -> EvidenceItem:
    return EvidenceItem(
        source_type="issue",
        venture=venture,
        repo=repo,
        title=title,
        url=f"https://github.com/{repo}/issues/{number}",
        author=author,
        state=state,
        labels=list(labels),
        raw_metadata={"number": number},
    )


# --- build_catchup ----------------------------------------------------------


def _consumer_venture() -> VentureSnapshot:
    return VentureSnapshot(
        id="consumer-app",
        name="Consumer App",
        repos=["orbital-ventures/consumer-web"],
        evidence=[
            # Other contributors' work — what changed while I was away
            _pr(venture="Consumer App", repo="orbital-ventures/consumer-web",
                number=22, author="wei-lin", state="merged",
                title="Migrate auth from JWT to session-based"),
            _pr(venture="Consumer App", repo="orbital-ventures/consumer-web",
                number=24, author="raj", state="merged",
                title="Add /api/notifications endpoint"),
            _commit(venture="Consumer App", repo="orbital-ventures/consumer-web",
                    sha="aaa1111", author="wei-lin"),
            _commit(venture="Consumer App", repo="orbital-ventures/consumer-web",
                    sha="bbb2222", author="raj"),
            _issue(venture="Consumer App", repo="orbital-ventures/consumer-web",
                   number=30, author="raj", state="open", labels=("bug",)),
            _issue(venture="Consumer App", repo="orbital-ventures/consumer-web",
                   number=31, author="wei-lin", state="open", labels=("urgent",)),
            # My work — should NOT appear in changes_by_others
            _pr(venture="Consumer App", repo="orbital-ventures/consumer-web",
                number=18, author="me", state="open",
                title="User profile flow refresh"),
            _commit(venture="Consumer App", repo="orbital-ventures/consumer-web",
                    sha="ccc3333", author="me"),
        ],
    )


def test_build_catchup_excludes_users_own_evidence_from_changes() -> None:
    ctx = build_catchup(_snapshot(_consumer_venture()), user="me", venture_ref="consumer-app")

    other_authors = {item.author for item in ctx.changes_by_others}
    assert "me" not in other_authors
    assert ctx.commit_count == 2
    assert ctx.merged_pr_count == 2
    assert sorted(ctx.contributors) == ["raj", "wei-lin"]


def test_build_catchup_collects_users_open_prs_for_cross_reference() -> None:
    ctx = build_catchup(_snapshot(_consumer_venture()), user="me", venture_ref="consumer-app")

    assert [item.raw_metadata["number"] for item in ctx.your_open_work] == [18]


def test_build_catchup_caps_users_open_prs() -> None:
    venture = VentureSnapshot(
        id="consumer-app", name="Consumer App",
        repos=["orbital-ventures/consumer-web"],
        evidence=[
            _pr(venture="Consumer App", repo="orbital-ventures/consumer-web",
                number=n, author="me", state="open")
            for n in range(20, 30)
        ],
    )
    ctx = build_catchup(_snapshot(venture), user="me", venture_ref="consumer-app")
    assert len(ctx.your_open_work) == 5  # capped at YOUR_OPEN_WORK_CAP


def test_build_catchup_label_counts_only_count_others_open_issues() -> None:
    ctx = build_catchup(_snapshot(_consumer_venture()), user="me", venture_ref="consumer-app")
    label_dict = dict(ctx.label_counts)
    assert label_dict == {"bug": 1, "urgent": 1}


def test_build_catchup_resolves_venture_by_name() -> None:
    ctx = build_catchup(_snapshot(_consumer_venture()), user="me", venture_ref="Consumer App")
    assert ctx.venture_id == "consumer-app"


def test_build_catchup_records_users_last_touched_timestamp() -> None:
    earlier = _now() - timedelta(days=10)
    later = _now() - timedelta(days=2)
    venture = VentureSnapshot(
        id="consumer-app", name="Consumer App",
        repos=["orbital-ventures/consumer-web"],
        evidence=[
            _commit(venture="Consumer App", repo="orbital-ventures/consumer-web",
                    sha="a", author="me", when=earlier),
            _pr(venture="Consumer App", repo="orbital-ventures/consumer-web",
                number=18, author="me", state="open", when=later),
        ],
    )
    ctx = build_catchup(_snapshot(venture), user="me", venture_ref="consumer-app")
    assert ctx.your_last_touched == later


def test_build_catchup_raises_on_unknown_venture_ref() -> None:
    with pytest.raises(KeyError):
        build_catchup(_snapshot(_consumer_venture()), user="me", venture_ref="nope")


def test_build_catchup_rejects_empty_user() -> None:
    with pytest.raises(ValueError):
        build_catchup(_snapshot(_consumer_venture()), user="", venture_ref="consumer-app")


# --- build_status -----------------------------------------------------------


def _signal(flag, venture, *, repo=None):  # type: ignore[no-untyped-def]
    return RiskSignal(flag=flag, venture=venture, repo=repo, reason="test", evidence_urls=[])


def _status_venture(name: str, *, signals=(), evidence=()) -> VentureSnapshot:  # type: ignore[no-untyped-def]
    return VentureSnapshot(
        id=name.lower().replace(" ", "-"),
        name=name,
        repos=[f"orbital-ventures/{name.lower().replace(' ', '-')}"],
        evidence=list(evidence),
        signals=list(signals),
        confidence="Medium",
    )


def test_build_status_uses_existing_signals_for_stale_and_critical_counts() -> None:
    venture = _status_venture(
        "Atlas",
        signals=[
            _signal("review_backlog", "Atlas"),
            _signal("review_backlog", "Atlas"),
            _signal("delivery_risk", "Atlas"),
            _signal("ci_unhealthy", "Atlas"),
        ],
    )
    [ctx] = build_status(_snapshot(venture)).ventures
    assert ctx.stale_pr_count == 2
    assert ctx.critical_issue_count == 1
    assert ctx.ci_unhealthy is True
    assert ctx.low_activity is False


def test_build_status_collects_open_pr_titles_excluding_drafts() -> None:
    repo = "orbital-ventures/atlas-router"
    open_pr = _pr(venture="Atlas", repo=repo, number=1, author="devi", state="open",
                  title="Add live ETA column")
    draft_pr = EvidenceItem(
        source_type="pull_request", venture="Atlas", repo=repo,
        title="WIP: spike",
        url=f"https://github.com/{repo}/pull/2",
        author="devi", state="open",
        raw_metadata={"number": 2, "draft": True},
    )
    merged_pr = _pr(venture="Atlas", repo=repo, number=3, author="devi", state="merged",
                    title="Already shipped")

    venture = VentureSnapshot(
        id="atlas", name="Atlas", repos=[repo],
        evidence=[open_pr, draft_pr, merged_pr],
    )

    [ctx] = build_status(_snapshot(venture)).ventures
    assert ctx.open_pr_count == 1
    assert ctx.open_pr_titles == ["Add live ETA column"]
    assert ctx.merged_pr_count == 1


def test_build_status_caps_open_pr_titles() -> None:
    repo = "orbital-ventures/atlas-router"
    venture = VentureSnapshot(
        id="atlas", name="Atlas", repos=[repo],
        evidence=[
            _pr(venture="Atlas", repo=repo, number=n, author="devi", state="open",
                title=f"PR {n}")
            for n in range(20)
        ],
    )
    [ctx] = build_status(_snapshot(venture)).ventures
    assert ctx.open_pr_count == 20
    assert len(ctx.open_pr_titles) == 8  # STATUS_OPEN_PR_TITLE_CAP


def test_build_status_low_activity_flag_passes_through() -> None:
    venture = _status_venture("Lumen", signals=[_signal("low_activity", "Lumen")])
    [ctx] = build_status(_snapshot(venture)).ventures
    assert ctx.low_activity is True


def test_build_status_filters_to_specified_venture_refs() -> None:
    helios = _status_venture("Helios")
    atlas = _status_venture("Atlas")
    lumen = _status_venture("Lumen")

    ctx = build_status(_snapshot(helios, atlas, lumen), venture_refs=["atlas", "helios"])
    assert [v.venture_id for v in ctx.ventures] == ["atlas", "helios"]


def test_build_status_unknown_venture_raises() -> None:
    venture = _status_venture("Atlas")
    with pytest.raises(KeyError):
        build_status(_snapshot(venture), venture_refs=["nope"])


# --- existing render tests continue below ----------------------------------


def test_render_shows_commit_breakdown_when_multiple_repos() -> None:
    venture = VentureSnapshot(
        id="helios-health", name="Helios Health",
        repos=["orbital-ventures/helios-api", "orbital-ventures/helios-portal"],
        evidence=[
            _commit(venture="Helios Health", repo="orbital-ventures/helios-api",
                    sha="a", author="avery"),
            _commit(venture="Helios Health", repo="orbital-ventures/helios-api",
                    sha="b", author="avery"),
            _commit(venture="Helios Health", repo="orbital-ventures/helios-portal",
                    sha="c", author="avery"),
        ],
    )
    output = _render(build_my_activity(_snapshot(venture), user="avery"))
    assert "3 commits" in output
    assert "orbital-ventures/helios-api (2)" in output
    assert "orbital-ventures/helios-portal (1)" in output
