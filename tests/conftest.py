"""Shared pytest fixtures.

Keeps CLI tests free of duplicated YAML and snapshot boilerplate. Any
test that needs a writable on-disk config or an in-memory snapshot
should pull from here rather than rolling its own.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pytest
from typer.testing import CliRunner

from orbit.models import EvidenceItem, StudioSnapshot, VentureSnapshot

DEFAULT_CONFIG_YAML = """
studio:
  name: Orbital Ventures
ventures:
  - id: atlas-logistics
    name: Atlas Logistics
    repos:
      - orbital-ventures/atlas-router
defaults:
  period: 7d
"""

RICH_CONFIG_YAML = """
studio:
  name: Orbital Ventures
ventures:
  - id: helios-health
    name: Helios Health
    repos:
      - orbital-ventures/helios-api
    stakeholder: Priya
    milestone: HIPAA pilot
    watch_items:
      - patient onboarding
  - id: atlas-logistics
    name: Atlas Logistics
    repos:
      - orbital-ventures/atlas-router
    stakeholder: Marco
    milestone: Route optimisation beta
    watch_items:
      - dispatcher UI
defaults:
  period: 7d
  github_user: orbital-bot
"""


@pytest.fixture
def runner() -> CliRunner:
    """A CliRunner with a wide terminal so Rich tables don't truncate."""
    return CliRunner(env={"COLUMNS": "160"})


@pytest.fixture
def write_config(tmp_path: Path) -> Callable[..., Path]:
    """Factory that writes a config YAML and returns its path.

    Usage:
        path = write_config()                        # default single-venture
        path = write_config(content=CUSTOM_YAML)     # custom YAML
        path = write_config(name="custom.yaml")      # custom filename
    """

    def _write(*, content: str = DEFAULT_CONFIG_YAML, name: str = "orbit.yaml") -> Path:
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        return path

    return _write


@pytest.fixture
def snapshot_factory() -> Callable[..., StudioSnapshot]:
    """Build minimal StudioSnapshot objects for report/collect tests."""

    def _make(
        *,
        studio: str = "Orbital Ventures",
        period: str = "7d",
        venture_id: str = "atlas-logistics",
        venture_name: str = "Atlas Logistics",
        repo: str = "orbital-ventures/atlas-router",
    ) -> StudioSnapshot:
        return StudioSnapshot(
            studio_name=studio,
            period=period,
            generated_at=datetime.now(timezone.utc),
            ventures=[
                VentureSnapshot(
                    id=venture_id,
                    name=venture_name,
                    repos=[repo],
                    evidence=[
                        EvidenceItem(
                            source_type="pull_request",
                            venture=venture_name,
                            repo=repo,
                            title="Ship something",
                            url=f"https://github.com/{repo}/pull/1",
                            state="merged",
                            raw_metadata={"number": 1},
                        )
                    ],
                )
            ],
        )

    return _make
