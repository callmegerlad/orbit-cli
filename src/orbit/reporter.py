from __future__ import annotations

from orbit.confidence import compute_confidence
from orbit.models import StudioSnapshot
from orbit.risk import detect_signals


def annotate_snapshot(snapshot: StudioSnapshot) -> StudioSnapshot:
    """Populate per-venture signals and confidence levels in-place."""
    for v in snapshot.ventures:
        v.signals = detect_signals(v)
        v.confidence = compute_confidence(v)
    return snapshot
