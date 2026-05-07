<div align="center">
  <h1>Orbit</h1>
  <p style="font-size:16px;font-weight:normal;">Cross-venture engineering intelligence for studio teams</p>
</div>

<div align="center">
  <p align="center">
    <a href="#introduction">Introduction</a> &nbsp;&bull;&nbsp;
    <a href="#system-overview">System Overview</a> &nbsp;&bull;&nbsp;
    <a href="#getting-started">Getting Started</a> &nbsp;&bull;&nbsp;
    <a href="#cli-reference">CLI Reference</a> &nbsp;&bull;&nbsp;
    <a href="#design-principles">Design Principles</a> &nbsp;&bull;&nbsp;
    <a href="#contributing--local-development">Contributing</a> &nbsp;&bull;&nbsp;
    <a href="#limits">Limits</a>
  </p>
</div>

## Introduction

### The problem

Studios run multiple ventures in parallel, and the engineering activity is fragmented across repos. 

* An engineering lead needs operational detail. 

* A co-founder needs product-level clarity. 

* Studio leadership needs the portfolio view. 

Producing those three views by hand means scanning GitHub once a week and rewriting the same activity in three different voices.

### What is Orbit?

**Orbit** is a CLI tool that performs the cross-venture scanning and does the first drafting.

It pulls structured engineering activity from every configured venture's repository, applies inspectable deterministic rules to flag operational risks, and uses an LLM to translate the result into Markdown drafts for each audience. 

The same pipeline answers personal queries: "*what did I ship last week?*" "*what changed while I was away?*" "*what's everyone working on right now?*"

**The LLM translates and synthesises. It does not detect, judge, or invent.** Risk signals and confidence levels are computed in plain Python before the LLM is called, and every material claim is cited inline back to the PR, issue, or commit that supports it.

> **"A drafting tool, not a replacement for communication"**

**Orbit** produces reviewable first drafts; it does not send them. The conversations that move ventures forward still happen between humans, and they should. 

Use **Orbit** before the meeting. Read the draft, edit what the model misjudged, drop what isn't relevant, add what the tool can't see, then share. 

**Orbit** earns trust by being verifiable, not by being autonomous.

### See it in action!

Before installing anything, here's what Orbit actually produces. Each example below was generated against the [bundled fixture](examples/fixture_activity.json), a fictional venture activity covering three studio companies in three different states (*healthy, mid-momentum, blocked*).

A taste — the status overview from the leadership report:

| Venture          | Status | Confidence | Headline                                                              |
|------------------|:------:|:----------:|-----------------------------------------------------------------------|
| Helios Health    |   🟢   |    High    | Compliance and onboarding work advanced, with CI succeeding.          |
| Atlas Logistics  |   🟡   |   Medium   | Delivery is moving, but review backlog and ETA drift need attention.  |
| Lumen Edu        |   🔴   |    Low     | Launch-blocking mobile issues and failed CI outweigh limited activity.|

View the full rendered outputs in [`examples/`](./examples/):

- [`leadership-report.md`](./examples/leadership-report.md) — portfolio traffic-light view with cross-venture observations
- [`founder-report.md`](./examples/founder-report.md) — per-venture co-founder update framed against the milestone
- [`engineering-report.md`](./examples/engineering-report.md) — operational lead report with shipped PRs, blockers, and CI health

> [!NOTE] Important to know!
> 📝 Every linked claim in those reports is a real evidence item from the fixture. URLs come directly from the snapshot, similar to citations. Orbit **cannot** invent or modify them!

---

## System Overview

### How it works

```text
GitHub API (commits, PRs, issues, CI)
↓
Structured evidence (normalised, per-venture)
↓
Deterministic risk signals (review backlog, CI failure, blockers, low activity)
↓
Deterministic confidence levels (High / Medium / Low, rule-based)
↓
LLM audience translation (engineering / founder / leadership)
↓
Reviewable Markdown report with inline reference-style citations
```

Risk detection and confidence assignment happen in plain Python before the LLM ever sees the data. 

The LLM's only job is audience translation: turning structured evidence into language that fits the reader. Every claim it makes is anchored to a real PR, issue, commit, or workflow run via a reference-style link, so a reviewer can verify and perform further inspection for any sentence with one click.

### Tech Stack

