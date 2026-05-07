from __future__ import annotations

from orbit.models import Confidence, VentureSnapshot


HIGH_RISK_FLAGS = frozenset({"delivery_risk", "ci_unhealthy", "low_activity"})


def compute_confidence(snapshot: VentureSnapshot) -> Confidence:
    flags = {s.flag for s in snapshot.signals}

    if flags & HIGH_RISK_FLAGS:
        return "Low"
    if not flags and snapshot.merged_pr_count >= 1:
        return "High"
    return "Medium"
