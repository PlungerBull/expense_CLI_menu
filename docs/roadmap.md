# Expense World CLI — Build Roadmap

> Build order inside the CLI: skeleton → auth → core CRUD → inbox flow → ledger → dashboard → reconciliations → sync → niche reads. Nothing is built client-side that isn't already live on the engine.
>
> Engine spec: [../../expense_world_engine/docs/engine-spec.md](../../expense_world_engine/docs/engine-spec.md)
> API conventions: [../../expense_world_engine/docs/api-design-principles.md](../../expense_world_engine/docs/api-design-principles.md)
> CLI spec: [cli-spec.md](cli-spec.md)

---

## Status

Engine feature-complete through Step 9.2 (PAT auth + ES256 JWT verification, shipped 2026-04-23), deployed to `https://expense-world-engine.onrender.com`. On top of auth, the engine also ships as part of the cross-cutting audit work: archive/unarchive on accounts, categories, hashtags; dashboard honors `include_archived` with lifetime-signed totals in `archived_accounts` / `archived_categories` / `archived_hashtags` panels; attach guard rejects `POST`/`PUT /v1/transactions` with 422 when `hashtag_ids` references an archived hashtag (and the equivalent for archived categories on transactions and pending inbox items); full `POST /v1/{resource}/{id}/restore` coverage on every soft-deletable resource; currencies locked at the schema to USD/PEN (no cross-rate math). Two operational tasks remain in engine [TODO.md](../../expense_world_engine/TODO.md): daily exchange-rate cron wiring + historical FX backfill — neither blocks CLI work. **All engine endpoints except `GET /health` are mounted under `/v1/`** — the CLI HTTP client's base path should be `<engine_url>/v1` with `/health` as the one special-case. CLI is Step 10 of the overall product roadmap ([../../expense_world_engine/docs/roadmap.md](../../expense_world_engine/docs/roadmap.md)).

---

## Step 0 — Repo & Skeleton

*Deliverable: a Typer app that prints `--help` locally, committed to a fresh GitHub repo.*

1. Create GitHub repo `expense_CLI_menu` (public — see [CLAUDE.md](../CLAUDE.md) "Config isolation"). Initialize git in this folder. Enable GitHub secret scanning + push protection under repo settings → Code security.
2. Create Python virtualenv (`python -m venv .venv`).
3. Install: `typer`, `httpx`, `pydantic`. (Note: the `[all]` extra was deprecated in Typer 0.12+; everything is bundled in the base install now.)
4. Scaffold `expense/__main__.py` with an empty Typer app; wire `python -m expense` to print help.
5. Add `.gitignore`, `README.md`, `requirements.txt`.

**Verify:** `python -m expense --help` prints the empty app help.

**Commit:** `feat: CLI skeleton — Typer app, project structure`

---

## Step 0.5 — Packaging, Testing, CI

*Deliverable: `expense` is a real console binary, tests run locally and in CI, lint/format are enforced.*

Pure plumbing — no engine calls, no product decisions. Unblocked by the PAT vs. JWT question, so it can land before Step 1.

1. **`pyproject.toml`** — replace `requirements.txt`. Declare project metadata, dependencies (`typer`, `httpx`, `pydantic`), dev dependencies (`pytest`, `respx`, `ruff`). Add a `[project.scripts]` entry so `expense = "expense.__main__:app"`. Run `pip install -e .` — `expense --help` now works from any directory.
2. **Lint + format** — `ruff check` + `ruff format` configured in `pyproject.toml`. Optional `mypy` for the Pydantic models layer.
3. **Pre-commit hook** — runs ruff on staged files. Keeps style drift out of commits.
4. **Test scaffold** — `pytest` with `respx` for mocking httpx responses. Directory layout: `tests/unit/` (respx-mocked), `tests/contract/` (hits staging engine only when `PYTEST_LIVE=1`). One placeholder test per directory proves the harness works.
5. **GitHub Actions CI** — single workflow on push + PR: install, ruff check, ruff format check, pytest (unit only — contract tests stay manual until staging creds are wired).

**Verify:** `pip install -e . && expense --help` works from a fresh shell in any directory. `pytest` runs green. Push a branch — CI goes green.

**Commit:** `chore: packaging + test scaffold + CI`

---

## Step 1 — Config, Auth, Health

