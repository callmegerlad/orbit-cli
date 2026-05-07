from __future__ import annotations

import json
from pathlib import Path

from orbit.models import StudioSnapshot


def load_fixture(path: Path) -> StudioSnapshot:
    """Load a previously saved StudioSnapshot from JSON."""
    if not path.exists():
        raise FileNotFoundError(f"Fixture not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return StudioSnapshot.model_validate(raw)


def save_fixture(snapshot: StudioSnapshot, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
