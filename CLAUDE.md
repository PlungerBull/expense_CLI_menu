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
- **What stays CLI-specific:** [expense/dates.py](expense/dates.py) (CLI-only date forgiveness), [expense/quickadd/](expense/quickadd/) (the one-line quick-add grammar), [expense/import_/](expense/import_/) (the `.xlsx` reader), `~/.expense-config` (filesystem token storage). *(`expense/_editor.py` — the `$EDITOR` flow — was deleted 2026-08-16 with `reconcile reorder`, its only consumer, when the engine de-chained reconciliations.)* Mobile and web will solve these problems differently and that's fine — the engine doesn't see the difference.

10,000-user scale is **not** a near-term goal of this repo. The end-state of this CLI is "feature-complete + a power-user surface for the same product non-developers will use via mobile/web." Distribution, multi-tenant scaling, billing, onboarding, localization — all of that lands on web/iOS, not here.

## Key documentation

| Doc | What it contains | Location |
|---|---|---|
| [docs/cli-spec.md](docs/cli-spec.md) | Command groups, output conventions, open questions | Local |
| [docs/cli-runtime.md](docs/cli-runtime.md) | CLI runtime behavior — read/write semantics, error handling, working against the live engine | Local |
| [docs/tui.md](docs/tui.md) | Textual TUI (`expense world`) — architecture, theming, keymap contract, terminal sizes, test conventions | Local |
| [docs/todo.md](docs/todo.md) | The **single open-work queue** — the workpad. Open items only; closed work is deleted, git history is the archive | Local |
| [docs/decisions.md](docs/decisions.md) | Decision record — why the big calls were made, **including rejected alternatives**; index links whys that live elsewhere | Local |
| [docs/mockups/](docs/mockups/) | HTML mockups — the approval gate for every screen and table | Local |
| `engine-spec.md` | Every endpoint, every business rule — the API contract the CLI consumes | [../expense_world_engine/docs/engine-spec.md](../expense_world_engine/docs/engine-spec.md) |
| `design-philosophy.md` | Product vision shared across all clients | [../expense_world_engine/docs/design-philosophy.md](../expense_world_engine/docs/design-philosophy.md) |
| `lessons-*.md` | UX lessons from YNAB, Lunch Money, TickTick, Todoist, Splitwise | [../expense_world_engine/docs/](../expense_world_engine/docs/) |

Engine docs are **referenced, not copied**. Single source of truth lives in the engine repo, assumed to sit as a **sibling checkout** (`../expense_world_engine` — see README "Checkout layout"). Same rule inside this repo: **each fact has one home** — the command surface lives in cli-spec, the TUI in tui.md, open work in todo.md, and this file points at them. When you ship something, update the owning doc, not (only) this one.

Docs must outlive any one contributor, session, or AI model. Three durability rules: **(1) fresh-clone test** — every doc must work with zero conversation history; if acting on something needs unwritten context, write the context down (decision rationale, with rejected alternatives, goes in [docs/decisions.md](docs/decisions.md)). **(2) Executable beats prose** — when a convention can be checked mechanically, add a guard test next to the existing ones ([tests/unit/test_command_surface.py](tests/unit/test_command_surface.py), [tests/unit/test_tui_theme.py](tests/unit/test_tui_theme.py), [tests/unit/test_docs_links.py](tests/unit/test_docs_links.py) for doc link rot). **(3) Absolute dates only** — never "recently" or "last week".

## Dev loop

- **Single branch — `main` only.** This repo has exactly one branch; no feature branches exist. Commit and push straight to `main` (this overrides any default "branch first" habit). CI runs on push to `main`; if a change needs isolating, use a throwaway git worktree, not a branch that outlives the work.
- **Install:** `pip install -e ".[dev]" -c constraints.txt` — entry point is `expense` (TUI via `expense world`). `constraints.txt` pins the direct deps CI installs; refresh = bump a pin, land on `main` on green CI.
- **Test:** `pytest tests/unit` (fast, respx-mocked, hermetic — an autouse fixture in [tests/unit/conftest.py](tests/unit/conftest.py) redirects `EXPENSE_CONFIG`; never bypass it). `tests/contract/` hits a **real engine**, gated on `PYTEST_LIVE=1` (+ `EXPENSE_PAT`) — never set casually; since 2026-08-16 it **refuses to run against the real ledger** and expects the disposable `expense_world_test` engine on `:8001` (setup: engine repo `deploy/local/seed-test-user.sh`). Because unit tests mock the engine, they cannot see it change shape — `python scripts/check_fixture_drift.py` diffs every fixture key against the engine's published `openapi.json`; run it after any engine change.
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