*Deliverable: `expense config`, `expense auth`, and `expense ping` wire the CLI to the live engine.*

**Blocker resolved 2026-04-23 — went with PAT (Option B).** The engine now ships PAT auth (engine commits `3f729b2` + `b001b85`): `POST /v1/auth/pat` issues a one-shot plaintext token prefixed `ewe_pat_`, `DELETE /v1/auth/pat/{id}` revokes. Middleware in `app/deps.py` branches on the `ewe_pat_` prefix — anything else falls through to JWT verification (HS256 shared-secret or ES256 via Supabase JWKS). The CLI treats the PAT as an opaque Bearer token; no client-side validation needed.

For Step 1, the user obtains a PAT out-of-band (direct API call to `POST /v1/auth/pat` with their Supabase JWT, or via the future web dashboard) and pastes it into `expense config set --token <pat>`. CLI-side PAT create/revoke commands are deferred — not required for the daily-driver flow.

1. **`expense config`** — `set` / `get` / `clear`. Store `token`, `engine_url`, `client_id` (auto-generated UUID), `main_currency` in `~/.expense-config` with `chmod 600`.
2. **HTTP client wrapper** — attaches `Authorization: Bearer <token>`, prepends base URL, generates fresh `X-Idempotency-Key` UUID on every write, attaches `X-Client-Id`. Honors a global `--verbose` flag that prints request + response (method, URL, status, headers, body) for debugging; redact the `Authorization` header.
3. **Error translator** — renders the engine's standard error shape to the terminal. `--json` passes through verbatim.
4. **`expense ping`** → `GET /health`. Confirms the engine is reachable.
5. **`expense auth bootstrap`** → `POST /v1/auth/bootstrap`. First-login upsert. Idempotent: subsequent calls only bump `last_login_at`. The `--display-name` and `--timezone` flags are honored ONLY on the very first call (the INSERT); replays don't overwrite them.
6. **`expense auth me`** (alias `whoami`) → `GET /v1/auth/me`. Proves the full auth stack works. Caches `main_currency` into config.
7. **`expense auth settings`** → `PUT /v1/auth/settings`. Partial update of `user_settings` fields only: `theme`, `start_of_week`, `main_currency`, `transaction_sort_preference`, `display_timezone`, `sidebar_show_bank_accounts`, `sidebar_show_people`, `sidebar_show_categories`. Warn the user that changing `main_currency` triggers home-currency recalc on the engine.
8. **`expense auth profile`** → `PUT /v1/auth/profile`. Partial update of `users` (identity) fields. Currently only `--display-name` is mutable in v1; the engine rejects `null` (clearing not supported). Shipped as a follow-on to Step 1 (engine commit `7017615`, CLI commit `99f9008`) to close the gap that bootstrap-idempotency leaves: post-login identity changes need a dedicated endpoint, not a settings overload.

**Verify:** `expense config set … && expense ping && expense auth me` returns current user's settings from the live engine.

**Commit:** `feat: CLI auth — config, HTTP client, error translation, health, auth commands`

---

## Step 2 — Accounts, Categories, Hashtags

*Deliverable: full CRUD + archive/unarchive/restore on the three core resource groups.*

Mirrors engine Step 4 (core CRUD), extended with the archive/unarchive/restore verbs shipped alongside the engine's cross-cutting audit work. Each group: `list`, `get`, `create`, `update`, `delete`, `restore`, `archive`, `unarchive`.

**2a — `expense accounts`**
- `list` supports `--include-archived`, `--include-deleted`, `--include-people`
- Currency immutability: pre-flight warning before the engine 422 lands
- `archive` is for closing accounts IRL; `delete` is for cleanup/mistakes (see [../../expense_world_engine/docs/engine-spec.md](../../expense_world_engine/docs/engine-spec.md))

**2b — `expense categories`**
- Same verbs. System categories (`@Debt`, `@Transfer`) return 403 on rename/delete/archive — render as a clear "System categories cannot be modified" message.

**2c — `expense hashtags`**
- Same verbs. Archive does not cascade to junction rows.

**Verify:** for each resource: create, update, list, archive, unarchive, delete, restore. Confirm the engine state via Swagger. Confirm that creating a transaction referencing an archived category/hashtag is rejected by the engine (422) and the CLI renders the rejection cleanly.

