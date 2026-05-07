from __future__ import annotations

import json
from datetime import datetime, timedelta
from getpass import getuser
from importlib import resources
from pathlib import Path
from typing import Any

from openai import OpenAI

from orbit.config import parse_period_to_hours
from orbit.models import Audience, EvidenceItem, StudioSnapshot, VentureSnapshot
from orbit.runtime import optional_env, require_env

DEFAULT_MODEL = "gpt-5-mini"


class LLMError(Exception):
    """Raised when the LLM call fails or returns no content."""


def _utc_offset(dt: datetime) -> str:
    offset = dt.strftime("%z")
    if not offset:
        return "UTC offset unknown"
    return f"UTC{offset[:3]}:{offset[3:]}"


def _timezone_label(dt: datetime) -> str:
    offset = _utc_offset(dt)
    return f"({offset})"


def _format_report_time(dt: datetime) -> str:
    local_dt = dt.astimezone()
    return f"{local_dt:%Y-%m-%d %H:%M} {_timezone_label(local_dt)}"


def _safe_label_part(value: object, fallback: str) -> str:
    text = str(value or fallback).lower()
    return "".join(ch if ch.isalnum() else "-" for ch in text).strip("-") or fallback


def _evidence_citation(item: EvidenceItem) -> dict[str, str]:
    metadata = item.raw_metadata
    if item.source_type == "pull_request":
        number = metadata.get("number")
        suffix = _safe_label_part(number, item.title)
        text = f"PR #{number}" if number else item.title
        label = f"pr-{suffix}"
    elif item.source_type == "issue":
        number = metadata.get("number")
        suffix = _safe_label_part(number, item.title)
        text = f"Issue #{number}" if number else item.title
        label = f"issue-{suffix}"
    elif item.source_type == "workflow_run":
        run_id = metadata.get("run_id")
        suffix = _safe_label_part(run_id, item.title)
        text = f"CI run {run_id}" if run_id else "CI run"
        label = f"ci-{suffix}"
    else:
        sha = str(metadata.get("sha") or "").strip()
        short_sha = sha[:7] if sha else _safe_label_part(item.title, "commit")[:12]
        text = f"`{short_sha}`"
        label = f"commit-{short_sha}"
    return {
        "text": text,
        "label": label,
        "markdown": f"[{text}][{label}]",
        "definition": f"[{label}]: {item.url}",
    }


def load_prompt(audience: Audience) -> str:
    """Load the audience-specific prompt template bundled with the package."""
    filename = f"{audience}.md"
    try:
        prompt_dir = resources.files("orbit.prompts")
        shared = prompt_dir.joinpath("_shared.md").read_text(encoding="utf-8")
        audience_prompt = prompt_dir.joinpath(filename).read_text(encoding="utf-8")
        return f"{shared}\n\n---\n\n{audience_prompt}"
    except FileNotFoundError as exc:
        raise LLMError(f"Prompt template not found: {filename}") from exc


def _ventures_payload(snapshot: StudioSnapshot, only: str | None = None) -> list[dict[str, Any]]:
    ventures: list[VentureSnapshot] = (
        [v for v in snapshot.ventures if v.id == only or v.name == only]
        if only
        else snapshot.ventures
    )
    if only and not ventures:
        raise LLMError(f"Venture {only!r} not found in snapshot")
    return [_venture_payload(v) for v in ventures]


def _resolve_venture_ref(snapshot: StudioSnapshot, ref: str) -> str:
    for venture in snapshot.ventures:
        if venture.id == ref or venture.name == ref:
            return venture.id or venture.name
    raise LLMError(f"Venture {ref!r} not found in snapshot")


def _venture_payload(v: VentureSnapshot) -> dict[str, Any]:
    return {
        "id": v.id,
        "name": v.name,
        "stakeholder": v.stakeholder,
        "milestone": v.milestone,
        "watch_items": v.watch_items,
        "repos": v.repos,
        "confidence": v.confidence,
        "signals": [s.model_dump(mode="json") for s in v.signals] if v.signals else "None",
        "evidence": [_evidence_payload(e) for e in v.evidence],
        "stats": {
            "merged_prs": v.merged_pr_count,
            "commits": v.commit_count,
        },
    }