![Tech Stack (Language)](https://img.shields.io/badge/language%3A-222222?style=for-the-badge) &nbsp; ![Python Badge](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&labelColor=222222)

![Tech Stack (CLI & UX)](https://img.shields.io/badge/cli_&_ux%3A-222222?style=for-the-badge) &nbsp; ![Typer Badge](https://img.shields.io/badge/Typer-009485?style=for-the-badge&logo=typer&labelColor=222222) ![Rich Badge](https://img.shields.io/badge/Rich-FAE742?style=for-the-badge&labelColor=222222)

![Tech Stack (Data & Validation)](https://img.shields.io/badge/data_&_validation%3A-222222?style=for-the-badge) &nbsp; ![Pydantic Badge](https://img.shields.io/badge/Pydantic-E92063?style=for-the-badge&logo=pydantic&labelColor=222222) ![PyYAML Badge](https://img.shields.io/badge/PyYAML-CB171E?style=for-the-badge&logo=yaml&labelColor=222222)

![Tech Stack (Integrations)](https://img.shields.io/badge/integrations%3A-222222?style=for-the-badge) &nbsp; ![GitHub API Badge](https://img.shields.io/badge/GitHub_REST_API-181717?style=for-the-badge&logo=github&labelColor=222222) ![OpenAI Badge](https://img.shields.io/badge/OpenAI-412991?style=for-the-badge&logo=openai&labelColor=222222) ![httpx Badge](https://img.shields.io/badge/httpx-2C5BB4?style=for-the-badge&labelColor=222222)

![Tech Stack (Quality)](https://img.shields.io/badge/quality%3A-222222?style=for-the-badge) &nbsp; ![pytest Badge](https://img.shields.io/badge/pytest-0A9EDC?style=for-the-badge&logo=pytest&labelColor=222222) ![Ruff Badge](https://img.shields.io/badge/Ruff-D7FF64?style=for-the-badge&logo=ruff&labelColor=222222) ![Mypy Badge](https://img.shields.io/badge/mypy-1F5082?style=for-the-badge&labelColor=222222)

---

## Getting Started

### Pre-requisites

- [Python 3.11+](https://www.python.org/downloads/)
- [`pipx`](https://pipx.pypa.io/stable/installation/) (recommended — installs CLIs in isolated environments)
- A GitHub personal access token with read access to the configured repos. Fine-grained tokens need read-only access to **Pull requests**, **Issues**, **Contents**, and **Actions**.
- An OpenAI API key.

### 1. Install Orbit

Install the latest tagged release directly from GitHub:

```bash
pipx install git+https://github.com/callmegerlad/orbit-cli.git@v0.1.0
```

> 📝 Tip: Replace `v0.1.0` with the latest tag listed on the [releases page](https://github.com/callmegerlad/orbit-cli/releases). To upgrade, run `pipx upgrade orbit-cli`.

If you don't have `pipx`, plain `pip` also works:

```bash
pip install git+https://github.com/callmegerlad/orbit-cli.git@v0.1.0
```

Verify the install:

```bash
orbit --version
```

### 2. Configure secrets

Orbit reads `GITHUB_TOKEN` and `OPENAI_API_KEY` from the environment. The simplest setup is a `.env` file in whatever directory you'll run Orbit from:

```bash
cat > .env <<'EOF'
GITHUB_TOKEN=<your-github-token>
OPENAI_API_KEY=<your-openai-api-key>
EOF
```

Or export them in your shell:

```bash
export GITHUB_TOKEN=<your-github-token>
export OPENAI_API_KEY=<your-openai-api-key>
```

> ⚠️ Warning: Never commit `.env` and never pass secrets as CLI arguments.

### 3. Initialise your studio config

```bash
orbit init
```

This walks you through naming the studio, the default reporting period, and one or more ventures with their repos, milestone, and watch items. The result is a validated `orbit.yaml` in your working directory.

### 4. Validate the setup

```bash
orbit validate
```

This checks the config, looks up your GitHub token, and verifies repo access for each configured venture. The output ends with a green `🚀 Orbit is ready to launch with this config!` when everything checks out.

### 5. Generate a report

Run against live GitHub data:

```bash
orbit report engineering -o reports/engineering.md
orbit report founder --venture helios-health -o reports/founder.md
orbit report leadership -o reports/leadership.md
```

> 📝 Tip: Splitting `collect` and `report` lets you generate all three audience reports from a single GitHub fetch — useful when iterating on prompts.

### Try Orbit without setting up GitHub

The repository ships a fixture snapshot of fictional venture activity, so you can see what Orbit produces without configuring `orbit.yaml` or a GitHub token. You'll still need `OPENAI_API_KEY` set, since the LLM call runs.

```bash
# Grab the fixture from the repo
curl -L -o fixture_activity.json \
  https://raw.githubusercontent.com/callmegerlad/orbit-cli/v0.1.0/examples/fixture_activity.json

# Generate any of the three reports
orbit report leadership   --fixture fixture_activity.json
orbit report engineering  --fixture fixture_activity.json
orbit report founder --venture helios-health --fixture fixture_activity.json
```

---

## Contributing / Local Development

If you want to read the source, run the tests, or change behaviour, install the package in editable mode:

```bash
git clone https://github.com/callmegerlad/orbit-cli.git
cd orbit-cli
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

cp .env.example .env                 # then fill in GITHUB_TOKEN and OPENAI_API_KEY
cp orbit.example.yaml orbit.yaml     # then edit your studio + ventures
```

### Tests, lint, type-check

```bash
pytest                               # 75 tests, no network access required
ruff check src tests
mypy src
```

The test suite covers config validation, every risk and confidence rule, fixture round-tripping, prompt loading, the LLM payload builder, and end-to-end CLI commands (with the LLM and GitHub collector stubbed).

```text
tests/
  conftest.py            Shared fixtures (CliRunner, snapshot factory, config writer)
  test_config.py         YAML validation, period parsing, add/update/remove
  test_risk.py           Each risk rule + confidence-level transitions
  test_fixtures.py       Snapshot JSON round-trip
  test_llm.py            Prompt loader, citation construction
  test_cli.py            init, validate, venture add/update/remove/list/details
  test_cli_helpers.py    _split_csv, _github_failure_message, _config_warnings, etc.
  test_report_cli.py     report and collect commands with stubs
```

### Modules

```
src/orbit/
  cli.py            Typer entrypoint and command surface
  config.py         Strict YAML loader, validation, and edit helpers
  models.py         Pydantic models — EvidenceItem, RiskSignal, *Snapshot
  github.py         Async httpx GitHub REST client
  collector.py      GitHub responses → normalised evidence
  risk.py           Deterministic risk signal rules
  confidence.py     Deterministic High / Medium / Low rules
  reporter.py       Annotates snapshots with signals + confidence
  query.py          Pull-mode data builders + Rich rendering (orbit me, catchup, status)
  llm.py            OpenAI synthesis for reports, catchup briefs, and status snapshots
  fixtures.py       Snapshot save / load (JSON)
  runtime.py        .env loading, env-var helpers
  prompts/          Markdown prompt templates
    _shared.md         Hard rules shared by every audience report
    engineering.md     Operational lead report
    founder.md         Per-venture co-founder report
    leadership.md      Portfolio-level studio report
    catchup.md         "What changed while I was away?" brief
    status.md          Studio-wide right-now snapshot
```

#### `cli` — Typer entrypoint and command surface
Seven top-level commands (`init`, `validate`, `collect`, `report`, `me`, `catchup`, `status`) plus `venture` and `settings` subgroups for config edits. Interactive prompts where they help, flags where automation matters. Every error path exits non-zero with a clean stderr message and never leaks raw stack traces from libraries.

#### `config` — strict YAML loader
Configuration is the contract between the user and the tool. Unknown keys are rejected, repos must match `owner/name`, periods must match `\d+[dhw]` (e.g. `7d`, `2w`, `48h`), venture ids must be lowercase-hyphenated, and duplicate ids or names are caught at load time. Edit helpers (`add_venture`, `update_venture`, `update_studio`, `update_defaults`) re-validate the whole config before writing — there is no path that produces an invalid `orbit.yaml` on disk.

#### `github` + `collector` — input pipeline
An async `httpx`-based client scoped to the five endpoints Orbit actually uses (repo metadata, pull requests, issues, commits, workflow runs). Responses are normalised into a single `EvidenceItem` shape — same fields whether the source is a PR or a commit — so the rest of the pipeline never reads raw GitHub JSON. PR comment counts (regular and review-thread) are captured into `raw_metadata` so `orbit me` can show "open, 3 comments" without an extra request.

#### `risk` + `confidence` — deterministic detection
Pure functions of a `VentureSnapshot`. No I/O, no LLM, no clock reads beyond `datetime.now(UTC)`. Adding a rule is a one-file change with a unit test for both the triggering case and at least one near-miss. The current ruleset covers `review_backlog`, `delivery_risk`, `ci_unhealthy`, `low_activity`, and `declining_momentum`. Confidence levels (`High` / `Medium` / `Low`) derive from the signal set — the LLM is shown the level as a fixed input and forbidden from overriding it.

#### `query` — pull-mode views
Backs the `me`, `catchup`, and `status` commands. Three pure builders over a `StudioSnapshot`:

- `build_my_activity` — filters evidence by author across all (or selected) ventures, groups PRs by state, computes commit breakdowns and last-touched timestamps. Rendered directly as Rich panels in this module — no LLM call.
- `build_catchup` — splits one venture's evidence into "changes by others" (what shipped while you were away) and "your open work" (so the LLM can flag possible conflicts). Pre-computes contributor counts and label tallies.
- `build_status` — reuses the snapshot's already-annotated risk signals to produce a per-venture status context (open PRs, stale PRs, critical issues, CI health) that the LLM phrases as one-line summaries plus optional cross-venture observations.

`me` is fully deterministic. `catchup` and `status` hand their pre-computed contexts to `llm.py` for synthesis.

#### `llm` — output synthesis
Three render paths, one OpenAI client. `render_report` produces audience-specific Markdown with reference-style citations (`[#41][issue-41]` plus a definition block) — this is the audit-grade output meant for sharing. `render_catchup` and `render_status` produce plain text with bare PR/issue numbers (`#41`, `(#22)`) — quick-scan format. In all three, citation labels and definitions are pre-computed in Python so the model can only ever cite items that actually exist; URLs come verbatim from `EvidenceItem.url`. Prompts live in `prompts/` as Markdown files, loaded via `importlib.resources`, so iterating on tone or rules never requires touching Python code.

---

## CLI Reference

| Command | Purpose |
|---|---|
| `orbit init` | Guided creation of `orbit.yaml`. `--force` overwrites an existing file. |
| `orbit validate` | Validate the config, then check GitHub token + repo access. |
| `orbit collect` | Fetch a GitHub snapshot and save it as JSON. `--period 7d`, `-o snapshot.json`. |
| `orbit report engineering` | Operational report across all ventures. |
| `orbit report founder --venture NAME` | Product-level report for one venture. Required `--venture`. |
| `orbit report leadership` | Portfolio-level traffic-light report. |
| `orbit me` | What you personally worked on across all ventures. `--period`, `--user`, `--venture` (repeatable or comma-separated), `--fixture`. |
| `orbit catchup --venture venture-id` | Plain-text "what changed while I was away?" brief, one section per venture. Excludes your own commits and flags possible conflicts with your open PRs. `--since 7d` (also accepts `2w`, `48h`), `--user`, `--venture` (repeatable/CSV), `--fixture`. |
| `orbit status` | Studio-wide snapshot: one terse line per venture (open PRs, stale reviews, sprint focus, blockers) plus optional cross-venture observations. `--period 7d`, `--venture` (repeatable/CSV), `--fixture`. |
| `orbit venture add` | Add a venture (interactive or with `--name --id --repo --milestone --watch-item`). |
| `orbit venture update` | Update repos, stakeholder, milestone, or watch items. |
| `orbit venture remove` | Remove a venture (refuses to remove the last one). |
| `orbit venture list` | Compact table of configured ventures. |
| `orbit venture details` | Detailed view of one venture's reporting context. |

Common options across `orbit report`:

| Option | What it does |
|---|---|
| `--period 7d` | Lookback window. Accepts e.g. `7d`, `24h`. |
| `--fixture FILE` | Use a saved snapshot instead of calling GitHub. |
| `-o, --output FILE` | Write Markdown to a file instead of stdout. |
| `--raw` | Print Markdown without terminal rendering. |

Run `orbit --help` or `orbit <command> --help` for the full surface.

---

## Design Principles

| Principle | Implementation |
|---|---|
| **Determinism before synthesis** | Risk signals (`risk.py`) and confidence levels (`confidence.py`) are pure functions of a `VentureSnapshot`. The LLM receives them as fixed inputs. |
| **Evidence-grounded output** | Every material claim in a generated report carries a reference-style Markdown citation (`[#41][issue-41]`) whose URL comes verbatim from a collected `EvidenceItem`. |
| **Strict input validation** | `orbit.yaml` is rejected on unknown keys, malformed repos, duplicate ids, or invalid period strings. Errors surface as a single readable line at the CLI. |
| **Secrets via env only** | `GITHUB_TOKEN` and `OPENAI_API_KEY` are read from environment / `.env` only. Never CLI flags, never logged, `.env` is gitignored. |
| **Hermetic tests** | The 127-test suite never hits the network. The OpenAI call and the GitHub collector are stubbed via `monkeypatch` in CLI tests; pure rules and helpers are tested directly. |
| **Drafts, not deliveries** | Orbit produces reviewable Markdown. There is no auto-send to Slack, email, or anywhere else. The human stays in the loop by design. |

---

## Limits

Orbit is deliberately scoped. A few things it does **not** do, and why.

- **It is not a measure of progress.** 40 commits can be churn, and 2 commits can unlock a launch. Orbit reports activity and flags signals. Judging significance still requires a human with product context.
- **It only sees the GitHub-visible slice.** Founder calls, design reviews, customer discovery, and strategic pivots are invisible to the tool. A quiet engineering week is not always a problem.
- **The founder report carries the most hallucination risk.** It bridges the widest gap between raw data and product meaning. Inline citations make it easier to verify, but a human review step before sharing remains non-negotiable.
- **Report quality depends on input quality.** PR titles like "fix stuff" produce vague reports. This is also a feedback loop, vague output exposes vague engineering communication, promoting better documentation.

---

## License

This project was built as an internal tool and is shared here for review and reference.