**Commit:** `feat: accounts + categories + hashtags — full CRUD + archive + restore`

---

## Step 3 — Inbox + Promote + Log

*Deliverable: the daily capture flow works end-to-end from the terminal.*

1. `expense inbox add` — partial-field capture (title + amount minimum).
2. `expense inbox list` supports `--ready` (excludes items missing required fields or pointing at archived categories) and `--include-deleted`.
3. `expense inbox get` / `update` / `delete` / `restore`.
4. `expense inbox promote <id>` → `POST /v1/inbox/{id}/promote`. On 422, pretty-print the missing/blocking fields and suggest the fix.
5. `expense log` — direct ledger entry, single transaction. All required fields supplied as flags. Transfer creation (`--transfer --to-account`) is deferred to Step 4 alongside the rest of the transactions surface.

**Verify:** add an incomplete inbox item, try to promote (expect a helpful error). Fill in, promote, confirm transaction appears in `expense transactions list` and inbox item is soft-deleted. Archive the category referenced by a ready inbox item and confirm `inbox list --ready` no longer surfaces it.

**Commit:** `feat: inbox + log — add, list, edit, promote, direct ledger entry`

---

## Step 3.1 — Date input normalization

*Deliverable: users type natural date shapes (`2026-04-25`, `2026-04-25 16:30`); the CLI converts to RFC 3339 with the local tz before sending.*

The engine ships strict aware-only datetime acceptance alongside this step (Pydantic `AwareDatetime` on `Transaction{Create,Update}Request` and `Inbox{Create,Update}Request`; naive input rejected with 422). Matches industry consensus (Stripe, Plaid, Square, GitHub, AWS, GCloud per AIP-142): "no globally-correct interpretation" of a naive timestamp in a financial system. The CLI absorbs the user-friendly conversion.

1. New `expense/dates.py` — `to_canonical_aware(user_input)` accepts `YYYY-MM-DD`, naive datetime (T or space separator, with or without seconds), or RFC 3339 with offset. Naive forms get the user's local timezone (via `tzlocal`) attached and are re-emitted as RFC 3339; aware forms pass through verbatim. Unparseable input raises `typer.BadParameter` with a clear message.
2. `expense log --date`, `expense inbox add --date`, `expense inbox update --date` route user input through the helper before building the request payload. Default for `expense log --date` (when omitted) stays as local-aware "now".
3. New runtime dependency: `tzlocal>=5.2`.

**Verify:** unit tests cover all accepted shapes; live smoke runs `expense log --date 2026-04-25` and `expense log --date "2026-04-25 16:30"` against the engine and confirms 201 (not a CLI BadParameter, not an engine 422).

**Commit:** `feat: date input normalization — accept naive forms, send RFC 3339`

---

## Step 4 — Transactions

*Deliverable: full ledger management including batch and restore.*

1. `transactions list` — filters: `--account`, `--category`, `--hashtag`, `--reconciliation`, `--from`, `--to`, `--cleared/--no-cleared`, `--search`, `--include-deleted`, `--debit-as-negative`. Pagination is offset-based: `--limit`, `--offset` (engine response shape `{items, total, limit, offset}`); human mode prints a `(showing N of M; pass --offset N --limit ... for more)` hint when truncated, `--json` is pass-through.
2. `transactions get <id>` — full detail. (`--with-activity` is deferred to Step 8: activity-log entries surface via `expense activity list --resource-type expense_transactions --resource-id <id>`.)
3. `transactions update <id>` — partial update. `hashtag_ids` (comma-separated) and `reconciliation_id` editable through update. Field locking under completed reconciliations and the transfer-pair edit guard surface as 422s with friendly hints.
4. `transactions delete <id>` / `restore <id>` — `delete` confirms unless `--yes`. Both render the engine's `warnings: list[str]` envelope as `Warning: ...` lines in human mode; `--json` passes through verbatim.
5. Extend `expense log` with `--transfer --to-account-id <id> --to-amount <signed_cents>` for paired transfer creation in a single atomic POST (engine creates both legs and links via `transfer_transaction_id`).
6. `transactions batch` — atomic multi-tx create from stdin JSON (or `--file <path>`). Wraps the array in `{"transactions": [...]}` per engine schema; injects `id` UUIDs for items missing one; rejects items with a `transfer` field locally before any HTTP call.

