# Expense World CLI — Build Roadmap

> Build order inside the CLI: skeleton → auth → core CRUD → inbox flow → ledger → dashboard → reconciliations → sync → niche reads. Nothing is built client-side that isn't already live on the engine.
>
> Engine spec: [../../expense_world_engine/docs/engine-spec.md](../../expense_world_engine/docs/engine-spec.md)
> API conventions: [../../expense_world_engine/docs/api-design-principles.md](../../expense_world_engine/docs/api-design-principles.md)
> CLI spec: [cli-spec.md](cli-spec.md)

---

## Status

Engine feature-complete through Step 9.1 (home-currency recalculation on `main_currency` change), deployed to `https://expense-world-engine.onrender.com`. On top of 9.1 the engine also ships, as part of the cross-cutting audit work: archive/unarchive on accounts, categories, hashtags; dashboard honors `include_archived` with lifetime-signed totals in `archived_accounts` / `archived_categories` / `archived_hashtags` panels; attach guard rejects `POST`/`PUT /transactions` with 422 when `hashtag_ids` references an archived hashtag (and the equivalent for archived categories on transactions and pending inbox items); full `POST /{resource}/{id}/restore` coverage on every soft-deletable resource; currencies locked at the schema to USD/PEN (no cross-rate math). Two operational tasks remain in engine [TODO.md](../../expense_world_engine/TODO.md): daily exchange-rate cron wiring + historical FX backfill — neither blocks CLI work. CLI is Step 10 of the overall product roadmap ([../../expense_world_engine/docs/roadmap.md](../../expense_world_engine/docs/roadmap.md)).

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

**Blocker to resolve first.** The CLI calls for a Personal Access Token in `~/.expense-config`, but the engine today validates Supabase JWTs only — no PAT endpoint exists. Two paths:

- **Option A (ship now):** use a long-lived Supabase JWT directly. Zero engine changes.
- **Option B (ship right):** add PAT issuance + validation to the engine first. Correct long-term; reopens engine work.

Owner: @alexterfer. Decision needed before any work on this step begins — record the outcome at the top of the step once made. Step 0.5 can proceed in parallel while this is open.

1. **`expense config`** — `set` / `get` / `clear`. Store `token`, `engine_url`, `client_id` (auto-generated UUID), `main_currency` in `~/.expense-config` with `chmod 600`.
2. **HTTP client wrapper** — attaches `Authorization: Bearer <token>`, prepends base URL, generates fresh `X-Idempotency-Key` UUID on every write, attaches `X-Client-Id`. Honors a global `--verbose` flag that prints request + response (method, URL, status, headers, body) for debugging; redact the `Authorization` header.
3. **Error translator** — renders the engine's standard error shape to the terminal. `--json` passes through verbatim.
4. **`expense ping`** → `GET /health`. Confirms the engine is reachable.
5. **`expense auth bootstrap`** → `POST /auth/bootstrap`. First-login upsert.
6. **`expense auth me`** (alias `whoami`) → `GET /auth/me`. Proves the full auth stack works. Caches `main_currency` into config.
7. **`expense auth settings`** → `PUT /auth/settings`. Partial update of `display_name`, `timezone`, `main_currency`. Warn the user that changing `main_currency` triggers home-currency recalc on the engine.

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
4. `expense inbox promote <id>` → `POST /inbox/{id}/promote`. On 422, pretty-print the missing/blocking fields and suggest the fix.
5. `expense log` — direct ledger entry, single transaction. All required fields supplied as flags. Transfer creation (`--transfer --to-account`) is deferred to Step 4 alongside the rest of the transactions surface.

**Verify:** add an incomplete inbox item, try to promote (expect a helpful error). Fill in, promote, confirm transaction appears in `expense transactions list` and inbox item is soft-deleted. Archive the category referenced by a ready inbox item and confirm `inbox list --ready` no longer surfaces it.

**Commit:** `feat: inbox + log — add, list, edit, promote, direct ledger entry`

---

## Step 4 — Transactions

*Deliverable: full ledger management including batch and restore.*

1. `transactions list` — filters: `--account`, `--category`, `--hashtag`, `--reconciliation`, `--from`, `--to`, `--cleared`, `--approved`, `--search`. Pagination: `--limit`, `--cursor` passed through to the engine; render the `next_cursor` in human mode as a hint and preserve it verbatim in `--json`.
2. `transactions get <id>` — full detail. `--with-activity` includes activity log entries.
3. `transactions update <id>` — partial update. `hashtag_ids` and `reconciliation_id` editable through update. Field locking under completed reconciliations surfaces cleanly.
4. `transactions delete <id>` / `restore <id>` — `delete` confirms unless `--yes`.
5. Extend `expense log` with `--transfer --to-account <id>` for paired transfer creation in a single call (the basic `log` shipped in Step 3).
6. `transactions batch` — atomic multi-tx create from flags or stdin JSON.

**Verify:** create, update, delete, restore a single tx. Create a transfer and confirm both sides paired via `transfer_transaction_id`. Complete a reconciliation and try to edit a locked field. Batch-create 3 transactions in one call.

**Commit:** `feat: transactions — list, view, edit, delete, restore, transfer, batch`

---

## Step 5 — Dashboard + Reports

*Deliverable: current month + historical views in the terminal.*

1. `expense dashboard` → `GET /dashboard`. Renders:
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

1. `expense activity list [--resource-type] [--resource-id] [--limit] [--cursor]` → `GET /activity`. Paginated per engine spec: render `next_cursor` as a hint in human mode; preserve verbatim in `--json`.
2. `expense rates get --target <code> [--base USD] [--date YYYY-MM-DD]` → `GET /exchange-rates`.

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

Next: iterate on ergonomics based on actual use. Quick-add natural-language parser (Todoist-style `expense $20 today #food`), interactive prompts, `expense import csv`, shell completions, color conventions — see "To Be Defined" in the spec.

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
