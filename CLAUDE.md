# expense_CLI_menu — CLAUDE.md

> Repo name note: `_menu` is historical — the questionary menu was deleted at Step 10.X. There is no menu package; the interactive surface is the Textual TUI (`expense world`).

## What this repo is

The Hands. A Python (Typer) CLI that talks to the `expense_world_engine` via its HTTPS API. Every command is a thin wrapper around one or more engine endpoints. Zero business logic lives here — if the engine doesn't do it, the CLI can't either.

## Product scope and role

This CLI is **the first of four clients** that will share the same engine (per the engine's roadmap: engine → CLI → web dashboard → iOS). The engine is the source of truth for every business rule; clients are equal in the sense that none of them implement logic — but **the CLI is unequal in purpose**: it exists to exercise every engine endpoint through real human use before second-client (web/iOS) development begins.

Implications for every decision in this repo:

- **The CLI is a contract validator.** Each command we ship is a real-world test of an engine endpoint. If a 422 hint, sign convention, idempotency replay, or field-locking semantic is wrong, we want to find out via CLI use, not via mobile users.
- **No CLI-only shortcuts.** Anything that would only make sense for a CLI user (e.g. parsing engine-side logic client-side because "the CLI doesn't need pagination") has to be rejected. The pattern has to generalize to the next client.
- **Sync, idempotency, error envelope, sign convention, date handling are shared infrastructure.** They were designed multi-client from day one (`X-Client-Id`, RFC 3339, signed amounts, structured error envelope) — the CLI uses them faithfully so iOS and web inherit working patterns, not just specs.
- **What stays CLI-specific:** [expense/dates.py](expense/dates.py) (CLI-only date forgiveness), [expense/_editor.py](expense/_editor.py) (terminal editor flow for `reconcile reorder`), `~/.expense-config` (filesystem token storage). Mobile and web will solve these problems differently and that's fine — the engine doesn't see the difference.

10,000-user scale is **not** a near-term goal of this repo. The end-state of this CLI is "feature-complete + a power-user surface for the same product non-developers will use via mobile/web." Distribution, multi-tenant scaling, billing, onboarding, localization — all of that lands on web/iOS, not here.

## Key documentation

| Doc | What it contains | Location |
|---|---|---|
| [docs/cli-spec.md](docs/cli-spec.md) | Command groups, output conventions, open questions | Local |
| [docs/cli-runtime.md](docs/cli-runtime.md) | CLI runtime behavior — sync model, write semantics, X-Client-Id lifecycle, cache phasing | Local |
| [docs/roadmap.md](docs/roadmap.md) | Step-by-step CLI build order + per-step status | Local |
| [docs/tui-plan.md](docs/tui-plan.md) | Textual TUI (`expense world`) — architecture, phases, keymap contract, status | Local |
| [docs/polish-backlog.md](docs/polish-backlog.md) | The **active** polish/quality backlog (currently the 2026-07-06 best-practices review; the worked-off 2026-07-02 review lives in git history at `2d42482`) | Local |
| [docs/decisions.md](docs/decisions.md) | Decision record — why the big calls were made, **including rejected alternatives**; index links whys that live elsewhere | Local |
| [docs/mockups/](docs/mockups/) | HTML mockups — the approval gate for every screen and table | Local |
| `engine-spec.md` | Every endpoint, every business rule — the API contract the CLI consumes | [../expense_world_engine/docs/engine-spec.md](../expense_world_engine/docs/engine-spec.md) |
| `api-design-principles.md` | Request/response conventions (error shape, null-over-omission, idempotency, sign) | [../expense_world_engine/docs/api-design-principles.md](../expense_world_engine/docs/api-design-principles.md) |
| `design-philosophy.md` | Product vision shared across all clients | [../expense_world_engine/docs/design-philosophy.md](../expense_world_engine/docs/design-philosophy.md) |
| `lessons-*.md` | UX lessons from YNAB, Lunch Money, TickTick, Todoist, Splitwise | [../expense_world_engine/docs/](../expense_world_engine/docs/) |

Engine docs are **referenced, not copied**. Single source of truth lives in the engine repo, assumed to sit as a **sibling checkout** (`../expense_world_engine` — see README "Checkout layout"). Same rule inside this repo: **each fact has one home** — status lives in roadmap/tui-plan/backlog, this file points at it. When you ship something, update the owning doc, not (only) this one.

Docs must outlive any one contributor, session, or AI model. Three durability rules: **(1) fresh-clone test** — every doc must work with zero conversation history; if acting on something needs unwritten context, write the context down (decision rationale, with rejected alternatives, goes in [docs/decisions.md](docs/decisions.md)). **(2) Executable beats prose** — when a convention can be checked mechanically, add a guard test next to the existing ones ([tests/unit/test_command_surface.py](tests/unit/test_command_surface.py), [tests/unit/test_tui_theme.py](tests/unit/test_tui_theme.py), [tests/unit/test_docs_links.py](tests/unit/test_docs_links.py) for doc link rot). **(3) Absolute dates only** — never "recently" or "last week".

## Dev loop

- **Single branch — `main` only.** This repo has exactly one branch; no feature branches exist. Commit and push straight to `main` (this overrides any default "branch first" habit). CI runs on push to `main`; if a change needs isolating, use a throwaway git worktree, not a branch that outlives the work.
- **Install:** `pip install -e ".[dev]" -c constraints.txt` — entry point is `expense` (TUI via `expense world`). `constraints.txt` pins the direct deps CI installs; refresh = bump a pin, land on `main` on green CI.
- **Test:** `pytest tests/unit` (fast, respx-mocked, hermetic — an autouse fixture in [tests/unit/conftest.py](tests/unit/conftest.py) redirects `EXPENSE_CONFIG`/`EXPENSE_CACHE`; never bypass it). `tests/contract/` hits the **live production engine**, gated on `PYTEST_LIVE=1` (+ `EXPENSE_PAT`) — never set casually.
- **Lint/format/types:** `ruff check . && ruff format .` plus scoped `mypy` (permissive, `[tool.mypy]` covers `http.py`/`config.py`/`errors.py`/`cache/` — widen as modules get annotated). CI (matrix 3.11/3.12/3.13, deps pinned via `constraints.txt`) enforces ruff check + format, mypy, and `pytest tests/unit --cov` (coverage reported, not gated); pre-commit runs gitleaks + ruff `--fix` + ruff-format + mypy. Line length 100, target py311.
- **Careful running live:** plain `expense …` commands use the developer's real `~/.expense-config` and hit the production engine. Don't run writes ad hoc. Full ops guide — isolation levers, PAT provisioning, what the contract suite actually does: [docs/cli-runtime.md](docs/cli-runtime.md) "Working against the live engine".
- **Env vars:** `EXPENSE_CONFIG`, `EXPENSE_CACHE` (path overrides), `EXPENSE_STATELESS=1` (bypass cache), `EXPENSE_NO_SYNC_AFTER=1` (skip post-write refresh), `PYTEST_LIVE=1` (contract tests).

## Tech stack

- **Language:** Python 3.11+
- **CLI framework:** Typer · **TUI framework:** Textual · **HTTP client:** httpx
- **Importer:** `expense import` (.xlsx via `openpyxl`, optional extra `[import]`) — package [expense/import_/](expense/import_/)
- **Config storage:** `~/.expense-config` (chmod 600)
- **Local cache (committed deliverable, not optional):** SQLite under `~/.expense-cache.sqlite3` per [api-design-principles.md §3b](../expense_world_engine/docs/api-design-principles.md) — cache-by-default, stateless escape hatch via `--no-cache` / `EXPENSE_STATELESS=1`. See [docs/cli-runtime.md](docs/cli-runtime.md).
- **Sync architecture — server-first, not local-first.** Writes go engine-direct over HTTPS; the local SQLite is a read-through replica only, never the origin of a write. No offline write queue (that's iOS-only per §3b; see [docs/cli-runtime.md](docs/cli-runtime.md)). Why: single source of truth = no conflict resolution, no CRDTs, no per-row vector clocks — every client inherits the same simple `POST → wait → done` contract.

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
Deletes, reverts, archives prompt for confirmation unless `--yes` is passed. (Unarchive and restore are prompt-free — they undo, not destroy.)

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

Flat CLI is **complete** (Steps 0–9, plus the `.xlsx` bulk importer `expense import` and `rates list`); every engine endpoint with a CLI surface is wrapped and regression-armored. The questionary `expense menu` shipped at Step 9.5 and was **deleted at Step 10.X (2026-07-02)** — flat commands stay the canonical contract-validator surface; the Textual TUI `expense world` (Step 10) is the interactive surface on the same fetch/write layer. TUI read views and write flows are shipped (Phase 2 closed 2026-07-08 with the Monthly-report screen — every home-menu entry is wired); the 2026-07-02 quality review was fully worked off. **Open:** the 2026-07-06 best-practices backlog, `?` help overlay, command palette, light/`NO_COLOR` theme; then post-Step-9 ergonomics (quick-add parser, shell completions). Live detail: [docs/roadmap.md](docs/roadmap.md) (step table) · [docs/tui-plan.md](docs/tui-plan.md) (TUI phases) · [docs/polish-backlog.md](docs/polish-backlog.md) (active backlog).