**Verify:** create, update, delete, restore a single tx. Create a transfer and confirm both sides paired via `transfer_transaction_id`. Complete a reconciliation and try to edit a locked field (Step 6 for the reconciliation create; Step 4 only verifies the hint surfaces). Batch-create 3 transactions in one call.

**Commit:** `feat: transactions — list, view, edit, delete, restore, transfer, batch`

---

## Step 5 — Dashboard + Reports

*Deliverable: current month + historical views in the terminal.*

1. `expense dashboard` → `GET /v1/dashboard`. Renders:
   - Bank accounts (native + home currency)
   - People accounts
   - Categories with expandable hashtag-combination breakdown
   - Totals (inflow / outflow / net)
2. `--include-archived` → adds `archived_accounts`, `archived_categories`, `archived_hashtags` panels with lifetime signed totals.
3. `--month YYYY-MM` → switches to single-month report.
4. `--json` → raw engine response.
5. `expense reports monthly` — separate command for historical:
   - `--year <y> --month <m>` → single month.
   - `--from YYYY-MM --to YYYY-MM` → inclusive range (max 24 months). Output renders as a table: rows = categories, cols = months.

**Verify:** `dashboard` matches the web view semantically. `dashboard --include-archived` surfaces the archived panels with lifetime totals. `reports monthly --from 2025-11 --to 2026-04` returns 6 months.

**Commit:** `feat: dashboard + reports — current month, historical, archived panels`

---

## Step 6 — Reconciliations

*Deliverable: `expense reconcile` matches the engine reconciliation state machine.*

1. `reconcile list [--account]`.
2. `reconcile create`, `get`, `update`, `delete`, `restore`.
3. `reconcile complete <id>` — prints the count of newly-locked transactions.
4. `reconcile revert <id>` — requires `--yes`; unlocks fields and is a meaningful audit event.

**Commit:** `feat: reconcile — full lifecycle`

---

## Step 7 — Sync

*Deliverable: `expense sync --full` pulls a complete snapshot from the engine. Local cache deferred.*

Stateless CLIs rarely need sync the way mobile/web do. Two modes:

1. **`expense sync --full`** → wildcard `*`. Prints per-resource counts. No local persistence. Ship this first.
2. **`expense sync --cache`** (optional, ship only if demand appears) — local SQLite cache under `~/.expense-cache.sqlite3`, persists `sync_token` per `X-Client-Id`. Enables `--offline` on read commands.

**Verify:** `sync --full` returns all active records. Mutate on the server via another client, re-sync, confirm the delta.

**Commit:** `feat: sync --full (cache optional)`

---

## Step 8 — Activity + Exchange Rates

*Deliverable: niche read commands for audit trail and rate lookups.*

1. `expense activity list [--resource-type] [--resource-id] [--limit] [--cursor]` → `GET /v1/activity`. Paginated per engine spec: render `next_cursor` as a hint in human mode; preserve verbatim in `--json`.
2. `expense rates get --target <code> [--base USD] [--date YYYY-MM-DD]` → `GET /v1/exchange-rates`.

Low-value by themselves, but they close the gap to full engine coverage.

**Commit:** `feat: activity + exchange-rates read commands`

---

## Step 9 — CLI Complete

All command groups from [cli-spec.md](cli-spec.md) work end-to-end against the live engine. Run the full check:

- Every command has `--help` with an example
- `--json` works on every read command
- Errors from the engine surface cleanly (never a bare stack trace)
- A fresh user goes `expense config set` → `expense auth bootstrap` → `expense dashboard` with no surprises
- Archive/delete distinction is respected: closed accounts/categories/hashtags appear only with `--include-archived`, deleted ones only with `--include-deleted`

Next: Step 9.5 (interactive shell) immediately after this gate, then Post-Step-9 ergonomics (quick-add parser, CSV import, shell completions, color conventions).

---

## Step 9.5 — Interactive shell (`expense menu`)

*Deliverable: a menu-driven UI that wraps the now-complete flat command surface, for management/inspection workflows.*

The CLI ships two complementary front doors after Step 9:

