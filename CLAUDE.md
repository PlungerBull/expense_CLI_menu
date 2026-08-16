# expense_CLI_menu — CLAUDE.md

> Repo name note: `_menu` is historical — the questionary menu was deleted at Step 10.X. There is no menu package; the interactive surface is the Textual TUI (`expense world`).

## What this repo is

The Hands. A Python (Typer) CLI that talks to the `expense_world_engine` via its HTTPS API. Every command is a thin wrapper around one or more engine endpoints. Zero business logic lives here — if the engine doesn't do it, the CLI can't either.

## Product scope and role

This CLI is **the first of four clients** that will share the same engine (per the engine's roadmap: engine → CLI → web dashboard → iOS). The engine is the source of truth for every business rule; clients are equal in the sense that none of them implement logic — but **the CLI is unequal in purpose**: it exists to exercise every engine endpoint through real human use before second-client (web/iOS) development begins.

Implications for every decision in this repo:

- **The CLI is a contract validator.** Each command we ship is a real-world test of an engine endpoint. If a 422 hint, sign convention, idempotency replay, or field-locking semantic is wrong, we want to find out via CLI use, not via mobile users.
- **No CLI-only shortcuts.** Anything that would only make sense for a CLI user (e.g. parsing engine-side logic client-side because "the CLI doesn't need pagination") has to be rejected. The pattern has to generalize to the next client.
- **Idempotency, error envelope, sign convention, date handling are shared infrastructure.** They were designed multi-client from day one (RFC 3339, signed amounts, structured error envelope) — the CLI uses them faithfully so iOS and web inherit working patterns, not just specs.
- **What stays CLI-specific:** [expense/dates.py](expense/dates.py) (CLI-only date forgiveness), [expense/_editor.py](expense/_editor.py) (terminal editor flow for `reconcile reorder`), `~/.expense-config` (filesystem token storage). Mobile and web will solve these problems differently and that's fine — the engine doesn't see the difference.

10,000-user scale is **not** a near-term goal of this repo. The end-state of this CLI is "feature-complete + a power-user surface for the same product non-developers will use via mobile/web." Distribution, multi-tenant scaling, billing, onboarding, localization — all of that lands on web/iOS, not here.

## Key documentation

| Doc | What it contains | Location |
|---|---|---|
| [docs/cli-spec.md](docs/cli-spec.md) | Command groups, output conventions, open questions | Local |
| [docs/cli-runtime.md](docs/cli-runtime.md) | CLI runtime behavior — read/write semantics, error handling, working against the live engine | Local |
| [docs/roadmap.md](docs/roadmap.md) | Step-by-step CLI build order + per-step status | Local |
| [docs/tui-plan.md](docs/tui-plan.md) | Textual TUI (`expense world`) — architecture, phases, keymap contract, status | Local |
| [docs/backlog.md](docs/backlog.md) | The **single open-work queue** — the phased engine-rework recovery plan + surviving polish items (merged 2026-08-15; the worked-off 2026-07-02 review lives in git history at `2d42482`) | Local |
| [docs/client-breaking-changes.md](docs/client-breaking-changes.md) | Engine-change record: every 2026-08 rework entry, what broke, what the client must do — the reference behind backlog Phases 1–6 (moved from the engine repo 2026-08-15) | Local |
| [docs/decisions.md](docs/decisions.md) | Decision record — why the big calls were made, **including rejected alternatives**; index links whys that live elsewhere | Local |
| [docs/mockups/](docs/mockups/) | HTML mockups — the approval gate for every screen and table | Local |
| `engine-spec.md` | Every endpoint, every business rule — the API contract the CLI consumes | [../expense_world_engine/docs/engine-spec.md](../expense_world_engine/docs/engine-spec.md) |
| `design-philosophy.md` | Product vision shared across all clients | [../expense_world_engine/docs/design-philosophy.md](../expense_world_engine/docs/design-philosophy.md) |
| `lessons-*.md` | UX lessons from YNAB, Lunch Money, TickTick, Todoist, Splitwise | [../expense_world_engine/docs/](../expense_world_engine/docs/) |

Engine docs are **referenced, not copied**. Single source of truth lives in the engine repo, assumed to sit as a **sibling checkout** (`../expense_world_engine` — see README "Checkout layout"). Same rule inside this repo: **each fact has one home** — status lives in roadmap/tui-plan/backlog, this file points at it. When you ship something, update the owning doc, not (only) this one.

Docs must outlive any one contributor, session, or AI model. Three durability rules: **(1) fresh-clone test** — every doc must work with zero conversation history; if acting on something needs unwritten context, write the context down (decision rationale, with rejected alternatives, goes in [docs/decisions.md](docs/decisions.md)). **(2) Executable beats prose** — when a convention can be checked mechanically, add a guard test next to the existing ones ([tests/unit/test_command_surface.py](tests/unit/test_command_surface.py), [tests/unit/test_tui_theme.py](tests/unit/test_tui_theme.py), [tests/unit/test_docs_links.py](tests/unit/test_docs_links.py) for doc link rot). **(3) Absolute dates only** — never "recently" or "last week".

## Dev loop

- **Single branch — `main` only.** This repo has exactly one branch; no feature branches exist. Commit and push straight to `main` (this overrides any default "branch first" habit). CI runs on push to `main`; if a change needs isolating, use a throwaway git worktree, not a branch that outlives the work.
- **Install:** `pip install -e ".[dev]" -c constraints.txt` — entry point is `expense` (TUI via `expense world`). `constraints.txt` pins the direct deps CI installs; refresh = bump a pin, land on `main` on green CI.
- **Test:** `pytest tests/unit` (fast, respx-mocked, hermetic — an autouse fixture in [tests/unit/conftest.py](tests/unit/conftest.py) redirects `EXPENSE_CONFIG`; never bypass it). `tests/contract/` hits the **live engine** (the local deployment, since 2026-07-30), gated on `PYTEST_LIVE=1` (+ `EXPENSE_PAT`) — never set casually.
- **Lint/format/types:** `ruff check . && ruff format .` plus scoped `mypy` (permissive, `[tool.mypy]` covers `http.py`/`config.py`/`errors.py` — widen as modules get annotated). CI (matrix 3.11/3.12/3.13, deps pinned via `constraints.txt`) enforces ruff check + format, mypy, and `pytest tests/unit --cov` (coverage reported, not gated); pre-commit runs gitleaks + ruff `--fix` + ruff-format + mypy. Line length 100, target py311.
- **Careful running live:** plain `expense …` commands use the developer's real `~/.expense-config` and hit the live engine — since 2026-07-30 that's the local deployment (`127.0.0.1:8000`, engine repo `deploy/local/`), and it is the one true ledger. Don't run writes ad hoc. Full ops guide — isolation levers, PAT provisioning, what the contract suite actually does: [docs/cli-runtime.md](docs/cli-runtime.md) "Working against the live engine".
- **Env vars:** `EXPENSE_CONFIG` (config path override), `PYTEST_LIVE=1` (contract tests).

## Tech stack

- **Language:** Python 3.11+
- **CLI framework:** Typer · **TUI framework:** Textual · **HTTP client:** httpx
- **Importer:** `expense import` (.xlsx via `openpyxl`, optional extra `[import]`) — package [expense/import_/](expense/import_/)
- **Config storage:** `~/.expense-config` (chmod 600) — the CLI's only local state
- **No local cache.** All reads and writes are live calls against the loopback engine. The Step-7b SQLite replica was deleted 2026-08-06 together with the engine's `GET /sync` (engine rework WP4) — see [docs/decisions.md](docs/decisions.md) "Delete the local replica". No offline write queue either (a per-client commitment for a future mobile client, never inherited). Why: single source of truth = no conflict resolution, no staleness, no CRDTs — every client inherits the same simple `request → wait → done` contract.

## Non-negotiable conventions

**Thin wrapper**
Every command parses args → calls an engine endpoint → formats output. No caching, no balance math, no validation beyond "do these flags make sense together."

**Sign convention**
Input and output are both signed (`debit_as_negative`): negative = expense, positive = income. The CLI is the caller-side preference layer the engine spec references.

**Human default, JSON opt-in**
Every read command supports `--json` for machine-readable output. Human mode may prettify; `--json` is always the raw engine response, passed through verbatim.

**Idempotency on every write**
The HTTP client mints a UUID per logical write and sets `X-Idempotency-Key`; timed-out/5xx writes auto-retry (bounded) with the **same** key, so a retry — manual or automatic — must never double-apply. Details in [docs/cli-runtime.md](docs/cli-runtime.md).

**Engine errors surface cleanly**
The engine's standard error shape (`{ error: { code, message, fields } }`) is rendered to the user. Never swallow, never reformat lossily.

**Confirm destructive operations**
Deletes and reverts prompt for confirmation unless `--yes` is passed. Archive, unarchive, and restore are prompt-free — reversible toggles, not destruction (archive reclassified 2026-07-11; rationale in [docs/decisions.md](docs/decisions.md)).

**Config isolation**
Auth token + engine URL live in `~/.expense-config`. Never checked in, never shared across machines. The GitHub repo (`PlungerBull/expense_CLI_menu`) is **public** by deliberate choice — which makes this rule non-negotiable: any secret committed is immediately public and permanent in git history. GitHub push protection is enabled as defense-in-depth, but the primary safeguard is that credentials never enter the repo in the first place.

**Mock every screen before building it — every time**
Before writing or changing UI code for any user-facing view or screen — a menu, dashboard, list, form, report, or TUI screen, anything the user will see — first present its **HTML mockup in [docs/mockups/](docs/mockups/)** and wait for the user's review. Do this **every time you pick up a screen, even one approved before** — a prior approval is not a standing license to skip the review; the user re-reads the mockup each session to make specific observations. **Showing mockups is not approval:** never implement (even in auto-accept mode) until the user explicitly picks one. This includes CLI tables: any new `<resource> list` renderer or column change needs a proposed column set + sign-off first (process rule in [docs/cli-spec.md](docs/cli-spec.md)). Never assume layout, fields, or behavior: when a detail is unspecified or ambiguous, **stop and ask**.

**One copy of everything shared**
The TUI imports `fetch_*` and formatters from `expense/commands/*` — shared read/format helpers live in [expense/commands/_resource.py](expense/commands/_resource.py), TUI write plumbing in [expense/tui/screens/_base.py](expense/tui/screens/_base.py) (`EngineWriteMixin.run_write`), form scaffolding in [expense/tui/screens/_form.py](expense/tui/screens/_form.py). Never duplicate fetch/format/write logic between CLI and TUI; extend the shared helper instead.

**No literal colors in the TUI**
All TUI color goes through theme tokens (`resolve_palette`), never hard-coded hex/ANSI in widgets. A guard test enforces this; see [docs/tui-plan.md](docs/tui-plan.md).

**Themes recolor the foreground, never the base surface**
The TUI runs in ANSI mode — the base fill is the terminal's *own* background (`ansi_default`, set structurally in [expense/tui/app.tcss](expense/tui/app.tcss)), so it's seamless on any terminal. A theme changes **foreground + semantic-span colors only** (text, accents, sign-colors, selection/diff highlights); it must **never** paint a full-screen/base background, which would bring back the terminal seam *and* break any light/dark/auto theme (one fixed surface can't match every terminal). Guard: `test_base_fills_are_terminal_transparent`; the principle + the Claude-Code parallel it's modeled on live in [docs/tui-plan.md](docs/tui-plan.md) §4.

**Testing conventions**
Every new command lands with at least one happy-path + one error-shape unit test. [tests/unit/test_command_surface.py](tests/unit/test_command_surface.py) is the surface armor — every command needs a docstring with an `Example:` block, `--json` on reads, `--yes` on destructive writes; a new command that skips these fails loudly.

## Status

Flat CLI is **complete** (Steps 0–9, plus the `.xlsx` bulk importer `expense import` and `rates list`); every engine endpoint with a CLI surface is wrapped and regression-armored. The questionary `expense menu` shipped at Step 9.5 and was **deleted at Step 10.X (2026-07-02)** — flat commands stay the canonical contract-validator surface; the Textual TUI `expense world` (Step 10) is the interactive surface on the same fetch/write layer. TUI read views and write flows are shipped (Phase 2 closed 2026-07-08 with the Monthly-report screen — every home-menu entry is wired); the 2026-07-02 quality review was fully worked off. **Open — and urgent:** the 2026-08 engine rework broke parts of the CLI/TUI surface (transfers, reconciliation chaining, several flags now 422/404); the phased recovery plan **is** the active backlog: [docs/backlog.md](docs/backlog.md), with per-entry contract detail in [docs/client-breaking-changes.md](docs/client-breaking-changes.md). After recovery: additive engine features (inbox hashtags, People API), `?` help overlay, command palette, light/`NO_COLOR` theme, then post-Step-9 ergonomics (quick-add parser, shell completions). Live detail: [docs/roadmap.md](docs/roadmap.md) (step table) · [docs/tui-plan.md](docs/tui-plan.md) (TUI phases) · [docs/backlog.md](docs/backlog.md) (active backlog).
