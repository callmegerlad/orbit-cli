from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

REPO_PATTERN = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
PERIOD_PATTERN = re.compile(r"^(\d+)([dhw])$")
VENTURE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def slugify(value: str) -> str:
    """Create a stable CLI-safe id from a display name."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "venture"


class StudioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)


class VentureConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str = Field(min_length=1)
    repos: list[str] = Field(min_length=1)
    stakeholder: str | None = None
    milestone: str | None = None
    watch_items: list[str] | None = Field(default_factory=list)

    @model_validator(mode="after")
    def _default_id(self) -> VentureConfig:
        if self.id is None:
            self.id = slugify(self.name)
        return self

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str | None) -> str | None:
        if value is not None and not VENTURE_ID_PATTERN.match(value):
            raise ValueError("Invalid venture id: use lowercase letters, numbers, and hyphens")
        return value

    @field_validator("repos")
    @classmethod
    def _validate_repos(cls, repos: list[str]) -> list[str]:
        for r in repos:
            if not REPO_PATTERN.match(r):
                raise ValueError(f"Invalid repo {r!r}: expected 'owner/name' format")
        return repos


class DefaultsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period: str = "7d"
    github_user: str | None = None

    @field_validator("period")
    @classmethod
    def _validate_period(cls, v: str) -> str:
        if not PERIOD_PATTERN.match(v):
            raise ValueError(f"Invalid period {v!r}: expected e.g. '7d', '24h', or '2w'")
        return v


class OrbitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    studio: StudioConfig
    ventures: list[VentureConfig] = Field(min_length=1)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)

    @field_validator("ventures")
    @classmethod
    def _unique_venture_names(cls, ventures: list[VentureConfig]) -> list[VentureConfig]:
        names = [v.name for v in ventures]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"Duplicate venture names: {sorted(dupes)}")
        ids = [v.id for v in ventures if v.id is not None]
        id_dupes = {i for i in ids if ids.count(i) > 1}
        if id_dupes:
            raise ValueError(f"Duplicate venture ids: {sorted(id_dupes)}")
        return ventures

    def venture(self, ref: str) -> VentureConfig:
        for v in self.ventures:
            if v.id == ref or v.name == ref:
                return v
        raise KeyError(f"Venture {ref!r} not found in config")


class ConfigError(Exception):
    """Raised when the config file is missing or invalid."""


def default_config_path() -> Path:
    """Resolve the config path from $ORBIT_CONFIG or fall back to ./orbit.yaml."""
    env = os.environ.get("ORBIT_CONFIG")
    return Path(env) if env else Path.cwd() / "orbit.yaml"


def load_config(path: Path | None = None) -> OrbitConfig:
    """Load and validate config from `path` (or the default location)."""
    p = path or default_config_path()
    if not p.exists():
        raise ConfigError(
            f"Config file not found: {p}. Copy orbit.example.yaml to orbit.yaml to get started."
        )
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Failed to parse {p}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"Config root must be a mapping, got {type(raw).__name__}")
    try:
        return OrbitConfig.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError -> readable text
        raise ConfigError(f"Invalid config: {exc}") from exc


def write_config(config: OrbitConfig, path: Path | None = None) -> Path:
    """Validate and write an Orbit config file."""
    p = path or default_config_path()
    data = config.model_dump(mode="json", exclude_none=True)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return p


def create_config(
    *,
    studio_name: str,
    ventures: list[VentureConfig],
    period: str = "7d",
    github_user: str | None = None,
) -> OrbitConfig:
    """Build a validated config from onboarding input."""
    return OrbitConfig(
        studio=StudioConfig(name=studio_name),
        ventures=ventures,
        defaults=DefaultsConfig(period=period, github_user=github_user),
    )


def add_venture(config: OrbitConfig, venture: VentureConfig) -> OrbitConfig:
    """Return a config with one validated venture appended."""
    data = config.model_dump()
    data["ventures"] = [*data["ventures"], venture.model_dump()]
    return OrbitConfig.model_validate(data)


def update_venture(
    config: OrbitConfig,
    ref: str,
    *,
    repos: list[str] | None = None,
    stakeholder: str | None = None,
    milestone: str | None = None,
    watch_items: list[str] | None = None,
) -> OrbitConfig:
    """Return a config with editable fields changed for one venture."""
    data: dict[str, Any] = config.model_dump()
    for venture in data["ventures"]:
        if venture["id"] != ref and venture["name"] != ref:
            continue
        if repos is not None:
            venture["repos"] = repos
        if stakeholder is not None:
            venture["stakeholder"] = stakeholder
        if milestone is not None:
            venture["milestone"] = milestone
        if watch_items is not None:
            venture["watch_items"] = watch_items
        return OrbitConfig.model_validate(data)
    raise ConfigError(f"Venture {ref!r} not found in config")


def remove_venture(config: OrbitConfig, venture: VentureConfig) -> OrbitConfig:
    """Return a config with one venture removed."""
    data = config.model_dump()
    ventures = [v for v in data["ventures"] if v["id"] != venture.id and v["name"] != venture.name]
    if len(ventures) == len(data["ventures"]):
        raise ConfigError(f"Venture {venture.id!r} not found in config")
    data["ventures"] = ventures
    return OrbitConfig.model_validate(data)


def update_studio(config: OrbitConfig, name: str) -> OrbitConfig:
    """Return a config with the studio name changed."""
    data = config.model_dump()
    data["studio"]["name"] = name
    return OrbitConfig.model_validate(data)


def update_defaults(
    config: OrbitConfig,
    *,
    period: str | None = None,
    github_user: str | None = None,
) -> OrbitConfig:
    """Return a config with default settings changed."""
    data = config.model_dump()
    if period is not None:
        data["defaults"]["period"] = period
    if github_user is not None:
        data["defaults"]["github_user"] = github_user
    return OrbitConfig.model_validate(data)


def parse_period_to_hours(period: str) -> int:
    """Convert a period string ('7d', '24h', '2w') to hours."""
    m = PERIOD_PATTERN.match(period)
    if not m:
        raise ValueError(f"Invalid period: {period!r}")
    value, unit = int(m.group(1)), m.group(2)
    if unit == "h":
        return value
    if unit == "d":
        return value * 24
    return value * 24 * 7  # weeks
