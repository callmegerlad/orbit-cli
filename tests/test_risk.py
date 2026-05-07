from datetime import datetime, timedelta, timezone

from orbit.confidence import compute_confidence
from orbit.models import EvidenceItem, VentureSnapshot
from orbit.risk import detect_signals


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _venture(items: list[EvidenceItem]) -> VentureSnapshot:
    return VentureSnapshot(name="V", repos=["o/r"], evidence=items)


def test_review_backlog_flagged_for_old_open_pr() -> None:
    item = EvidenceItem(
        source_type="pull_request",
        venture="V",
        repo="o/r",
        title="Add foo",
        url="https://example.test/pr/1",
        state="open",
        created_at=_now() - timedelta(days=4),
        raw_metadata={"number": 1, "draft": False},
    )
    signals = detect_signals(_venture([item]))
    assert any(s.flag == "review_backlog" for s in signals)


def test_draft_prs_do_not_trigger_review_backlog() -> None:
    item = EvidenceItem(
        source_type="pull_request",
        venture="V",
        repo="o/r",
        title="WIP",
        url="https://example.test/pr/2",
        state="open",
        created_at=_now() - timedelta(days=10),
        raw_metadata={"number": 2, "draft": True},
    )
    assert not any(s.flag == "review_backlog" for s in detect_signals(_venture([item])))


def test_blocker_label_flags_delivery_risk() -> None:
    item = EvidenceItem(
        source_type="issue",
        venture="V",
        repo="o/r",
        title="Stripe webhook broken",
        url="https://example.test/issue/41",
        state="open",
        labels=["blocker"],
    )
    signals = detect_signals(_venture([item]))
    assert any(s.flag == "delivery_risk" for s in signals)


def test_failing_workflow_flags_ci_unhealthy() -> None:
    item = EvidenceItem(
        source_type="workflow_run",
        venture="V",
        repo="o/r",
        title="ci",
        url="https://example.test/run/9",
        state="failure",
    )
    signals = detect_signals(_venture([item]))
    assert any(s.flag == "ci_unhealthy" for s in signals)


def test_low_activity_when_no_merged_prs_and_few_commits() -> None:
    signals = detect_signals(_venture([]))
    assert any(s.flag == "low_activity" for s in signals)


def test_confidence_high_with_merged_pr_and_no_signals() -> None:
    merged = EvidenceItem(
        source_type="pull_request",
        venture="V",
        repo="o/r",
        title="Ship X",
        url="https://example.test/pr/3",
        state="merged",
        raw_metadata={"number": 3},
    )
    commits = [
        EvidenceItem(
            source_type="commit",
            venture="V",
            repo="o/r",
            title=f"c{i}",
            url=f"https://example.test/c/{i}",
        )
        for i in range(5)
    ]
    snapshot = _venture([merged, *commits])
    snapshot.signals = detect_signals(snapshot)
    assert compute_confidence(snapshot) == "High"


def test_confidence_low_when_high_risk_flag_present() -> None:
    blocker = EvidenceItem(
        source_type="issue",
        venture="V",
        repo="o/r",
        title="bad",
        url="https://example.test/i/1",
        state="open",
        labels=["blocker"],
    )
    snapshot = _venture([blocker])
    snapshot.signals = detect_signals(snapshot)
    assert compute_confidence(snapshot) == "Low"