- **`expense <command> [flags]`** (current) — flat invocations. Power users, scripting, automation, the future quick-add parser. Stays the canonical interface.
- **`expense menu`** — drops into an interactive walkdown over the same actions. For first-time discovery, infrequent management tasks ("archive an account I haven't touched in months"), and any case where the user prefers navigating to remembering flag names.

Both paths call the same underlying flat-command implementations. The menu is a thin presentation layer; it does not duplicate logic.

`expense` (no args) keeps its current behavior — prints the group help. Menu is opt-in via the explicit `expense menu` invocation.

1. **Library choice** — `questionary` (built on `prompt_toolkit`). Adds one dev dep, supports text prompts, single/multi-select lists, checkboxes, confirmations. Lighter than Textual; no need for full-screen panels for v1.
2. **Navigation** — root menu lists the same top-level groups as `expense --help` (config, auth, accounts, categories, hashtags, inbox, transactions, dashboard, reconcile, sync, activity, rates). Selecting a group lists its commands. Selecting a command prompts for inputs (one prompt per flag), then invokes the underlying flat command and renders the result inline.
3. **Inputs** — for read commands, prompt only for filters (skip them with Enter for "all"). For writes, prompt for required fields first, then offer to "set additional optional fields?" — yes/no fork keeps simple actions short.
4. **Confirmations** — destructive actions reuse the same `--yes`-equivalent prompts the flat commands already gate on. Currency-change recalc warning surfaces here too.
5. **Quit / back** — `q` or Ctrl-C at any prompt returns to the previous menu; from the root, exits cleanly.
6. **Output** — same renderers the flat commands use (no parallel formatting code). After an action completes, the menu prints the result and returns to the parent menu, ready for the next action.

**Out of scope for v1 of the menu:** no full-screen TUI panels, no live dashboards, no mouse, no color theming. Just menus → prompts → invoke → show result → back to menu.

**Verify:** a fresh user types `expense menu` and walks the entire app (set config, bootstrap, browse accounts, log a transaction, view dashboard) without ever consulting `--help` or memorizing a flag.

**Commit:** `feat: interactive shell — expense menu wraps the flat command surface`

---

## Post-Step-9 ergonomics

Land in this order, separately from Step 9.5:

1. **Quick-add natural-language parser** — `expense $20 today #food` → parses amount, sign, date, hashtag, title from free text and dispatches to the flat `log` command. Sign stays literal (`$20` = income, `-$20` = expense). The "low-friction capture" half of the dual-UX strategy; the menu is the "discoverable management" half.
2. **Shell completions** — zsh, bash, fish. `expense <TAB>` shows commands; `expense auth <TAB>` shows subcommands. Lowest-effort discoverability win for the flat path.
3. **`expense import csv`** — bulk transaction import for migration.
4. **Color conventions** — Rich-based output styling; opt-out flag for plain ANSI.

---

## Cross-Cutting Conventions

These apply at every step — don't defer them.

- **Human-readable default, `--json` for machines.** Same flag on every read.
- **`debit_as_negative` end-to-end.** Negative = expense, positive = income.
- **Idempotency keys on every write.** Fresh UUID per write, passed as `X-Idempotency-Key`. Retrying a failed command must not double-apply.
- **Never reimplement engine logic.** If a command needs a rule, call an endpoint. No balance math, no currency conversion, no validation beyond obvious flag-combination checks.
- **Confirm destructive operations** unless `--yes` is passed.
- **Engine errors surface intact.** Human mode may prettify; `--json` passes through verbatim.
- **Archive ≠ delete.** Archive is "retired-but-real"; delete is "mistake/gone". The CLI honors both states distinctly in list output and dashboard views.
- **Testing.** Unit tests under `tests/unit/` use `respx` to mock httpx — fast, deterministic, engine-response fixtures checked in. Contract tests under `tests/contract/` hit the live staging engine and run only when `PYTEST_LIVE=1` is set; they're the safety net for engine-shape drift. Every new command lands with at least one unit test covering the happy path and one covering the primary error shape.
- **Pagination.** Any endpoint the engine paginates (activity, transactions list, etc.) exposes `--limit` and `--cursor` flags. Human mode prints `next_cursor` as a hint under the table; `--json` passes it through verbatim.
- **`--verbose`.** Global flag handled by the HTTP client wrapper. Prints request + response (method, URL, status, headers, body) to stderr. Redacts the `Authorization` header.

---

*Last updated: April 2026*
