from datetime import datetime, timezone
from pathlib import Path

from orbit.fixtures import load_fixture, save_fixture
from orbit.models import EvidenceItem, StudioSnapshot, VentureSnapshot
from orbit.reporter import annotate_snapshot


def test_round_trip_fixture(tmp_path: Path) -> None:
    snapshot = StudioSnapshot(
        studio_name="Orbital Ventures",
        period="7d",
        generated_at=datetime.now(timezone.utc),
        ventures=[
            VentureSnapshot(
                id="helios-health",
                name="Helios Health",
                repos=["orbital-ventures/helios-api"],
                evidence=[
                    EvidenceItem(
                        source_type="pull_request",
                        venture="Helios Health",
                        repo="orbital-ventures/helios-api",
                        title="Implement audit log retention policy",
                        url="https://github.com/orbital-ventures/helios-api/pull/1",
                        state="merged",
                        raw_metadata={"number": 1},
                    )
                ],
            )
        ],
    )
    annotate_snapshot(snapshot)
    path = tmp_path / "snap.json"
    save_fixture(snapshot, path)
    restored = load_fixture(path)
    assert restored.studio_name == snapshot.studio_name
    assert restored.ventures[0].confidence == "High"