def _evidence_payload(item: EvidenceItem) -> dict[str, Any]:
    payload = item.model_dump(mode="json")
    payload["citation"] = _evidence_citation(item)
    return payload


def _report_metadata(
    snapshot: StudioSnapshot,
    audience: Audience,
    *,
    venture: str | None,
    model: str,
) -> dict[str, str | None]:
    period_hours = parse_period_to_hours(snapshot.period)
    period_end = snapshot.generated_at.astimezone()
    period_start = period_end - timedelta(hours=period_hours)
    scope = venture if audience == "founder" else "All configured ventures"
    return {
        "brand": "Orbit",
        "generator": "Orbit CLI",
        "audience": audience,
        "scope": scope,
        "timezone": _timezone_label(period_end),
        "generated_at": _format_report_time(snapshot.generated_at),
        "generated_at_iso": snapshot.generated_at.isoformat(timespec="minutes"),
        "reporting_window_start": _format_report_time(period_start),
        "reporting_window_start_iso": period_start.isoformat(timespec="minutes"),
        "reporting_window_end": _format_report_time(period_end),
        "reporting_window_end_iso": period_end.isoformat(timespec="minutes"),
        "reporting_period": snapshot.period,
        "generated_by": optional_env("ORBIT_GENERATED_BY") or getuser(),
        "model": model,
        "confidence_source": "Deterministic Orbit rules",
        "evidence_source": "GitHub activity snapshot",
    }


def render_report(
    snapshot: StudioSnapshot,
    audience: Audience,
    *,
    venture: str | None = None,
    model: str | None = None,
) -> str:
    """Generate a Markdown report for the given audience.

    `venture` is required for `audience="founder"` and ignored otherwise.
    """
    if audience == "founder" and not venture:
        raise LLMError("Founder reports require --venture")

    resolved_venture = _resolve_venture_ref(snapshot, venture) if venture else None

    api_key = require_env("OPENAI_API_KEY")
    client = OpenAI(api_key=api_key)
    chosen_model = model or optional_env("ORBIT_LLM_MODEL") or DEFAULT_MODEL

    system = load_prompt(audience)
    payload = {
        "studio": snapshot.studio_name,
        "period": snapshot.period,
        "generated_at": _format_report_time(snapshot.generated_at),
        "metadata": _report_metadata(
            snapshot, audience, venture=resolved_venture, model=chosen_model
        ),
        "ventures": _ventures_payload(snapshot, only=resolved_venture),
    }
    user = (
        "Structured evidence and deterministic signals follow as JSON. "
        "Use only this data. Return Markdown only.\n\n"
        f"```json\n{json.dumps(payload, indent=2, default=str)}\n```"
    )

    try:
        resp = client.chat.completions.create(
            model=chosen_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
        )
    except Exception as exc:  # SDK exceptions vary; surface a clean message.
        raise LLMError(f"LLM request failed: {exc}") from exc

    content = (resp.choices[0].message.content or "").strip()
    if not content:
        raise LLMError("LLM returned empty response")
    return content


# --- catchup ---------------------------------------------------------------


def _catchup_payload(context: object) -> dict[str, Any]:
    """Build the JSON payload for the catchup prompt.

    Imported lazily inside the function so `query` can depend on `llm` only
    via this contract, not via module-level types.
    """
    from orbit.query import CatchupContext

    if not isinstance(context, CatchupContext):  # pragma: no cover - guard
        raise LLMError("render_catchup requires a CatchupContext")

    your_last_touched = (
        _format_report_time(context.your_last_touched)
        if context.your_last_touched
        else None
    )
    return {
        "venture": {
            "id": context.venture_id,
            "name": context.venture_name,
            "repos": context.repos,
        },
        "user": context.user,
        "period": context.period,
        "your_last_touched": your_last_touched,
        "stats": {
            "commits": context.commit_count,
            "merged_prs": context.merged_pr_count,
            "open_prs": context.open_pr_count,
            "contributors": context.contributors,
            "open_issue_label_counts": context.label_counts,
        },
        "changes_by_others": [item.model_dump(mode="json") for item in context.changes_by_others],
        "your_open_work": [item.model_dump(mode="json") for item in context.your_open_work],
        "your_open_issue_count": context.your_open_issue_count,
    }


