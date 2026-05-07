"""Tests for the `report` and `collect` CLI commands.

These exercise the full Typer commands with the LLM and GitHub
collector replaced by stubs, so the suite never reaches the network.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

import orbit.cli as cli
from orbit.cli import app
from orbit.fixtures import save_fixture
from orbit.llm import LLMError
from orbit.models import EvidenceItem, StudioSnapshot, VentureSnapshot

runner = CliRunner(env={"COLUMNS": "160"})


# --- helpers ----------------------------------------------------------------


def _snapshot() -> StudioSnapshot:
    return StudioSnapshot(
        studio_name="Orbital Ventures",
        period="7d",
        generated_at=datetime.now(timezone.utc),
        ventures=[
            VentureSnapshot(
                id="atlas-logistics",
                name="Atlas Logistics",
                repos=["orbital-ventures/atlas-router"],
                evidence=[
                    EvidenceItem(
                        source_type="pull_request",
                        venture="Atlas Logistics",
                        repo="orbital-ventures/atlas-router",
                        title="Bidirectional Dijkstra",
                        url="https://github.com/orbital-ventures/atlas-router/pull/88",
                        state="merged",
                        raw_metadata={"number": 88},
                    )
                ],
            )
        ],
    )


def _fixture_path(tmp_path: Path) -> Path:
    path = tmp_path / "snap.json"
    save_fixture(_snapshot(), path)
    return path


# --- report: argument validation --------------------------------------------


def test_report_unknown_audience_exits(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["report", "marketing", "--fixture", str(_fixture_path(tmp_path))]
    )
    assert result.exit_code == 1
    assert "Unknown audience" in (result.stderr or result.output)


def test_report_founder_without_venture_exits(tmp_path: Path) -> None:
    # `render_report` itself enforces that founder reports get a venture; it
    # raises LLMError before touching OpenAI, so no monkeypatch is needed.
    result = runner.invoke(
        app, ["report", "founder", "--fixture", str(_fixture_path(tmp_path))]
    )
    assert result.exit_code == 1
    assert "Founder reports require" in (result.stderr or result.output)


def test_report_missing_fixture_exits(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["report", "engineering", "--fixture", str(tmp_path / "absent.json")],
    )
    assert result.exit_code == 1


# --- report: success paths ---------------------------------------------------


def test_report_engineering_writes_to_output_file(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def fake_render(snapshot, audience, *, venture=None, model=None):  # type: ignore[no-untyped-def]
        captured["audience"] = audience
        captured["studio"] = snapshot.studio_name
        captured["venture"] = venture
        return "# Report\n\nBody."

    monkeypatch.setattr(cli, "render_report", fake_render)

    output = tmp_path / "out" / "report.md"
    result = runner.invoke(
        app,
        [
            "report",
            "engineering",
            "--fixture",
            str(_fixture_path(tmp_path)),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert output.read_text(encoding="utf-8") == "# Report\n\nBody."
    assert captured == {
        "audience": "engineering",
        "studio": "Orbital Ventures",
        "venture": None,
    }


def test_report_founder_passes_venture_to_renderer(monkeypatch, tmp_path: Path) -> None:
    seen_venture: dict[str, Any] = {}

    def fake_render(snapshot, audience, *, venture=None, model=None):  # type: ignore[no-untyped-def]
        seen_venture["venture"] = venture
        return "## Founder update\n"

    monkeypatch.setattr(cli, "render_report", fake_render)

    result = runner.invoke(
        app,
        [
            "report",
            "founder",
            "--venture",
            "atlas-logistics",
            "--fixture",
            str(_fixture_path(tmp_path)),
            "--raw",
        ],
    )

    assert result.exit_code == 0, result.output
    assert seen_venture["venture"] == "atlas-logistics"
    assert "Founder update" in result.output


def test_report_surfaces_llm_errors_cleanly(monkeypatch, tmp_path: Path) -> None:
    def boom(*_a, **_k):  # type: ignore[no-untyped-def]
        raise LLMError("LLM request failed: invalid api key")

    monkeypatch.setattr(cli, "render_report", boom)

    result = runner.invoke(
        app,
        ["report", "leadership", "--fixture", str(_fixture_path(tmp_path))],
    )

    assert result.exit_code == 1
    assert "invalid api key" in (result.stderr or result.output)


# --- collect ----------------------------------------------------------------


def test_collect_writes_snapshot_with_venture_count(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    config_path.write_text(
        """
studio:
  name: Orbital Ventures
ventures:
  - id: atlas-logistics
    name: Atlas Logistics
    repos:
      - orbital-ventures/atlas-router
defaults:
  period: 7d
""",
        encoding="utf-8",
    )

    async def fake_collect(config, *, period=None):  # type: ignore[no-untyped-def]
        return _snapshot()

    monkeypatch.setattr(cli, "collect", fake_collect)

    output = tmp_path / "out.json"
    result = runner.invoke(
        app,
        ["collect", "--config", str(config_path), "-o", str(output), "--period", "7d"],
    )

    assert result.exit_code == 0, result.output
    assert output.exists()
    assert "(1 ventures)" in result.output


def test_collect_surfaces_collector_errors(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    config_path.write_text(
        """
studio:
  name: Orbital Ventures
ventures:
  - id: atlas-logistics
    name: Atlas Logistics
    repos:
      - orbital-ventures/atlas-router
defaults:
  period: 7d
""",
        encoding="utf-8",
    )

    async def boom(config, *, period=None):  # type: ignore[no-untyped-def]
        raise RuntimeError("GITHUB_TOKEN is required")

    monkeypatch.setattr(cli, "collect", boom)

    result = runner.invoke(
        app,
        ["collect", "--config", str(config_path), "-o", str(tmp_path / "out.json")],
    )
    assert result.exit_code == 1
    assert "GITHUB_TOKEN" in (result.stderr or result.output)
