"""Tests for pure helper functions in `orbit.cli`.

These cover the small, stateless utilities that the CLI commands compose
on top of. Keeping them in a dedicated file makes the higher-level CLI
tests easier to read.
"""

from __future__ import annotations

import pytest

import orbit.cli as cli
from orbit.config import VentureConfig, create_config
from orbit.github import GitHubError


# --- _split_csv ---------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("a,b,c", ["a", "b", "c"]),
        (" a , b , c ", ["a", "b", "c"]),
        ("a,,b,", ["a", "b"]),
        ("", []),
        (",,,", []),
        ("only-one", ["only-one"]),
    ],
)
def test_split_csv(value: str, expected: list[str]) -> None:
    assert cli._split_csv(value) == expected


# --- _github_failure_message --------------------------------------------------


def test_github_failure_message_maps_token_permission_error() -> None:
    err = GitHubError("403 Resource not accessible by personal access token")
    assert (
        cli._github_failure_message("orbital-ventures/atlas-router: pull requests", err)
        == "orbital-ventures/atlas-router: pull requests failed: missing token permission"
    )


def test_github_failure_message_passes_through_other_errors() -> None:
    err = GitHubError("rate limit exceeded")
    msg = cli._github_failure_message("orbital-ventures/atlas-router: issues", err)
    assert msg == "orbital-ventures/atlas-router: issues failed: rate limit exceeded"


# --- _github_permission_hints / _github_permission_checklist -----------------


def test_permission_hints_dedupe_across_repos() -> None:
    failures = [
        "repo-a: pull requests failed: missing token permission",
        "repo-b: pull requests failed: missing token permission",  # duplicate hint
        "repo-a: issues failed: missing token permission",
    ]
    assert cli._github_permission_hints(failures) == [
        "Pull requests: Read-only",
        "Issues: Read-only",
    ]


def test_permission_hints_returns_empty_when_no_keywords_match() -> None:
    failures = ["repo-a: timed out connecting"]
    assert cli._github_permission_hints(failures) == []


def test_permission_checklist_marks_unconfigured_hints() -> None:
    missing = ["Pull requests: Read-only"]
    checklist = cli._github_permission_checklist(missing)
    pulls = next(item for item in checklist if item[1] == "Pull requests: Read-only")
    issues = next(item for item in checklist if item[1] == "Issues: Read-only")
    assert pulls == (False, "Pull requests: Read-only")
    assert issues == (True, "Issues: Read-only")


# --- _config_warnings ---------------------------------------------------------


def test_config_warnings_flags_repo_used_by_multiple_ventures() -> None:
    config = create_config(
        studio_name="Orbital Ventures",
        ventures=[
            VentureConfig(
                id="helios", name="Helios Health", repos=["orbital-ventures/shared-infra"]
            ),
            VentureConfig(
                id="atlas", name="Atlas Logistics", repos=["orbital-ventures/shared-infra"]
            ),
        ],
    )
    warnings = cli._config_warnings(config)
    assert any(
        "orbital-ventures/shared-infra" in w and "multiple ventures" in w for w in warnings
    )


def test_config_warnings_flags_custom_id_diverging_from_slug() -> None:
    config = create_config(
        studio_name="Orbital Ventures",
        ventures=[
            VentureConfig(id="hh", name="Helios Health", repos=["orbital-ventures/helios-api"])
        ],
    )
    warnings = cli._config_warnings(config)
    assert any("differs from generated slug `helios-health`" in w for w in warnings)


def test_config_warnings_quiet_for_complete_config() -> None:
    config = create_config(
        studio_name="Orbital Ventures",
        ventures=[
            VentureConfig(
                id="helios-health",
                name="Helios Health",
                repos=["orbital-ventures/helios-api"],
                stakeholder="Priya",
                milestone="HIPAA pilot",
                watch_items=["patient onboarding"],
            )
        ],
    )
    assert cli._config_warnings(config) == []