def render_catchup(context: object, *, model: str | None = None) -> str:
    """Generate a plain-text catchup brief for one venture."""
    api_key = require_env("OPENAI_API_KEY")
    client = OpenAI(api_key=api_key)
    chosen_model = model or optional_env("ORBIT_LLM_MODEL") or DEFAULT_MODEL

    system = _load_catchup_prompt()
    payload = _catchup_payload(context)
    user = (
        "Structured evidence for this venture follows as JSON. Use only "
        "this data. Return plain text only, following the structure in "
        "the system prompt.\n\n"
        f"```json\n{json.dumps(payload, indent=2, default=str)}\n```"
    )

    try:
        resp = client.chat.completions.create(
            model=chosen_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
        )
    except Exception as exc:
        raise LLMError(f"LLM request failed: {exc}") from exc

    content = (resp.choices[0].message.content or "").strip()
    if not content:
        raise LLMError("LLM returned empty response")
    return content


def _load_catchup_prompt() -> str:
    try:
        return resources.files("orbit.prompts").joinpath("catchup.md").read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise LLMError("Prompt template not found: catchup.md") from exc


# --- status ----------------------------------------------------------------


def _status_payload(context: object) -> dict[str, Any]:
    """Build the JSON payload for the status prompt."""
    from orbit.query import StatusContext

    if not isinstance(context, StatusContext):  # pragma: no cover - guard
        raise LLMError("render_status requires a StatusContext")

    return {
        "studio": context.studio_name,
        "period": context.period,
        "ventures": [
            {
                "id": v.venture_id,
                "name": v.venture_name,
                "repos": v.repos,
                "confidence": v.confidence,
                "signal_flags": v.signal_flags,
                "counts": {
                    "open_prs": v.open_pr_count,
                    "merged_prs": v.merged_pr_count,
                    "stale_prs": v.stale_pr_count,
                    "critical_issues": v.critical_issue_count,
                    "commits": v.commit_count,
                    "contributors": len(v.contributors),
                },
                "ci_unhealthy": v.ci_unhealthy,
                "low_activity": v.low_activity,
                "open_pr_titles": v.open_pr_titles,
            }
            for v in context.ventures
        ],
    }


def render_status(context: object, *, model: str | None = None) -> str:
    """Generate a plain-text studio status snapshot."""
    api_key = require_env("OPENAI_API_KEY")
    client = OpenAI(api_key=api_key)
    chosen_model = model or optional_env("ORBIT_LLM_MODEL") or DEFAULT_MODEL

    system = _load_status_prompt()
    payload = _status_payload(context)
    user = (
        "Studio-wide status data follows as JSON. Use only this data. "
        "Return plain text only, following the structure in the system "
        "prompt.\n\n"
        f"```json\n{json.dumps(payload, indent=2, default=str)}\n```"
    )

    try:
        resp = client.chat.completions.create(
            model=chosen_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
        )
    except Exception as exc:
        raise LLMError(f"LLM request failed: {exc}") from exc

    content = (resp.choices[0].message.content or "").strip()
    if not content:
        raise LLMError("LLM returned empty response")
    return content


def _load_status_prompt() -> str:
    try:
        return resources.files("orbit.prompts").joinpath("status.md").read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise LLMError("Prompt template not found: status.md") from exc


# Re-exported for tests and tooling that want to write a report without rerunning.
def write_report(report: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")
