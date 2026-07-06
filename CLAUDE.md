# expense_CLI_menu — CLAUDE.md

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
| [docs/roadmap.md](docs/roadmap.md) | Step-by-step CLI build order | Local |
| `engine-spec.md` | Every endpoint, every business rule — the API contract the CLI consumes | [../expense_world_engine/docs/engine-spec.md](../expense_world_engine/docs/engine-spec.md) |
| `api-design-principles.md` | Request/response conventions (error shape, null-over-omission, idempotency, sign) | [../expense_world_engine/docs/api-design-principles.md](../expense_world_engine/docs/api-design-principles.md) |
| `design-philosophy.md` | Product vision shared across all clients | [../expense_world_engine/docs/design-philosophy.md](../expense_world_engine/docs/design-philosophy.md) |
| `lessons-*.md` | UX lessons from YNAB, Lunch Money, TickTick, Todoist, Splitwise | [../expense_world_engine/docs/](../expense_world_engine/docs/) |

Engine docs are **referenced, not copied**. Single source of truth lives in the engine repo.

## Tech stack

- **Language:** Python 3.11+
- **CLI framework:** Typer
- **HTTP client:** httpx
- **Config storage:** `~/.expense-config` (chmod 600)
- **Local cache (Step 7b — committed deliverable, not optional):** SQLite under `~/.expense-cache.sqlite3` per [api-design-principles.md §3b](../expense_world_engine/docs/api-design-principles.md). Stateless escape hatch via `--no-cache` / `EXPENSE_STATELESS=1`. See [docs/cli-runtime.md](docs/cli-runtime.md).
- **Sync architecture — server-first, not local-first.** Writes go engine-direct over HTTPS; the local SQLite is a read-through replica only, never the origin of a write. No offline write queue (unlike Todoist's mobile clients — that's an **iOS-only future feature** per [api-design-principles.md §3b](../expense_world_engine/docs/api-design-principles.md), explicitly excluded from CLI and web by design). Why: single source of truth = no conflict resolution, no CRDTs, no per-row vector clocks — every client inherits the same simple `POST → wait → done` contract.

## Non-negotiable conventions

**Thin wrapper**
Every command parses args → calls an engine endpoint → formats output. No caching, no balance math, no validation beyond "do these flags make sense together."

**Sign convention**
Input and output are both signed (`debit_as_negative`): negative = expense, positive = income. The CLI is the caller-side preference layer the engine spec references.

**Human default, JSON opt-in**
Every read command supports `--json` for machine-readable output. Human mode may prettify; `--json` is always the raw engine response, passed through verbatim.

**Idempotency on every write**
The HTTP client generates a fresh UUID per write and sets `X-Idempotency-Key`. Retrying a failed command must never double-apply.

**Engine errors surface cleanly**
The engine's standard error shape (`{ error: { code, message, fields } }`) is rendered to the user. Never swallow, never reformat lossily.

**Confirm destructive operations**
Deletes, reverts, archives prompt for confirmation unless `--yes` is passed.

**Config isolation**
Auth token + engine URL live in `~/.expense-config`. Never checked in, never shared across machines. The GitHub repo (`PlungerBull/expense_CLI_menu`) is **public** by deliberate choice — which makes this rule non-negotiable: any secret committed is immediately public and permanent in git history. GitHub push protection is enabled as defense-in-depth, but the primary safeguard is that credentials never enter the repo in the first place.

**Mock every screen before building it — every time**
Before writing or changing UI code for any user-facing view or screen — a menu, dashboard, list, form, report, or TUI screen, anything the user will see — first present its **HTML mockup in [docs/mockups/](docs/mockups/)** and wait for the user's review. Do this **every time you pick up a screen, even one approved before** — a prior approval is not a standing license to skip the review; the user re-reads the mockup each session to make specific observations. Never assume layout, fields, or behavior: when a detail is unspecified or ambiguous, **stop and ask**.

## Build phases (current status)

See [docs/roadmap.md](docs/roadmap.md). Engine is feature-complete through Step 9.2 (PAT auth + ES256 JWT verification, shipped 2026-04-23) plus the follow-on `PUT /v1/auth/profile` (engine commit 7017615). CLI is through Step 9 (CLI-complete gate closed 2026-05-10): every engine endpoint with a CLI surface is wrapped, surface coverage is regression-armored by [tests/unit/test_command_surface.py](tests/unit/test_command_surface.py), and the freshman flow is wired as a live contract test. Step 9.5 (questionary interactive shell, `expense menu`) shipped in full and was then **deleted at Step 10.X (2026-07-02)** — the Textual TUI replaces it; see below.

