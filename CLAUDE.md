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

## Build phases (current status)

See [docs/roadmap.md](docs/roadmap.md). Engine is feature-complete through Step 9.2 (PAT auth + ES256 JWT verification, shipped 2026-04-23) plus the follow-on `PUT /v1/auth/profile` (engine commit 7017615). CLI is through Step 9 (CLI-complete gate closed 2026-05-10): every engine endpoint with a CLI surface is wrapped, surface coverage is regression-armored by [tests/unit/test_command_surface.py](tests/unit/test_command_surface.py), and the freshman flow is wired as a live contract test. Next is Step 9.5 (interactive shell).

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
| 9.5.1 | Menu — foundation (questionary, root menu, shared helpers) | Done |
| 9.5.2 | Menu — Log a transaction (root shortcut) | Done |
| 9.5.3 | Menu — Inbox | Done |
| 9.5.4 | Menu — Transactions | Done |
| 9.5.5 | Menu — Dashboard | Done |
| 9.5.6 | Menu — Config | Done |
| 9.5.7 | Menu — Auth & profile | Done |
| 9.5.8 | Menu — Reports (with hashtag tree) | Done |
| 9.5.9 | Menu — Accounts | Done |
| 9.5.10 | Menu — Categories (next) | Pending |
| 9.5.11 | Menu — Hashtags | Pending |
| 9.5.12 | Menu — Reconciliations (incl. `$EDITOR` reorder) | Pending |
| 9.5.13 | Menu — Sync | Pending |
| 9.5.14 | Menu — Activity log | Pending |
| 9.5.15 | Menu — Exchange rates | Pending |
| 9.5.16 | Menu — Step 9.5 closeout (freshman-flow gate) | Pending |