**No literal colors in the TUI — and no authored ones either**
All TUI color goes through theme tokens — CSS uses `$accent`/`$secondary`/`$error`; Rich content takes the `PALETTE` constant ([theme.py](expense/tui/theme.py)) — never hard-coded hex/ANSI in widgets. A guard test enforces this; see [docs/tui.md](docs/tui.md) §3. Since 2026-08-19 the tokens themselves are **ANSI slots**, not hexes: the terminal supplies every colour, which is what makes the app readable on light and dark terminals without detecting anything. A hex in [theme.py](expense/tui/theme.py) would pin the app back to one terminal — guarded by `test_theme_is_ansi_slots_not_hexes`.

**Themes recolor the foreground, never the base surface**
The TUI runs in ANSI mode — the base fill is the terminal's *own* background (`ansi_default`, set structurally in [expense/tui/app.tcss](expense/tui/app.tcss)), so it's seamless on any terminal. A theme changes **foreground + semantic-span colors only** (text, accents, sign-colors, selection/diff highlights); it must **never** paint a full-screen/base background, which would bring back the terminal seam *and* break any light/dark/auto theme (one fixed surface can't match every terminal). Guard: `test_base_fills_are_terminal_transparent`; the principle + the Claude-Code parallel it's modeled on live in [docs/tui.md](docs/tui.md) §3.

**Testing conventions**
Every new command lands with at least one happy-path + one error-shape unit test. [tests/unit/test_command_surface.py](tests/unit/test_command_surface.py) is the surface armor — every command needs a docstring with an `Example:` block, `--json` on reads, `--yes` on destructive writes; a new command that skips these fails loudly.

## Status

Both surfaces are **complete and verified.** The flat CLI wraps every engine endpoint that has a CLI surface, regression-armored (gate closed 2026-05-10, plus the `.xlsx` bulk importer `expense import` and `rates list`). The Textual TUI `expense world` covers the same ground on the same fetch/write layer — every home-menu entry is wired, no stubs. The questionary `expense menu` that preceded it was **deleted 2026-07-02**; flat commands stay the canonical contract-validator surface.

**Recovery from the 2026-08 engine rework is complete and verified** (2026-08-16), gated on the contract suite passing against a real engine — the first such check since the rework. The additive capability that followed it (inbox hashtags, the People API) shipped the same day, and the polish tail closed over four passes: the deleted-rows column (2026-08-16), the `?` help overlay with the command palette removed (2026-08-17), the `pilot.pause` sweep (2026-08-18, every TUI pilot test now waits on a condition rather than the clock — guarded by [tests/unit/test_suite_hygiene.py](tests/unit/test_suite_hygiene.py)), the ANSI palette (2026-08-19, which closed the light-theme item by deleting its premise) and the minimum-terminal-size question (2026-08-20, closed with no code — see [docs/decisions.md](docs/decisions.md) "A terminal too small is the user's to fix").

**Baseline: 1080 unit tests green (2026-08-25), contract suite 12/12** against the disposable engine on `:8001` (last run 2026-08-20). Nothing is broken and nothing is urgent.

**Open work** — all ergonomics, none of it parity: the quick-add bar (phases 1–3 shipped 2026-08-25 — the grammar in [expense/quickadd/](expense/quickadd/), `expense log "<line>"` on the flat CLI, and the TUI LOG bar in [expense/tui/screens/log_bar.py](expense/tui/screens/log_bar.py), which stages but does not yet save; **phase 4, the save and the `+` switch, is what remains**), shell completions, human-name resolution for reference flags, and four smaller items (two of them opened 2026-08-20 — the TUI cannot create an inbox draft, and the edit form's `^↑/^↓` field keys are eaten by macOS Mission Control). One home: [docs/todo.md](docs/todo.md). Reference for what exists: [docs/cli-spec.md](docs/cli-spec.md) (commands) · [docs/tui.md](docs/tui.md) (the TUI) · [docs/decisions.md](docs/decisions.md) (why).

*The docs were consolidated 2026-08-20: `roadmap.md` (build order, every step shipped), `tui-plan.md` (phased plan, every phase shipped), `backlog.md` (closed phases), `client-breaking-changes.md` (the worked-off 2026-08 rework record) and `tui-decache-notes.md` were **deleted** — git history is the archive. `tui-plan.md` was rewritten as the present-tense [docs/tui.md](docs/tui.md); `backlog.md` became [docs/todo.md](docs/todo.md).*
