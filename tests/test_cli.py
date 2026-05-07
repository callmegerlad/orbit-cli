from pathlib import Path

from typer.testing import CliRunner

import orbit.cli as cli
from orbit.cli import app
from orbit.config import load_config

runner = CliRunner(env={"COLUMNS": "160"})


def _write_config(path: Path) -> None:
    path.write_text(
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


def test_venture_add_updates_config(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _write_config(config_path)

    result = runner.invoke(
        app,
        [
            "venture",
            "add",
            "--config",
            str(config_path),
            "--name",
            "Helios Health",
            "--id",
            "helios",
            "--repo",
            "orbital-ventures/helios-api",
            "--milestone",
            "Beta launch",
            "--watch-item",
            "patient onboarding",
        ],
    )

    assert result.exit_code == 0
    config = load_config(config_path)
    venture = config.venture("helios")
    assert venture.name == "Helios Health"
    assert venture.repos == ["orbital-ventures/helios-api"]
    assert venture.milestone == "Beta launch"
    assert venture.watch_items == ["patient onboarding"]


def test_venture_update_replaces_milestone_and_watch_items(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _write_config(config_path)

    result = runner.invoke(
        app,
        [
            "venture",
            "update",
            "atlas-logistics",
            "--config",
            str(config_path),
            "--milestone",
            "Pilot launch",
            "--watch-item",
            "saved events",
            "--watch-item",
            "notifications",
        ],
    )

    assert result.exit_code == 0
    venture = load_config(config_path).venture("atlas-logistics")
    assert venture.milestone == "Pilot launch"
    assert venture.watch_items == ["saved events", "notifications"]


def test_settings_studio_updates_name(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _write_config(config_path)

    result = runner.invoke(
        app,
        ["settings", "studio", "--config", str(config_path), "--name", "New Studio"],
    )

    assert result.exit_code == 0
    assert load_config(config_path).studio.name == "New Studio"


def test_settings_defaults_updates_period_and_github_user(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _write_config(config_path)

    result = runner.invoke(
        app,
        [
            "settings",
            "defaults",
            "--config",
            str(config_path),
            "--period",
            "24h",
            "--github-user",
            "studio-bot",
        ],
    )

    assert result.exit_code == 0
    config = load_config(config_path)
    assert config.defaults.period == "24h"
    assert config.defaults.github_user == "studio-bot"


def test_settings_defaults_guided(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _write_config(config_path)

    result = runner.invoke(
        app,
        ["settings", "defaults", "--config", str(config_path)],
        input="24h\nstudio-bot\n",
    )

    assert result.exit_code == 0
    config = load_config(config_path)
    assert config.defaults.period == "24h"
    assert config.defaults.github_user == "studio-bot"


def test_init_can_add_multiple_ventures(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"

    result = runner.invoke(
        app,
        ["init", "--config", str(config_path)],
        input=(
            "Orbital\n"
            "7d\n"
            "\n"
            "Atlas Logistics\n"
            "\n"
            "orbital-ventures/atlas-router\n"
            "\n"
            "Beta launch\n"
            "saved events\n"
            "\n"
            "y\n"
            "Helios Health\n"
            "helios\n"
            "orbital-ventures/helios-api\n"
            "\n"
            "Pilot launch\n"
            "onboarding\n"
            "staging stability\n"
            "\n"
            "n\n"
        ),
    )

    assert result.exit_code == 0
    config = load_config(config_path)
    assert [venture.id for venture in config.ventures] == ["atlas-logistics", "helios"]
    assert [venture.name for venture in config.ventures] == ["Atlas Logistics", "Helios Health"]
    assert config.venture("helios").watch_items == [
        "onboarding",
        "staging stability",
    ]


def test_venture_update_can_select_interactively(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _write_config(config_path)

    result = runner.invoke(
        app,
        [
            "venture",
            "update",
            "--config",
            str(config_path),
            "--milestone",
            "Interactive launch",
        ],
        input="1\n",
    )

    assert result.exit_code == 0
    assert load_config(config_path).venture("atlas-logistics").milestone == "Interactive launch"


def test_venture_update_guided_keeps_defaults_and_updates_watch_items(tmp_path: Path) -> None:
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
    stakeholder: Marco
    milestone: Beta launch
    watch_items:
      - saved events
defaults:
  period: 7d
""",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["venture", "update", "atlas-logistics", "--config", str(config_path)],
        input=("\n\nPilot launch\nn\nnotifications\nstaging stability\n\n"),
    )

    assert result.exit_code == 0
    venture = load_config(config_path).venture("atlas-logistics")
    assert venture.repos == ["orbital-ventures/atlas-router"]
    assert venture.stakeholder == "Marco"
    assert venture.milestone == "Pilot launch"
    assert venture.watch_items == ["notifications", "staging stability"]


def test_validate_displays_summary_and_warnings(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _write_config(config_path)

    result = runner.invoke(
        app,
        ["validate", "--config", str(config_path)],
        env={"GITHUB_TOKEN": ""},
    )

    assert result.exit_code == 0
    assert "Orbit config is valid" in result.output
    assert "Configured ventures" in result.output
    assert "atlas-logistics" in result.output
    assert "milestone is not set" in result.output
    assert "watch items are not set" in result.output
    assert "missing GITHUB_TOKEN" in result.output
    assert "not fully ready yet" in result.output


def test_validate_reports_ready_config_without_warnings(tmp_path: Path) -> None:
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
    stakeholder: Marco
    milestone: Beta launch
    watch_items:
      - saved events
defaults:
  period: 7d
  github_user: orbital-bot
""",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["validate", "--config", str(config_path)],
        env={"GITHUB_TOKEN": ""},
    )

    assert result.exit_code == 0
    assert "No warnings found" in result.output
    assert "Beta launch" not in result.output
    assert "saved events" not in result.output
    assert "not fully ready yet" in result.output


def test_venture_list_uses_compact_table(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _write_config(config_path)

    result = runner.invoke(app, ["venture", "list", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "Configured ventures" in result.output
    assert "atlas-logistics" in result.output
    assert "orbital-ventures/atlas-router" in result.output
    assert "Milestone" not in result.output
    assert "Watch items" not in result.output


def test_venture_details_shows_milestones_and_watch_items(tmp_path: Path) -> None:
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
    milestone: Beta launch
    watch_items:
      - saved events
defaults:
  period: 7d
""",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["venture", "details", "--config", str(config_path), "--venture", "atlas-logistics"],
    )

    assert result.exit_code == 0
    assert "Venture details for Atlas Logistics" in result.output
    assert "orbital-ventures/atlas-router" in result.output
    assert "Beta launch" in result.output
    assert "saved events" in result.output


def test_venture_details_can_select_interactively(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _write_config(config_path)

    result = runner.invoke(
        app,
        ["venture", "details", "--config", str(config_path)],
        input="1\n",
    )

    assert result.exit_code == 0
    assert "Venture details for Atlas Logistics" in result.output


def test_validate_github_reports_missing_token(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _write_config(config_path)

    result = runner.invoke(
        app,
        ["validate", "--config", str(config_path)],
        env={"GITHUB_TOKEN": ""},
    )

    assert result.exit_code == 0
    assert "missing GITHUB_TOKEN" in result.output


def test_validate_github_reports_success(monkeypatch, tmp_path: Path) -> None:
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
    stakeholder: Marco
    milestone: Beta launch
    watch_items:
      - saved events
defaults:
  period: 7d
""",
        encoding="utf-8",
    )

    async def fake_github_checks(config, token):
        return "orbital-bot", []

    monkeypatch.setattr(cli, "_github_checks", fake_github_checks)
    result = runner.invoke(
        app,
        ["validate", "--config", str(config_path)],
        env={"GITHUB_TOKEN": "token"},
    )

    assert result.exit_code == 0
    assert "GitHub token works for @orbital-bot" in result.output
    assert "Orbit is ready to launch with this config" in result.output


def test_github_permission_hints_from_failed_endpoints() -> None:
    failures = [
        "orbital-ventures/atlas-router: pull requests failed: missing token permission",
        "orbital-ventures/atlas-router: issues failed: missing token permission",
        "orbital-ventures/atlas-router: actions workflow runs failed: missing token permission",
    ]

    assert cli._github_permission_hints(failures) == [
        "Pull requests: Read-only",
        "Issues: Read-only",
        "Actions: Read-only",
    ]


def test_validate_groups_permission_hints(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _write_config(config_path)

    async def fake_github_checks(config, token):
        return "orbital-bot", [
            "orbital-ventures/atlas-router: pull requests failed: missing token permission",
            "orbital-ventures/atlas-router: issues failed: missing token permission",
        ]

    monkeypatch.setattr(cli, "_github_checks", fake_github_checks)
    result = runner.invoke(
        app,
        ["validate", "--config", str(config_path)],
        env={"GITHUB_TOKEN": "token"},
    )

    assert result.exit_code == 0
    assert "GitHub token check failed for @orbital-bot" in result.output
    assert "Fine-grained PAT permission checklist" in result.output
    assert "Pull requests: Read-only" in result.output
    assert "◻ Pull requests: Read-only" in result.output
    assert "☑ Contents: Read-only" in result.output


# --- Top-level CLI surface ---------------------------------------------------


def test_version_flag_prints_version_and_exits() -> None:
    from orbit import __version__

    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_lists_top_level_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("init", "validate", "collect", "report", "venture"):
        assert cmd in result.output


def test_venture_help_lists_subcommands() -> None:
    result = runner.invoke(app, ["venture", "--help"])
    assert result.exit_code == 0
    for sub in ("add", "update", "remove", "list", "details"):
        assert sub in result.output


# --- Config error paths ------------------------------------------------------


def test_validate_exits_on_missing_config(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.yaml"
    result = runner.invoke(app, ["validate", "--config", str(missing)])
    assert result.exit_code == 1
    assert "not found" in (result.stderr or result.output).lower()


def test_validate_exits_on_invalid_yaml(tmp_path: Path) -> None:
    bad = tmp_path / "orbit.yaml"
    bad.write_text(": not valid yaml :\n  - foo\n", encoding="utf-8")

    result = runner.invoke(app, ["validate", "--config", str(bad)])
    assert result.exit_code == 1
    combined = (result.stderr or "") + result.output
    assert "Failed to parse" in combined or "Invalid config" in combined


def test_venture_list_exits_when_config_missing(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    result = runner.invoke(app, ["venture", "list", "--config", str(missing)])
    assert result.exit_code == 1


# --- init: overwrite protection ----------------------------------------------


def test_init_refuses_to_overwrite_existing_config(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _write_config(config_path)
    original = config_path.read_text(encoding="utf-8")

    result = runner.invoke(app, ["init", "--config", str(config_path)])

    assert result.exit_code == 1
    assert config_path.read_text(encoding="utf-8") == original


def test_init_force_overwrites_existing_config(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _write_config(config_path)

    result = runner.invoke(
        app,
        ["init", "--config", str(config_path), "--force"],
        input=(
            "Northwind\n"
            "7d\n"
            "\n"
            "Helios Health\n"
            "\n"
            "orbital-ventures/helios-api\n"
            "\n"
            "HIPAA pilot\n"
            "patient onboarding\n"
            "\n"
            "n\n"
        ),
    )

    assert result.exit_code == 0
    config = load_config(config_path)
    assert config.studio.name == "Northwind"
    assert [v.id for v in config.ventures] == ["helios-health"]


# --- venture add error paths -------------------------------------------------


def test_venture_add_rejects_invalid_repo_format(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _write_config(config_path)

    result = runner.invoke(
        app,
        [
            "venture",
            "add",
            "--config",
            str(config_path),
            "--name",
            "Bad",
            "--id",
            "bad",
            "--repo",
            "not-a-repo",
        ],
    )

    assert result.exit_code == 1
    # The original config must be untouched.
    assert load_config(config_path).venture("atlas-logistics") is not None


def test_venture_add_rejects_duplicate_id(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _write_config(config_path)

    result = runner.invoke(
        app,
        [
            "venture",
            "add",
            "--config",
            str(config_path),
            "--name",
            "Duplicate",
            "--id",
            "atlas-logistics",  # already exists
            "--repo",
            "orbital-ventures/duplicate",
        ],
    )

    assert result.exit_code == 1
    config = load_config(config_path)
    assert len(config.ventures) == 1


# --- venture update error paths ----------------------------------------------


def test_venture_update_unknown_ref_exits(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _write_config(config_path)

    result = runner.invoke(
        app,
        [
            "venture",
            "update",
            "no-such-venture",
            "--config",
            str(config_path),
            "--milestone",
            "Whatever",
        ],
    )

    assert result.exit_code == 1


# --- venture remove ----------------------------------------------------------


def _two_venture_config(path: Path) -> None:
    path.write_text(
        """
studio:
  name: Orbital Ventures
ventures:
  - id: helios-health
    name: Helios Health
    repos:
      - orbital-ventures/helios-api
  - id: atlas-logistics
    name: Atlas Logistics
    repos:
      - orbital-ventures/atlas-router
defaults:
  period: 7d
""",
        encoding="utf-8",
    )


def test_venture_remove_by_id_persists_change(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _two_venture_config(config_path)

    result = runner.invoke(
        app, ["venture", "remove", "atlas-logistics", "--config", str(config_path)]
    )

    assert result.exit_code == 0
    config = load_config(config_path)
    assert [v.id for v in config.ventures] == ["helios-health"]


def test_venture_remove_supports_interactive_selection(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _two_venture_config(config_path)

    result = runner.invoke(
        app,
        ["venture", "remove", "--config", str(config_path)],
        input="2\n",  # remove the second listed venture
    )

    assert result.exit_code == 0
    remaining = [v.id for v in load_config(config_path).ventures]
    assert remaining == ["helios-health"]


def test_venture_remove_unknown_ref_exits(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _write_config(config_path)

    result = runner.invoke(
        app, ["venture", "remove", "no-such-venture", "--config", str(config_path)]
    )

    assert result.exit_code == 1


def test_venture_remove_refuses_when_only_one_venture_left(tmp_path: Path) -> None:
    """Configs require at least one venture, so removing the last must fail."""
    config_path = tmp_path / "orbit.yaml"
    _write_config(config_path)

    result = runner.invoke(
        app, ["venture", "remove", "atlas-logistics", "--config", str(config_path)]
    )

    assert result.exit_code == 1
    # Config still parses with the single venture intact.
    assert len(load_config(config_path).ventures) == 1


# --- _select_venture cancel path --------------------------------------------


def test_venture_update_interactive_cancel_with_zero(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _write_config(config_path)

    result = runner.invoke(
        app,
        [
            "venture",
            "update",
            "--config",
            str(config_path),
            "--milestone",
            "Will not be applied",
        ],
        input="0\n",
    )

    # Cancel exits cleanly (code 0) without writing changes.
    assert result.exit_code == 0
    assert load_config(config_path).venture("atlas-logistics").milestone is None


# --- venture details ---------------------------------------------------------


def test_venture_details_unknown_ref_exits(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _write_config(config_path)

    result = runner.invoke(
        app,
        ["venture", "details", "--config", str(config_path), "--venture", "missing"],
    )

    assert result.exit_code == 1


# --- orbit me ----------------------------------------------------------------


def _config_with_github_user(path: Path) -> None:
    path.write_text(
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
  github_user: avery
""",
        encoding="utf-8",
    )


def _me_fixture(tmp_path: Path) -> Path:
    """Snapshot fixture with one PR + one commit by `avery`, plus a quiet venture."""
    from datetime import datetime, timezone

    from orbit.fixtures import save_fixture
    from orbit.models import EvidenceItem, StudioSnapshot, VentureSnapshot

    snap = StudioSnapshot(
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
                        author="avery",
                        state="merged",
                        raw_metadata={"number": 88, "comments": 0, "review_comments": 0},
                    ),
                    EvidenceItem(
                        source_type="commit",
                        venture="Atlas Logistics",
                        repo="orbital-ventures/atlas-router",
                        title="Cache traffic tiles",
                        url="https://github.com/orbital-ventures/atlas-router/commit/abc1234",
                        author="avery",
                        raw_metadata={"sha": "abc1234"},
                    ),
                ],
            ),
            VentureSnapshot(
                id="lumen-edu",
                name="Lumen Edu",
                repos=["orbital-ventures/lumen-classroom"],
                evidence=[],
            ),
        ],
    )
    fixture_path = tmp_path / "snap.json"
    save_fixture(snap, fixture_path)
    return fixture_path


def test_me_uses_github_user_from_config(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _config_with_github_user(config_path)

    result = runner.invoke(
        app,
        ["me", "--config", str(config_path), "--fixture", str(_me_fixture(tmp_path))],
    )

    assert result.exit_code == 0, result.output
    assert "Activity for @avery" in result.output
    assert "Atlas Logistics" in result.output
    assert "Lumen Edu" in result.output
    assert "no activity in this period" in result.output


def test_me_user_flag_overrides_config(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _config_with_github_user(config_path)

    result = runner.invoke(
        app,
        [
            "me",
            "--user",
            "someone-else",
            "--config",
            str(config_path),
            "--fixture",
            str(_me_fixture(tmp_path)),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Activity for @someone-else" in result.output
    # The fixture's PRs are by 'avery', so someone-else has no activity anywhere.
    assert "no activity in this period" in result.output


def test_me_errors_when_user_unresolved_and_using_fixture(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _write_config(config_path)  # default config has no github_user

    result = runner.invoke(
        app,
        ["me", "--config", str(config_path), "--fixture", str(_me_fixture(tmp_path))],
    )

    assert result.exit_code == 1
    assert "No GitHub user" in (result.stderr or result.output)


def test_me_filters_to_csv_venture_ids(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _config_with_github_user(config_path)

    result = runner.invoke(
        app,
        [
            "me",
            "--config", str(config_path),
            "--fixture", str(_me_fixture(tmp_path)),
            "--venture", "atlas-logistics",  # only one of the two fixture ventures
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Atlas Logistics" in result.output
    assert "Lumen Edu" not in result.output


def test_me_accepts_repeated_and_csv_venture_flags(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _config_with_github_user(config_path)

    # Pass one venture as a repeated flag and one inside a comma-separated value.
    result = runner.invoke(
        app,
        [
            "me",
            "--config", str(config_path),
            "--fixture", str(_me_fixture(tmp_path)),
            "--venture", "atlas-logistics,lumen-edu",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Atlas Logistics" in result.output
    assert "Lumen Edu" in result.output


# --- orbit catchup -----------------------------------------------------------


def _catchup_fixture(tmp_path: Path) -> Path:
    from datetime import datetime, timezone

    from orbit.fixtures import save_fixture
    from orbit.models import EvidenceItem, StudioSnapshot, VentureSnapshot

    snap = StudioSnapshot(
        studio_name="Orbital Ventures",
        period="7d",
        generated_at=datetime.now(timezone.utc),
        ventures=[
            VentureSnapshot(
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
                ],
            ),
            VentureSnapshot(
                id="lumen-edu",
                name="Lumen Edu",
                repos=["orbital-ventures/lumen-classroom"],
                evidence=[],
            ),
        ],
    )
    fixture_path = tmp_path / "snap.json"
    save_fixture(snap, fixture_path)
    return fixture_path


def test_catchup_calls_llm_per_venture_and_prints_each(
    monkeypatch: "object", tmp_path: Path
) -> None:
    config_path = tmp_path / "orbit.yaml"
    _config_with_github_user(config_path)

    seen: list[str] = []

    def fake_render(ctx, *, model=None):  # type: ignore[no-untyped-def]
        seen.append(ctx.venture_name)
        return f"  - changes summary for {ctx.venture_name}\n"

    monkeypatch.setattr(cli, "render_catchup", fake_render)

    result = runner.invoke(
        app,
        [
            "catchup",
            "--config", str(config_path),
            "--fixture", str(_catchup_fixture(tmp_path)),
            "--venture", "consumer-app,lumen-edu",
        ],
    )

    assert result.exit_code == 0, result.output
    assert seen == ["Consumer App", "Lumen Edu"]
    assert "Consumer App" in result.output
    assert "changes summary for Consumer App" in result.output
    assert "Lumen Edu" in result.output


def test_catchup_requires_at_least_one_venture(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _config_with_github_user(config_path)

    result = runner.invoke(
        app,
        [
            "catchup",
            "--config", str(config_path),
            "--fixture", str(_catchup_fixture(tmp_path)),
        ],
    )

    assert result.exit_code == 1
    assert "at least one venture" in (result.stderr or result.output)


def test_catchup_unknown_venture_exits_with_clean_error(
    monkeypatch: "object", tmp_path: Path
) -> None:
    config_path = tmp_path / "orbit.yaml"
    _config_with_github_user(config_path)

    monkeypatch.setattr(cli, "render_catchup", lambda *_a, **_k: "should not run")

    result = runner.invoke(
        app,
        [
            "catchup",
            "--config", str(config_path),
            "--fixture", str(_catchup_fixture(tmp_path)),
            "--venture", "no-such-venture",
        ],
    )

    assert result.exit_code == 1
    assert "no-such-venture" in (result.stderr or result.output)


# --- orbit status ------------------------------------------------------------


def _status_fixture(tmp_path: Path) -> Path:
    from datetime import datetime, timezone

    from orbit.fixtures import save_fixture
    from orbit.models import EvidenceItem, RiskSignal, StudioSnapshot, VentureSnapshot

    snap = StudioSnapshot(
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
                        title="Add live ETA column",
                        url="https://github.com/orbital-ventures/atlas-router/pull/56",
                        author="devi",
                        state="open",
                        raw_metadata={"number": 56, "draft": False},
                    ),
                ],
                signals=[
                    RiskSignal(
                        flag="review_backlog",
                        venture="Atlas Logistics",
                        repo="orbital-ventures/atlas-router",
                        reason="open >2 days",
                        evidence_urls=[],
                    )
                ],
            ),
            VentureSnapshot(
                id="lumen-edu",
                name="Lumen Edu",
                repos=["orbital-ventures/lumen-classroom"],
                evidence=[],
            ),
        ],
    )
    fixture_path = tmp_path / "snap.json"
    save_fixture(snap, fixture_path)
    return fixture_path


def test_status_calls_llm_once_with_all_ventures(monkeypatch: "object", tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _write_config(config_path)

    seen_studios: list[str] = []

    def fake_render(ctx, *, model=None):  # type: ignore[no-untyped-def]
        seen_studios.append(ctx.studio_name)
        names = [v.venture_name for v in ctx.ventures]
        return "\n".join(f"{name}: 0 open PRs, 0 commits" for name in names)

    monkeypatch.setattr(cli, "render_status", fake_render)

    result = runner.invoke(
        app,
        ["status", "--config", str(config_path), "--fixture", str(_status_fixture(tmp_path))],
    )

    assert result.exit_code == 0, result.output
    assert seen_studios == ["Orbital Ventures"]
    assert "Atlas Logistics: 0 open PRs" in result.output
    assert "Lumen Edu: 0 open PRs" in result.output


def test_status_filters_to_specified_ventures(monkeypatch: "object", tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _write_config(config_path)

    seen_names: list[list[str]] = []

    def fake_render(ctx, *, model=None):  # type: ignore[no-untyped-def]
        seen_names.append([v.venture_name for v in ctx.ventures])
        return "ok"

    monkeypatch.setattr(cli, "render_status", fake_render)

    result = runner.invoke(
        app,
        [
            "status",
            "--config", str(config_path),
            "--fixture", str(_status_fixture(tmp_path)),
            "--venture", "atlas-logistics",
        ],
    )

    assert result.exit_code == 0, result.output
    assert seen_names == [["Atlas Logistics"]]


def test_status_unknown_venture_exits_with_clean_error(
    monkeypatch: "object", tmp_path: Path
) -> None:
    config_path = tmp_path / "orbit.yaml"
    _write_config(config_path)

    monkeypatch.setattr(cli, "render_status", lambda *_a, **_k: "should not run")

    result = runner.invoke(
        app,
        [
            "status",
            "--config", str(config_path),
            "--fixture", str(_status_fixture(tmp_path)),
            "--venture", "no-such-venture",
        ],
    )

    assert result.exit_code == 1
    assert "no-such-venture" in (result.stderr or result.output)


def test_status_surfaces_llm_errors(monkeypatch: "object", tmp_path: Path) -> None:
    from orbit.llm import LLMError

    config_path = tmp_path / "orbit.yaml"
    _write_config(config_path)

    def boom(*_a, **_k):  # type: ignore[no-untyped-def]
        raise LLMError("LLM request failed: invalid api key")

    monkeypatch.setattr(cli, "render_status", boom)

    result = runner.invoke(
        app,
        ["status", "--config", str(config_path), "--fixture", str(_status_fixture(tmp_path))],
    )

    assert result.exit_code == 1
    assert "invalid api key" in (result.stderr or result.output)


def test_catchup_surfaces_llm_errors(monkeypatch: "object", tmp_path: Path) -> None:
    from orbit.llm import LLMError

    config_path = tmp_path / "orbit.yaml"
    _config_with_github_user(config_path)

    def boom(*_a, **_k):  # type: ignore[no-untyped-def]
        raise LLMError("LLM request failed: invalid api key")

    monkeypatch.setattr(cli, "render_catchup", boom)

    result = runner.invoke(
        app,
        [
            "catchup",
            "--config", str(config_path),
            "--fixture", str(_catchup_fixture(tmp_path)),
            "--venture", "consumer-app",
        ],
    )

    assert result.exit_code == 1
    assert "invalid api key" in (result.stderr or result.output)


def test_me_unknown_venture_exits_with_clean_error(tmp_path: Path) -> None:
    config_path = tmp_path / "orbit.yaml"
    _config_with_github_user(config_path)

    result = runner.invoke(
        app,
        [
            "me",
            "--config", str(config_path),
            "--fixture", str(_me_fixture(tmp_path)),
            "--venture", "atlas-logistics,no-such-venture",
        ],
    )

    assert result.exit_code == 1
    assert "no-such-venture" in (result.stderr or result.output)