**Current work — the Textual TUI (`expense world`), Step 10.** A retained-mode terminal app is the interactive front door (see [docs/tui-plan.md](docs/tui-plan.md)). It is another thin client of the same command/data layer — zero new business logic. Phases 0 (skeleton) and 1 (read views) are done; Phase 2 (write flows) is in progress. The **System reads (Sync · Activity · Rates)** screens are now wired ([expense/tui/screens/system.py](expense/tui/screens/system.py)) as three direct System-group entries; the one remaining stub is **Reports (Monthly report)**, still "coming later" in [expense/tui/screens/home.py](expense/tui/screens/home.py). Phase 3 (polish) shipped its first slice via [docs/polish-backlog.md](docs/polish-backlog.md) §4 (2026-07-05/06): keymap contract (§4.1/§4.5 — r always refreshes, y alone confirms, enter never mutates), theme-resolved sign-colored amounts (§4.2), the fake home status removed by decision (§4.3), and the form label column widened (§4.4) — each gated on an approved mockup and regression-armored (binding pilot tests, literal-color guard, hermetic test env, label-width guard). The audit's follow-ups §4.6 (q scoped to Home), §4.7 (unarchive prompt-free, matching CLI 1.2), and §4.8 (Rates redesigned as a history table over the engine's new `GET /v1/exchange-rates/history`, with flat `expense rates list` as its contract validator) shipped 2026-07-06 — **section 4 is closed**. The dedup backlog (§5, all six items) closed 2026-07-06 as pure refactors: `EngineWriteMixin.run_write` ([expense/tui/screens/_base.py](expense/tui/screens/_base.py) — now PUT + json_body + success/error callbacks + `exclusive=True`) replaced the eight copied TUI write workers; one `FormScreen` base ([expense/tui/screens/_form.py](expense/tui/screens/_form.py)) sits under all three bar-cycle forms; and [expense/commands/_resource.py](expense/commands/_resource.py) gained the shared `fetch_body` (the cache-vs-live skeleton behind every `fetch_*`/`get`), `render_record`, `items_of`, `format_bool`/`format_month`, `redact_token`, `format_hashtag_cell`, and `load_hashtag_name_map`. `?` help overlay / command palette / docs remain for Phase 3. A bulk `.xlsx → engine` importer (`expense import`) also landed on this branch.

**Two front doors.** The flat commands (`expense log`, `expense dashboard`, …) stay the canonical contract-validator interface and remain the complete surface — every engine endpoint is reachable through them. The TUI (`expense world`) is the interactive surface. The questionary `expense menu` (Step 9.5, `expense/menu/`) **was deleted at Step 10.X (2026-07-02)**, retired ahead of full TUI parity by decision — no capability was lost because the flat commands cover everything. The fetch/print split still lets the TUI reuse the underlying command implementations directly.

Next is post-Step-9 ergonomics (quick-add parser, shell completions — see [docs/roadmap.md](docs/roadmap.md)).

The CLI is **cache-by-default by design** per [api-design-principles.md §3b](../expense_world_engine/docs/api-design-principles.md), with stateless as the explicit escape hatch. Step 7 phases: 7a (stateless milestone, shipped), 7b.1 (replica foundation, shipped), 7b.2.1 / 7b.2.2 / 7b.2.3 (replica reads, all shipped), 7b.3 (write-path refresh, shipped).

| Step | Scope | Status |
|---|---|---|
| 0 | Repo & skeleton | Done |
| 0.5 | Packaging, testing, CI | Done |
| 1 | Auth + config + HTTP client | Done |
| 2 | Accounts / categories / hashtags | Done |
| 3 | Inbox + promote + log | Done |
| 3.1 | Date input normalization | Done |
| 4 | Transactions | Done |
| 5 | Dashboard + reports | Done |
| 6 | Reconciliations | Done |
| 7a | Sync — stateless `--full` | Done |
| 7b.1 | Sync — SQLite replica foundation | Done |
| 7b.2.1 | Sync — replica reads for accounts/categories/hashtags + auto cold-start | Done |
| 7b.2.2 | Sync — replica reads for inbox + reconciliations | Done |
| 7b.2.3 | Sync — replica reads for transactions | Done |
| 7b.3 | Sync — write-path refresh | Done |
| 8.1 | Activity log read | Done |
| 8.2 | Exchange-rate read | Done |
| 9 | CLI complete (gate) | Done |
| 9.5 | Menu — questionary interactive shell, all 16 sub-steps (`expense/menu/`) | Shipped, deleted at 10.X |
| import | Bulk `.xlsx → engine` importer (`expense import`) | Done |
| 10.P0 | TUI (`expense world`) — walking skeleton (Outstanding Amounts live) | Done |
| 10.P1 | TUI — read views (Inbox / Transactions / Accounts / Categories / Hashtags / tree) | Done |
| 10.P2 | TUI — write flows (Log/transfer, edit, create forms, Reconciliations, Config, Auth) | In progress |
| 10.P2 | TUI — Reports (Monthly report) screen | Not started |
| 10.P2 | TUI — System reads (Sync · Activity · Rates) screens | Done |
| 10.P3 | TUI — polish (theme, `?` help, command palette, pilot tests, docs) | In progress (backlog §4 closed 2026-07-05/06, §5 closed 2026-07-06; help overlay + palette open) |
| 10.X | Delete questionary `expense menu` (`expense/menu/` + tests + dep) | Done (2026-07-02) |
