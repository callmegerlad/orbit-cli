from datetime import UTC, datetime

from orbit.llm import (
    _catchup_payload,
    _load_catchup_prompt,
    _load_status_prompt,
    _status_payload,
    _venture_payload,
    load_prompt,
)
from orbit.models import EvidenceItem, StudioSnapshot, VentureSnapshot
from orbit.query import build_catchup, build_status


def test_load_prompt_includes_shared_metadata_instructions() -> None:
    prompt = load_prompt("engineering")

    assert "Standard report metadata block" in prompt
    assert "engineering lead report" in prompt


def test_venture_payload_adds_readable_commit_citation() -> None:
    venture = VentureSnapshot(
        name="Atlas Logistics",
        evidence=[
            EvidenceItem(
                source_type="commit",
                venture="Atlas Logistics",
                repo="orbital-ventures/atlas-router",
                title="Cache traffic tiles for 60s to reduce Mapbox spend",
                url="https://github.com/orbital-ventures/atlas-router/commit/7e6400bc",
                created_at=datetime.now(UTC),
                raw_metadata={"sha": "7e6400bcbe095104a5ab4473559a6e6f4d3ee6e2"},
            )
        ],
    )

    payload = _venture_payload(venture)

    citation = payload["evidence"][0]["citation"]
    assert citation["text"] == "`7e6400b`"
    assert citation["label"] == "commit-7e6400b"
    assert citation["markdown"] == "[`7e6400b`][commit-7e6400b]"
    assert citation["definition"] == (
        "[commit-7e6400b]: https://github.com/orbital-ventures/atlas-router/commit/7e6400bc"
    )


# --- catchup ---------------------------------------------------------------


def _catchup_snapshot() -> StudioSnapshot:
    venture = VentureSnapshot(
        id="consumer-app",
        name="Consumer App",
        repos=["orbital-ventures/consumer-web"],
        evidence=[
            EvidenceItem(
                source_type="pull_request",
                venture="Consumer App",
                repo="orbital-ventures/consumer-web",
                title="Migrate auth from JWT to session-based",
                url="https://github.com/orbital-ventures/consumer-web/pull/22",
                author="wei-lin",
                state="merged",
                raw_metadata={"number": 22},
            ),
            EvidenceItem(
                source_type="pull_request",
                venture="Consumer App",
                repo="orbital-ventures/consumer-web",
                title="User profile flow refresh",
                url="https://github.com/orbital-ventures/consumer-web/pull/18",
                author="me",
                state="open",
                raw_metadata={"number": 18},
            ),
        ],
    )
    return StudioSnapshot(
        studio_name="Orbital Ventures",
        period="7d",
        generated_at=datetime.now(UTC),
        ventures=[venture],
    )


def test_catchup_payload_separates_others_from_users_open_work() -> None:
    ctx = build_catchup(_catchup_snapshot(), user="me", venture_ref="consumer-app")

    payload = _catchup_payload(ctx)

    assert payload["venture"]["id"] == "consumer-app"
    assert payload["user"] == "me"
    assert payload["stats"]["merged_prs"] == 1
    others = [item["raw_metadata"]["number"] for item in payload["changes_by_others"]]
    assert others == [22]
    yours = [item["raw_metadata"]["number"] for item in payload["your_open_work"]]
    assert yours == [18]


def test_catchup_prompt_template_loads_with_required_rules() -> None:
    prompt = _load_catchup_prompt()
    assert "catchup brief" in prompt
    assert "plain text" in prompt.lower()
    assert "Heads up" in prompt


# --- status ----------------------------------------------------------------


def test_status_payload_includes_counts_signals_and_open_pr_titles() -> None:
    venture = VentureSnapshot(
        id="atlas",
        name="Atlas",
        repos=["orbital-ventures/atlas-router"],
        evidence=[
            EvidenceItem(
                source_type="pull_request",
                venture="Atlas",
                repo="orbital-ventures/atlas-router",
                title="Add live ETA column",
                url="https://github.com/orbital-ventures/atlas-router/pull/56",
                author="devi",
                state="open",
                raw_metadata={"number": 56, "draft": False},
            )
        ],
    )
    snapshot = StudioSnapshot(
        studio_name="Orbital Ventures",
        period="7d",
        generated_at=datetime.now(UTC),
        ventures=[venture],
    )

    payload = _status_payload(build_status(snapshot))

    assert payload["studio"] == "Orbital Ventures"
    assert payload["period"] == "7d"
    [v] = payload["ventures"]
    assert v["id"] == "atlas"
    assert v["counts"]["open_prs"] == 1
    assert v["counts"]["contributors"] == 1
    assert v["open_pr_titles"] == ["Add live ETA column"]


def test_status_prompt_template_loads_with_required_rules() -> None:
    prompt = _load_status_prompt()
    assert "studio status snapshot" in prompt
    assert "Heads up" in prompt
    assert "deterministic counts" in prompt
