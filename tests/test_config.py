from pathlib import Path

import pytest

from orbit.config import (
    ConfigError,
    VentureConfig,
    add_venture,
    create_config,
    load_config,
    parse_period_to_hours,
    update_defaults,
    update_studio,
    update_venture,
    write_config,
)

VALID = """
studio:
  name: "Orbital Ventures"
ventures:
  - name: "Helios Health"
    repos: ["orbital-ventures/helios-api"]
    milestone: "HIPAA-compliant patient portal pilot"
defaults:
  period: "7d"
"""


def write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "orbit.yaml"
    p.write_text(content)
    return p


def test_loads_valid_config(tmp_path: Path) -> None:
    cfg = load_config(write(tmp_path, VALID))
    assert cfg.studio.name == "Orbital Ventures"
    assert cfg.ventures[0].id == "helios-health"
    assert cfg.ventures[0].repos == ["orbital-ventures/helios-api"]
    assert cfg.defaults.period == "7d"


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.yaml")


def test_invalid_repo_format(tmp_path: Path) -> None:
    bad = VALID.replace("orbital-ventures/helios-api", "not-a-repo")
    with pytest.raises(ConfigError, match="owner/name"):
        load_config(write(tmp_path, bad))


def test_duplicate_venture_names(tmp_path: Path) -> None:
    bad = """
studio:
  name: "Orbital Ventures"
ventures:
  - name: "Helios Health"
    repos: ["orbital-ventures/helios-api"]
  - name: "Helios Health"
    repos: ["orbital-ventures/helios-portal"]
"""
    with pytest.raises(ConfigError, match="Duplicate venture names"):
        load_config(write(tmp_path, bad))


def test_duplicate_venture_ids(tmp_path: Path) -> None:
    bad = """
studio:
  name: "Orbital Ventures"
ventures:
  - id: helios
    name: "Helios Health"
    repos: ["orbital-ventures/helios-api"]
  - id: helios
    name: "Helios Portal"
    repos: ["orbital-ventures/helios-portal"]
"""
    with pytest.raises(ConfigError, match="Duplicate venture ids"):
        load_config(write(tmp_path, bad))


def test_unknown_keys_rejected(tmp_path: Path) -> None:
    bad = VALID + "extra_top_level: true\n"
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, bad))


@pytest.mark.parametrize(
    "period,hours",
    [("7d", 168), ("24h", 24), ("1d", 24), ("2w", 336), ("1w", 168)],
)
def test_parse_period(period: str, hours: int) -> None:
    assert parse_period_to_hours(period) == hours


def test_parse_period_invalid() -> None:
    with pytest.raises(ValueError):
        parse_period_to_hours("week")


def test_write_and_reload_created_config(tmp_path: Path) -> None:
    config = create_config(
        studio_name="Orbital Ventures",
        period="7d",
        github_user="orbital-bot",
        ventures=[
            VentureConfig(
                id="atlas-logistics",
                name="Atlas Logistics",
                repos=["orbital-ventures/atlas-router"],
                milestone="Route optimisation beta with 5 fleet customers",
                watch_items=["dispatcher UI"],
            )
        ],
    )

    path = write_config(config, tmp_path / "orbit.yaml")
    restored = load_config(path)

    assert restored.studio.name == "Orbital Ventures"
    assert restored.defaults.github_user == "orbital-bot"
    assert restored.ventures[0].id == "atlas-logistics"
    assert restored.ventures[0].name == "Atlas Logistics"


def test_add_and_update_venture() -> None:
    config = create_config(
        studio_name="Orbital Ventures",
        ventures=[
            VentureConfig(id="helios", name="Helios Health", repos=["orbital-ventures/helios-api"])
        ],
    )

    config = add_venture(
        config,
        VentureConfig(id="atlas", name="Atlas Logistics", repos=["orbital-ventures/atlas-router"]),
    )
    config = update_venture(
        config,
        "atlas",
        milestone="Route optimisation beta",
        watch_items=["dispatcher UI", "telemetry ingestion"],
    )

    venture = config.venture("atlas")
    assert venture.milestone == "Route optimisation beta"
    assert venture.watch_items == ["dispatcher UI", "telemetry ingestion"]


def test_update_studio_and_defaults() -> None:
    config = create_config(
        studio_name="Orbital Ventures",
        ventures=[VentureConfig(id="atlas", name="Atlas", repos=["org/atlas"])],
    )

    config = update_studio(config, "New Studio")
    config = update_defaults(config, period="24h", github_user="studio-bot")

    assert config.studio.name == "New Studio"
    assert config.defaults.period == "24h"
    assert config.defaults.github_user == "studio-bot"
