"""Orbit CLI entrypoint."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, TypeVar

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from orbit import __version__
from orbit.collector import collect
from orbit.config import (
    ConfigError,
    OrbitConfig,
    VentureConfig,
    add_venture,
    create_config,
    default_config_path,
    load_config,
    remove_venture,
    slugify,
    update_defaults,
    update_studio,
    update_venture,
    write_config,
)
from orbit.fixtures import load_fixture, save_fixture
from orbit.github import GitHubClient, GitHubError
from orbit.llm import LLMError, render_catchup, render_report, render_status, write_report
from orbit.models import Audience, StudioSnapshot
from orbit.query import build_catchup, build_my_activity, build_status, render_my_activity
from orbit.reporter import annotate_snapshot
from orbit.runtime import optional_env, require_env

app = typer.Typer(
    name="orbit",
    help=(
        """
        Welcome to Orbit :rocket:

        A cross-venture engineering intelligence tool for studio teams.
        """
    ),
    no_args_is_help=True,
    add_completion=False,
    suggest_commands=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
venture_app = typer.Typer(help="Manage your studio's ventures.", no_args_is_help=True)
app.add_typer(venture_app, name="venture")
settings_app = typer.Typer(
    help="Manage Orbit studio and default settings.",
    no_args_is_help=True,
)
app.add_typer(settings_app, name="settings")

console = Console()
err_console = Console(stderr=True)

ConfigOpt = Annotated[
    Path | None,
    typer.Option("--config", "-c", help="Path to orbit.yaml.", exists=False),
]

T = TypeVar("T")

GitHubValidationResult = tuple[bool, str | None, list[str], list[str]]

GITHUB_PERMISSION_HINTS = (
    ("repo metadata", "Repository access: include the configured repo in the token scope"),
    ("pull requests", "Pull requests: Read-only"),
    ("issues", "Issues: Read-only"),
    ("commits", "Contents: Read-only"),
    ("actions workflow runs", "Actions: Read-only"),
)


def _exit(message: str, code: int = 1) -> None:
    err_console.print(f"[red]error:[/red] {message}")
    raise typer.Exit(code)


def _cancel(message: str = "Cancelled.") -> None:
    console.print(message)
    raise typer.Exit()


def _load(config_path: Path | None) -> tuple[StudioSnapshot | None, OrbitConfig]:
    """Helper that handles ConfigError uniformly."""
    try:
        return None, load_config(config_path)
    except ConfigError as exc:
        _exit(str(exc))
        raise  # unreachable; satisfies the type checker


def _resolve_snapshot(
    config_path: Path | None,
    fixture: Path | None,
    period: str | None,
) -> StudioSnapshot:
    if fixture is not None:
        try:
            snapshot = load_fixture(fixture)
        except (FileNotFoundError, ValueError) as exc:
            _exit(str(exc))
        return annotate_snapshot(snapshot)

    _, config = _load(config_path)
    try:
        snapshot = asyncio.run(collect(config, period=period))
    except RuntimeError as exc:
        _exit(str(exc))
    except Exception as exc:  # pragma: no cover - surface as clean CLI error
        _exit(f"Failed to collect data: {exc}")
    return annotate_snapshot(snapshot)


def _task_spinner(progress: Progress, description: str, callback: Callable[[], T]) -> T:
    task_id = progress.add_task(description, total=1)
    try:
        result = callback()
    except Exception:
        progress.update(task_id, description=f"{description} failed")
        raise
    progress.update(task_id, description=f"{description} done", completed=1)
    return result


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _prompt_csv(prompt: str, *, default: list[str] | None = None) -> list[str]:
    default_text = ", ".join(default or [])
    value = typer.prompt(prompt, default=default_text)
    return _split_csv(value)


def _prompt_optional(prompt: str, *, default: str | None = None) -> str | None:
    value = typer.prompt(prompt, default=default or "")
    value = value.strip()
    return value or None


def _prompt_items(label: str, *, default: list[str] | None = None) -> list[str]:
    current = default or []
    if current:
        console.print(f"Current {label.lower()}:")
        for index, item in enumerate(current, start=1):
            console.print(f"  {index}. {item}")
        if typer.confirm(f"Keep current {label.lower()}?", default=True):
            return current

    items: list[str] = []
    console.print(f"Enter {label.lower()} one at a time. Leave blank when done.")
    while True:
        item = typer.prompt(label.rstrip("s"), default="", show_default=False).strip()
        if not item:
            return items
        items.append(item)


def _venture_from_input(
    *,
    venture_id: str | None,
    name: str | None,
    repos: list[str] | None,
    stakeholder: str | None,
    milestone: str | None,
    watch_items: list[str] | None,
    prompt_details: bool,
) -> VentureConfig:
    venture_name = name or typer.prompt("Venture name")
    resolved_id = venture_id
    if resolved_id is None and prompt_details:
        resolved_id = typer.prompt("Venture id", default=slugify(venture_name))
    venture_repos = repos or _prompt_csv("GitHub repos (owner/name, comma-separated)")
    return VentureConfig(
        id=resolved_id,
        name=venture_name,
        repos=venture_repos,
        stakeholder=stakeholder
        if stakeholder is not None or not prompt_details
        else _prompt_optional("Stakeholder/co-founder", default=None),
        milestone=milestone
        if milestone is not None or not prompt_details
        else _prompt_optional("Current milestone", default=None),
        watch_items=watch_items
        if watch_items is not None or not prompt_details
        else _prompt_items("Watch items", default=[]),
    )


def _select_venture(config: OrbitConfig, prompt: str = "Select venture:") -> str:
    console.print(prompt)
    for index, venture in enumerate(config.ventures, start=1):
        console.print(f"  {index}. {venture.id} - {venture.name}")
    choice = typer.prompt(f"Select venture (1-{len(config.ventures)}, 0 to cancel)", type=int)
    if choice == 0:
        _cancel()
        raise
    elif choice < 0 or choice > len(config.ventures):
        _exit(f"Invalid venture selection: {choice}")
    selected = config.ventures[choice - 1]
    if selected.id is None:
        _exit(f"Selected venture {selected.name!r} has no id")
    return selected.id


def _venture_table(config: OrbitConfig) -> Table:
    table = Table(
        title=f"Configured ventures for [bold]{config.studio.name}[/bold]",
        show_lines=True,
    )
    table.add_column("ID / Name", no_wrap=True)
    table.add_column("Repos", no_wrap=True)
    table.add_column("Stakeholder")
    for venture in config.ventures:
        table.add_row(
            f"[cyan]{venture.id}[/cyan]\n[bold]{venture.name}[/bold]",
            "\n".join(venture.repos),
            venture.stakeholder or "[yellow]not set[/yellow]",
        )
    return table


def _venture_detail_table(config: OrbitConfig, venture_ref: str) -> Table:
    try:
        venture = config.venture(venture_ref)
    except KeyError as exc:
        _exit(str(exc))
    table = Table(
        title=f"Venture details for [bold]{venture.name}[/bold]",
        show_lines=True,
    )
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value")
    table.add_row("ID", venture.id or "N/A")
    table.add_row("Name", venture.name)
    table.add_row("Repos", "\n".join(venture.repos))
    table.add_row("Stakeholder", venture.stakeholder or "[yellow]not set[/yellow]")
    table.add_row("Milestone", venture.milestone or "[yellow]not set[/yellow]")
    table.add_row(
        "Watch items",
        "\n".join(venture.watch_items) if venture.watch_items else "[yellow]not set[/yellow]",
    )
    return table


def _prompt_venture_update(config: OrbitConfig, venture_ref: str) -> VentureConfig:
    venture = config.venture(venture_ref)
    console.print(_venture_detail_table(config, venture_ref))
    console.print("Press Enter to keep a value unchanged.")
    return VentureConfig(
        id=venture.id,
        name=venture.name,
        repos=_prompt_csv("GitHub repos (owner/name, comma-separated)", default=venture.repos),
        stakeholder=_prompt_optional("Stakeholder/co-founder", default=venture.stakeholder),
        milestone=_prompt_optional("Current milestone", default=venture.milestone),
        watch_items=_prompt_items("Watch items", default=venture.watch_items),
    )


def _config_path(config_path: Path | None) -> Path:
    return config_path or default_config_path()


def _config_warnings(config: OrbitConfig) -> list[str]:
    warnings: list[str] = []
    repo_owners: dict[str, list[str]] = {}
    for venture in config.ventures:
        ref = venture.id or venture.name
        if venture.id != slugify(venture.name):
            warnings.append(
                f"{ref}: id differs from generated slug `{slugify(venture.name)}`. "
                "This is OK if intentional."
            )
        if not venture.stakeholder:
            warnings.append(f"{ref}: stakeholder is not set.")
        if not venture.milestone:
            warnings.append(f"{ref}: milestone is not set.")
        if not venture.watch_items:
            warnings.append(f"{ref}: watch items are not set.")
        for repo in venture.repos:
            repo_owners.setdefault(repo, []).append(ref)
    for repo, owners in repo_owners.items():
        if len(owners) > 1:
            warnings.append(
                f"{repo}: repo is configured under multiple ventures: {', '.join(owners)}."
            )
    return warnings


def _github_permission_hints(failures: list[str]) -> list[str]:
    hints: list[str] = []
    for failure in failures:
        normalized = failure.lower()
        for label, hint in GITHUB_PERMISSION_HINTS:
            if label in normalized and hint not in hints:
                hints.append(hint)
    return hints


def _github_permission_checklist(missing_hints: list[str]) -> list[tuple[bool, str]]:
    missing = set(missing_hints)
    return [(hint not in missing, hint) for _, hint in GITHUB_PERMISSION_HINTS]


def _github_failure_message(label: str, error: GitHubError) -> str:
    text = str(error)
    if "Resource not accessible by personal access token" in text:
        return f"{label} failed: missing token permission"
    return f"{label} failed: {text}"


async def _github_checks(config: OrbitConfig, token: str) -> tuple[str, list[str]]:
    failures: list[str] = []
    since = datetime.now(UTC) - timedelta(days=1)
    async with GitHubClient(token) as client:
        try:
            user = await client.authenticated_user()
            login = str(user.get("login") or "unknown")
        except GitHubError as exc:
            return "unknown", [f"authentication failed: {exc}"]

        checks: list[tuple[str, Callable[[], Awaitable[object]]]] = []
        for venture in config.ventures:
            for repo in venture.repos:
                checks.extend(
                    [
                        (f"{repo}: repo metadata", lambda r=repo: client.repo_info(r)),
                        (
                            f"{repo}: pull requests",
                            lambda r=repo: client.list_pull_requests(r, per_page=1),
                        ),
                        (
                            f"{repo}: issues",
                            lambda r=repo: client.list_issues(r, since=since, per_page=1),
                        ),
                        (
                            f"{repo}: commits",
                            lambda r=repo: client.list_commits(r, since=since, per_page=1),
                        ),
                        (
                            f"{repo}: actions workflow runs",
                            lambda r=repo: client.latest_workflow_run(r),
                        ),
                    ]
                )
        for label, check in checks:
            try:
                await check()
            except GitHubError as exc:
                failures.append(_github_failure_message(label, exc))
    return login, failures


def _github_validation_result(config: OrbitConfig) -> GitHubValidationResult:
    token = optional_env("GITHUB_TOKEN")
    if not token:
        return (
            False,
            None,
            [
                "GitHub token: missing GITHUB_TOKEN",
                "Set GITHUB_TOKEN in your shell or local .env file.",
            ],
            [],
        )

    try:
        login, failures = asyncio.run(_github_checks(config, token))
    except RuntimeError as exc:
        return False, None, [f"GitHub validation failed: {exc}"], []

    if failures:
        permission_hints = _github_permission_hints(failures)
        return (
            False,
            login,
            [
                f"GitHub token check failed for @{login}",
            ],
            permission_hints,
        )

    return (
        True,
        login,
        [
            "Verified access to repo metadata, pull requests, issues, commits, "
            "and actions workflow runs for all configured repos."
        ],
        [],
    )


def _run_validate_checks(config: OrbitConfig) -> tuple[list[str], GitHubValidationResult]:
    with Progress(
        SpinnerColumn("dots"),
        TextColumn("[progress.description]{task.description}"),
        console=err_console,
        transient=False,
    ) as progress:
        warnings = _task_spinner(
            progress,
            "Checking Orbit config quality...",
            lambda: _config_warnings(config),
        )
        github_result = _task_spinner(
            progress,
            "Checking GitHub token and repository access...",
            lambda: _github_validation_result(config),
        )
    return warnings, github_result


def _print_github_validation(result: GitHubValidationResult) -> bool:
    github_ok, login, messages, permission_hints = result
    if github_ok:
        console.print(f"[green]:heavy_check_mark: GitHub token works for @{login}[/green]")
        for message in messages:
            console.print(message)
        return True

    console.print(f"[red]{messages[0]}[/red]")
    for message in messages[1:]:
        console.print(f"  - {message}")
    if permission_hints:
        console.print("Fine-grained PAT permission checklist:")
        for configured, hint in _github_permission_checklist(permission_hints):
            marker = ":ballot_box_with_check:" if configured else ":white_medium_square:"
            console.print(f"  {marker} {hint}")
    return False


def version_callback(value: bool):
    if value:
        print(f"Orbit {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            "--version", "-v", help="Show Orbit version.", is_eager=True, callback=version_callback
        ),
    ] = False,
) -> None:
    pass


@app.command()
def init(
    config_path: ConfigOpt = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing config.")] = False,
) -> None:
    """Create `orbit.yaml` through a guided setup."""
    target = config_path or default_config_path()
    if target.exists() and not force:
        _exit(f"{target} already exists. Use --force to overwrite.")

    console.print("[bold]Orbit setup[/bold]")
    studio_name = typer.prompt("Studio name", default="Orbital Ventures")
    period = typer.prompt("Default reporting period", default="7d")
    github_user = _prompt_optional("Default GitHub username", default=None)
    ventures = [
        _venture_from_input(
            venture_id=None,
            name=None,
            repos=None,
            stakeholder=None,
            milestone=None,
            watch_items=None,
            prompt_details=True,
        )
    ]
    while typer.confirm("Add another venture?", default=False):
        ventures.append(
            _venture_from_input(
                venture_id=None,
                name=None,
                repos=None,
                stakeholder=None,
                milestone=None,
                watch_items=None,
                prompt_details=True,
            )
        )
    try:
        config = create_config(
            studio_name=studio_name,
            period=period,
            github_user=github_user,
            ventures=ventures,
        )
        written = write_config(config, target)
    except Exception as exc:
        _exit(f"Failed to create config: {exc}")
    console.print(f"[green]wrote[/green] {written}")
    console.print("Add more ventures with `orbit venture add`.")


@venture_app.command("add")
def venture_add(
    venture_id: Annotated[
        str | None,
        typer.Option("--id", help="Stable CLI id. Defaults to a slug from --name."),
    ] = None,
    name: Annotated[str | None, typer.Option("--name", help="Venture name.")] = None,
    repo: Annotated[
        list[str] | None,
        typer.Option("--repo", help="GitHub repo in owner/name format. Repeatable."),
    ] = None,
    stakeholder: Annotated[
        str | None, typer.Option("--stakeholder", help="Founder or stakeholder name.")
    ] = None,
    milestone: Annotated[
        str | None, typer.Option("--milestone", help="Current venture milestone.")
    ] = None,
    watch_item: Annotated[
        list[str] | None,
        typer.Option("--watch-item", help="Product or delivery area to watch. Repeatable."),
    ] = None,
    config_path: ConfigOpt = None,
) -> None:
    """Add a venture to the Orbit config."""
    _, config = _load(config_path)
    prompt_details = all(
        value is None for value in (venture_id, name, repo, stakeholder, milestone, watch_item)
    )
    try:
        venture = _venture_from_input(
            venture_id=venture_id,
            name=name,
            repos=repo,
            stakeholder=stakeholder,
            milestone=milestone,
            watch_items=watch_item,
            prompt_details=prompt_details,
        )
        updated = add_venture(config, venture)
        written = write_config(updated, config_path)
    except Exception as exc:
        _exit(f"Failed to add venture: {exc}")
    console.print(f"[green]added[/green] {venture.name} in {written}")


@venture_app.command("update")
def venture_update(
    venture_ref: Annotated[
        str | None,
        typer.Argument(help="Existing venture id. Omit for interactive selection."),
    ] = None,
    repo: Annotated[
        list[str] | None,
        typer.Option("--repo", help="Replace repos. Repeat for multiple repos."),
    ] = None,
    stakeholder: Annotated[
        str | None, typer.Option("--stakeholder", help="Replace stakeholder.")
    ] = None,
    milestone: Annotated[str | None, typer.Option("--milestone", help="Replace milestone.")] = None,
    watch_item: Annotated[
        list[str] | None,
        typer.Option("--watch-item", help="Replace watch items. Repeat for multiple items."),
    ] = None,
    config_path: ConfigOpt = None,
) -> None:
    """Update repos, stakeholder, milestone, or watch items for a venture."""
    _, config = _load(config_path)
    selected_ref = venture_ref or _select_venture(config)
    try:
        if repo is None and stakeholder is None and milestone is None and watch_item is None:
            venture = _prompt_venture_update(config, selected_ref)
            updated = update_venture(
                config,
                selected_ref,
                repos=venture.repos,
                stakeholder=venture.stakeholder,
                milestone=venture.milestone,
                watch_items=venture.watch_items,
            )
        else:
            updated = update_venture(
                config,
                selected_ref,
                repos=repo,
                stakeholder=stakeholder,
                milestone=milestone,
                watch_items=watch_item,
            )
        written = write_config(updated, config_path)
    except Exception as exc:
        _exit(f"Failed to update venture: {exc}")
    console.print(f"[green]updated[/green] {selected_ref} in {written}")


@venture_app.command("remove")
def venture_remove(
    venture_ref: Annotated[
        str | None,
        typer.Argument(help="Existing venture id. Omit for interactive selection."),
    ] = None,
    config_path: ConfigOpt = None,
) -> None:
    """Remove an existing venture from the config."""
    _, config = _load(config_path)
    selected_ref = venture_ref or _select_venture(config, "Select venture to remove:")
    try:
        updated = remove_venture(config, config.venture(selected_ref))
        written = write_config(updated, config_path)
    except Exception as exc:
        _exit(f"Failed to remove venture: {exc}")
    console.print(f"[green]removed[/green] {selected_ref} in {written}")


@venture_app.command("list")
def venture_list(config_path: ConfigOpt = None) -> None:
    """List ventures in the config."""
    _, config = _load(config_path)
    console.print(_venture_table(config))


@venture_app.command("details")
def venture_details(
    venture_ref: Annotated[
        str | None,
        typer.Option("--venture", help="Venture id or exact name. Omit for selection."),
    ] = None,
    config_path: ConfigOpt = None,
) -> None:
    """Show detailed reporting context for one venture."""
    _, config = _load(config_path)
    selected_ref = venture_ref or _select_venture(config, "Select venture to show details:")
    console.print(_venture_detail_table(config, selected_ref))


@settings_app.command("studio")
def settings_studio(
    name: Annotated[str | None, typer.Option("--name", help="New studio name.")] = None,
    config_path: ConfigOpt = None,
) -> None:
    """Update the studio name."""
    _, config = _load(config_path)
    new_name = name or typer.prompt("Studio name", default=config.studio.name)
    try:
        updated = update_studio(config, new_name)
        written = write_config(updated, config_path)
    except Exception as exc:
        _exit(f"Failed to update studio settings: {exc}")
    console.print(f"[green]updated[/green] studio name in {written}")


@settings_app.command("defaults")
def settings_defaults(
    period: Annotated[
        str | None,
        typer.Option("--period", help="Default reporting period, e.g. 7d or 24h."),
    ] = None,
    github_user: Annotated[
        str | None,
        typer.Option("--github-user", help="Default GitHub username."),
    ] = None,
    config_path: ConfigOpt = None,
) -> None:
    """Update default reporting settings."""
    _, config = _load(config_path)
    prompt_values = period is None and github_user is None
    new_period = period
    new_github_user = github_user
    if prompt_values:
        new_period = typer.prompt("Default reporting period", default=config.defaults.period)
        new_github_user = _prompt_optional(
            "Default GitHub username",
            default=config.defaults.github_user,
        )
    try:
        updated = update_defaults(
            config,
            period=new_period,
            github_user=new_github_user,
        )
        written = write_config(updated, config_path)
    except Exception as exc:
        _exit(f"Failed to update default settings: {exc}")
    console.print(f"[green]updated[/green] defaults in {written}")


@app.command(name="validate")
def config_validate(config_path: ConfigOpt = None) -> None:
    """Inspect and validate existing Orbit configuration."""
    _, config = _load(config_path)
    path = _config_path(config_path)
    warnings, github_result = _run_validate_checks(config)

    console.print("\n[bold]Config checks[/bold]")
    console.print(f"[green]:heavy_check_mark:[/green] Orbit config is valid: {path}\n")
    console.print(
        f"Defaults: period=[cyan]{config.defaults.period}[/cyan], "
        f"github_user=[cyan]{config.defaults.github_user or 'not set'}[/cyan]"
        "\n"
    )

    console.print(_venture_table(config))

    if warnings:
        console.print("[yellow]Warnings[/yellow]")
        for warning in warnings:
            console.print(f"  - {warning}")
        console.print("Config is usable, but reports may be less useful until these are filled in.")
    else:
        console.print("[green]:heavy_check_mark: No warnings found.[/green]")

    console.print()
    console.print("[bold]GitHub checks[/bold]")
    github_ok = _print_github_validation(github_result)

    console.print()
    console.print("[bold]Result[/bold]")
    if warnings or not github_ok:
        console.print("[yellow]Orbit config is valid, but setup is not fully ready yet.[/yellow]")
        console.print("Fix the items above, then run `orbit validate` again.")
        return

    console.print(":rocket: Orbit is ready to launch with this config!")


@app.command(name="collect")
def collect_cmd(  # `collect` would shadow the imported function in this module.
    config_path: ConfigOpt = None,
    period: Annotated[
        str | None, typer.Option("--period", help="Lookback period, e.g. 7d or 24h.")
    ] = None,
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Where to write the snapshot JSON."),
    ] = Path("snapshot.json"),
) -> None:
    """Collect a snapshot from GitHub and save it as JSON."""
    with Progress(
        SpinnerColumn("dots"),
        TextColumn("[progress.description]{task.description}"),
        console=err_console,
        transient=False,
    ) as progress:
        snapshot = _task_spinner(
            progress,
            "Collecting GitHub activity...",
            lambda: _resolve_snapshot(config_path, fixture=None, period=period),
        )
        _task_spinner(
            progress,
            f"Writing snapshot to {output}...",
            lambda: save_fixture(snapshot, output),
        )
    console.print(f"[green]wrote[/green] {output} ({len(snapshot.ventures)} ventures)")


@app.command(no_args_is_help=True)
def report(
    audience: Annotated[str, typer.Argument(help="One of: engineering, founder, leadership.")],
    venture: Annotated[
        str | None,
        typer.Option("--venture", help="Required for `founder` reports."),
    ] = None,
    period: Annotated[
        str | None, typer.Option("--period", help="Lookback period, e.g. 7d.")
    ] = None,
    fixture: Annotated[
        Path | None,
        typer.Option(
            "--fixture",
            help="Read a previously saved snapshot instead of calling GitHub.",
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write Markdown to a file instead of stdout."),
    ] = None,
    raw: Annotated[
        bool,
        typer.Option("--raw", help="Print raw Markdown without terminal rendering."),
    ] = False,
    config_path: ConfigOpt = None,
) -> None:
    """Generate an audience-specific report."""
    if audience not in ("engineering", "founder", "leadership"):
        _exit(f"Unknown audience: {audience!r}")
    aud: Audience = audience  # type: ignore[assignment]

    snapshot_status = (
        f"Loading snapshot from {fixture}..."
        if fixture is not None
        else "Collecting GitHub activity..."
    )

    try:
        with Progress(
            SpinnerColumn("dots"),
            TextColumn("[progress.description]{task.description}"),
            console=err_console,
            transient=False,
        ) as progress:
            snapshot = _task_spinner(
                progress,
                snapshot_status,
                lambda: _resolve_snapshot(config_path, fixture=fixture, period=period),
            )
            body = _task_spinner(
                progress,
                f"Generating {aud} report with Orbit...",
                lambda: render_report(snapshot, aud, venture=venture),
            )
    except LLMError as exc:
        _exit(str(exc))
    except RuntimeError as exc:
        _exit(str(exc))

    if output is not None:
        write_report(body, output)
        console.print(f"[green]wrote[/green] {output}")
        return

    if raw or not sys.stdout.isatty():
        console.print(body, markup=False, highlight=False)
    else:
        console.print(Markdown(body))


async def _fetch_authenticated_user(token: str) -> str:
    async with GitHubClient(token) as client:
        info = await client.authenticated_user()
    login = info.get("login")
    if not isinstance(login, str) or not login:
        raise GitHubError("GitHub returned no login for the authenticated user")
    return login


def _resolve_user(
    *,
    override: str | None,
    config: OrbitConfig,
    allow_github_lookup: bool,
) -> str:
    """Resolve the GitHub user for `orbit me`.

    Priority: explicit override > config.defaults.github_user > authenticated
    user from GitHub (only when we have a token and aren't using a fixture).
    """
    if override:
        return override
    if config.defaults.github_user:
        return config.defaults.github_user
    if not allow_github_lookup:
        _exit(
            "No GitHub user. Pass --user, set defaults.github_user in your "
            "config, or run without --fixture so Orbit can read the "
            "authenticated user from GitHub."
        )
    try:
        token = require_env("GITHUB_TOKEN")
        return asyncio.run(_fetch_authenticated_user(token))
    except (RuntimeError, GitHubError) as exc:
        _exit(f"Could not resolve GitHub user: {exc}")
        raise  # unreachable


ME_DEFAULT_PERIOD = "7d"


@app.command(name="me")
def me_cmd(
    period: Annotated[
        str,
        typer.Option(
            "--period",
            help="Lookback period (e.g. 7d, 24h). Defaults to a weekly recap window.",
        ),
    ] = ME_DEFAULT_PERIOD,
    user: Annotated[
        str | None,
        typer.Option("--user", help="GitHub handle to query (defaults to your configured user)."),
    ] = None,
    venture: Annotated[
        list[str] | None,
        typer.Option(
            "--venture",
            help=(
                "Restrict to one or more ventures by id (or exact name). "
                "Repeat the flag or pass a comma-separated list."
            ),
        ),
    ] = None,
    fixture: Annotated[
        Path | None,
        typer.Option(
            "--fixture",
            help="Read a previously saved snapshot instead of calling GitHub.",
        ),
    ] = None,
    config_path: ConfigOpt = None,
) -> None:
    """Show what you personally worked on across all configured ventures."""
    _, config = _load(config_path)
    resolved_user = _resolve_user(
        override=user,
        config=config,
        allow_github_lookup=fixture is None,
    )

    venture_refs: list[str] = []
    for raw in venture or []:
        venture_refs.extend(_split_csv(raw))

    snapshot_status = (
        f"Loading snapshot from {fixture}..."
        if fixture is not None
        else "Collecting GitHub activity..."
    )

    with Progress(
        SpinnerColumn("dots"),
        TextColumn("[progress.description]{task.description}"),
        console=err_console,
        transient=False,
    ) as progress:
        snapshot = _task_spinner(
            progress,
            snapshot_status,
            lambda: _resolve_snapshot(config_path, fixture=fixture, period=period),
        )
        try:
            activity = _task_spinner(
                progress,
                f"Building activity view for @{resolved_user}...",
                lambda: build_my_activity(
                    snapshot, resolved_user, venture_refs=venture_refs or None
                ),
            )
        except KeyError as exc:
            _exit(f"Unknown venture: {exc.args[0]!r}")

    console.print(render_my_activity(activity))


CATCHUP_DEFAULT_SINCE = "7d"


@app.command(name="catchup")
def catchup_cmd(
    venture: Annotated[
        list[str] | None,
        typer.Option(
            "--venture",
            help=(
                "Venture(s) to catch up on, by id or exact name. "
                "Repeat the flag or pass a comma-separated list."
            ),
        ),
    ] = None,
    since: Annotated[
        str,
        typer.Option(
            "--since",
            help="Lookback window (e.g. 7d, 2w, 24h). Defaults to a week.",
        ),
    ] = CATCHUP_DEFAULT_SINCE,
    user: Annotated[
        str | None,
        typer.Option("--user", help="GitHub handle to exclude (defaults to your configured user)."),
    ] = None,
    fixture: Annotated[
        Path | None,
        typer.Option(
            "--fixture",
            help="Read a previously saved snapshot instead of calling GitHub.",
        ),
    ] = None,
    config_path: ConfigOpt = None,
) -> None:
    """Catch up on what changed in one or more ventures while you were away."""
    _, config = _load(config_path)
    resolved_user = _resolve_user(
        override=user,
        config=config,
        allow_github_lookup=fixture is None,
    )

    venture_refs: list[str] = []
    for raw in venture or []:
        venture_refs.extend(_split_csv(raw))
    if not venture_refs:
        _exit("Pass at least one venture via --venture (id or exact name).")

    snapshot_status = (
        f"Loading snapshot from {fixture}..."
        if fixture is not None
        else "Collecting GitHub activity..."
    )

    with Progress(
        SpinnerColumn("dots"),
        TextColumn("[progress.description]{task.description}"),
        console=err_console,
        transient=False,
    ) as progress:
        snapshot = _task_spinner(
            progress,
            snapshot_status,
            lambda: _resolve_snapshot(config_path, fixture=fixture, period=since),
        )

        contexts = []
        for ref in venture_refs:
            try:
                contexts.append(
                    _task_spinner(
                        progress,
                        f"Building catchup context for {ref}...",
                        lambda r=ref: build_catchup(snapshot, user=resolved_user, venture_ref=r),
                    )
                )
            except KeyError as exc:
                _exit(f"Unknown venture: {exc.args[0]!r}")

        briefs = []
        for ctx in contexts:
            try:
                briefs.append(
                    (
                        ctx,
                        _task_spinner(
                            progress,
                            f"Generating catchup for {ctx.venture_name}...",
                            lambda c=ctx: render_catchup(c),
                        ),
                    )
                )
            except LLMError as exc:
                _exit(str(exc))
            except RuntimeError as exc:
                _exit(str(exc))

    for ctx, body in briefs:
        console.print(f"\n[bold cyan]{ctx.venture_name}[/bold cyan]")
        console.print(body, markup=False, highlight=False)


STATUS_DEFAULT_PERIOD = "7d"


@app.command(name="status")
def status_cmd(
    period: Annotated[
        str,
        typer.Option(
            "--period",
            help="Lookback window for the activity heartbeat (e.g. 7d, 2w, 24h).",
        ),
    ] = STATUS_DEFAULT_PERIOD,
    venture: Annotated[
        list[str] | None,
        typer.Option(
            "--venture",
            help=(
                "Restrict to one or more ventures by id (or exact name). "
                "Repeat the flag or pass a comma-separated list."
            ),
        ),
    ] = None,
    fixture: Annotated[
        Path | None,
        typer.Option(
            "--fixture",
            help="Read a previously saved snapshot instead of calling GitHub.",
        ),
    ] = None,
    config_path: ConfigOpt = None,
) -> None:
    """Studio-wide snapshot: what every venture is working on right now."""
    _, _config = _load(config_path)

    venture_refs: list[str] = []
    for raw in venture or []:
        venture_refs.extend(_split_csv(raw))

    snapshot_status = (
        f"Loading snapshot from {fixture}..."
        if fixture is not None
        else "Collecting GitHub activity..."
    )

    with Progress(
        SpinnerColumn("dots"),
        TextColumn("[progress.description]{task.description}"),
        console=err_console,
        transient=False,
    ) as progress:
        snapshot = _task_spinner(
            progress,
            snapshot_status,
            lambda: _resolve_snapshot(config_path, fixture=fixture, period=period),
        )
        try:
            context = _task_spinner(
                progress,
                "Building studio status context...",
                lambda: build_status(snapshot, venture_refs=venture_refs or None),
            )
        except KeyError as exc:
            _exit(f"Unknown venture: {exc.args[0]!r}")

        try:
            body = _task_spinner(
                progress,
                "Generating studio status with Orbit...",
                lambda: render_status(context),
            )
        except LLMError as exc:
            _exit(str(exc))
        except RuntimeError as exc:
            _exit(str(exc))

    console.print(body, markup=False, highlight=False)


if __name__ == "__main__":  # pragma: no cover
    app()
