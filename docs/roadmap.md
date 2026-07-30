# Expense World CLI — Build Roadmap

> Build order inside the CLI: skeleton → auth → core CRUD → inbox flow → ledger → dashboard → reconciliations → sync → niche reads. Nothing is built client-side that isn't already live on the engine.
>
> Engine spec: [../../expense_world_engine/docs/engine-spec.md](../../expense_world_engine/docs/engine-spec.md)
> API conventions: [../../expense_world_engine/docs/api-design-principles.md](../../expense_world_engine/docs/api-design-principles.md)
> CLI spec: [cli-spec.md](cli-spec.md)

---

## Status

Engine feature-complete through Step 9.2 (PAT auth + ES256 JWT verification, shipped 2026-04-23); deployed to Render 2026-04, **relocated to the local deployment 2026-07-30** (`http://127.0.0.1:8000`, engine roadmap Step 11 + `deploy/local/README.md`; cloud mothballed). On top of auth, the engine also ships as part of the cross-cutting audit work: archive/unarchive on accounts, categories, hashtags; dashboard honors `include_archived` with lifetime-signed totals in `archived_accounts` / `archived_categories` / `archived_hashtags` panels; attach guard rejects `POST`/`PUT /v1/transactions` with 422 when `hashtag_ids` references an archived hashtag (and the equivalent for archived categories on transactions and pending inbox items); full `POST /v1/{resource}/{id}/restore` coverage on every soft-deletable resource; currencies locked at the schema to USD/PEN (no cross-rate math). Two operational tasks remain in engine [TODO.md](../../expense_world_engine/TODO.md): daily exchange-rate cron wiring + historical FX backfill — neither blocks CLI work. **All engine endpoints except `GET /health` are mounted under `/v1/`** — the CLI HTTP client's base path should be `<engine_url>/v1` with `/health` as the one special-case. CLI is Step 10 of the overall product roadmap ([../../expense_world_engine/docs/roadmap.md](../../expense_world_engine/docs/roadmap.md)).

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
5. **GitHub Actions CI** — single workflow on push to `main`: install, ruff check, ruff format check, pytest (unit only — contract tests stay manual until staging creds are wired).

**Verify:** `pip install -e . && expense --help` works from a fresh shell in any directory. `pytest` runs green. Push to `main` — CI goes green.

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

1. `transactions list` — filters: `--account-id`, `--category-id`, `--hashtag-id`, `--reconciliation-id`, `--from`, `--to`, `--cleared/--no-cleared`, `--search`, `--include-deleted`. (Signed amounts are not opt-in: every stateless read sends `debit_as_negative=true`, matching the replica; the former `--debit-as-negative` flag was removed at the polish pass.) Pagination is offset-based: `--limit`, `--offset` (engine response shape `{items, total, limit, offset}`); human mode prints a `(showing N of M; pass --offset N --limit ... for more)` hint when truncated, `--json` is pass-through.
2. `transactions get <id>` — full detail. (`--with-activity` is deferred to Step 8: activity-log entries surface via `expense activity list --resource-type transaction --resource-id <id>`.)
3. `transactions update <id>` — partial update. `hashtag_ids` (comma-separated) and `reconciliation_id` editable through update. Field locking under completed reconciliations and the transfer-pair edit guard surface as 422s with friendly hints.
4. `transactions delete <id>` / `restore <id>` — `delete` confirms unless `--yes`. Both render the engine's `warnings: list[str]` envelope as `Warning: ...` lines in human mode; `--json` passes through verbatim.
5. Extend `expense log` with `--transfer --to-account-id <id> --to-amount <signed_cents>` for paired transfer creation in a single atomic POST (engine creates both legs and links via `transfer_transaction_id`).
6. `transactions batch` — atomic multi-tx create from stdin JSON (or `--file <path>`). Wraps the array in `{"transactions": [...]}` per engine schema; injects `id` UUIDs for items missing one; rejects items with a `transfer` field locally before any HTTP call.

**Verify:** create, update, delete, restore a single tx. Create a transfer and confirm both sides paired via `transfer_transaction_id`. Complete a reconciliation and try to edit a locked field (Step 6 for the reconciliation create; Step 4 only verifies the hint surfaces). Batch-create 3 transactions in one call.

**Commit:** `feat: transactions — list, view, edit, delete, restore, transfer, batch`

---

## Step 5 — Dashboard + Reports

*Deliverable: current month + historical views in the terminal.*

1. `expense dashboard` → `GET /v1/dashboard`. Current-month-only (the engine endpoint is current-month-only — there is no `?month=` parameter). Renders:
   - Bank accounts (native + home currency)
   - People accounts
   - Categories with expandable hashtag-combination breakdown
   - Totals (inflow / outflow / net)
2. `--include-archived` → adds `archived_accounts`, `archived_categories`, `archived_hashtags` panels with lifetime signed totals.
3. `--json` → raw engine response.
4. `expense reports monthly` — separate command for historical flow (no balances; balances are a "now" concept and live on `/dashboard` only):
   - `--date YYYY-MM` → single month.
   - `--from YYYY-MM --to YYYY-MM` → inclusive range (max 24 months). Output renders as a table: rows = categories, cols = months. Mutually exclusive with `--date`.
   - `--json` → raw engine response.

**Verify:** `dashboard` matches the web view semantically. `dashboard --include-archived` surfaces the archived panels with lifetime totals. `reports monthly --date 2026-03` returns a single month. `reports monthly --from 2025-11 --to 2026-04` returns 6 months.

**Commit:** `feat: dashboard + reports — current month, historical, archived panels`

---

## Step 6 — Reconciliations

*Deliverable: `expense reconcile` matches the engine reconciliation state machine, including `sort_order` chaining and the bulk reorder endpoint.*

The engine ships `sort_order`, `beginning_balance_source` (`"manual"` or `"chained"`), `chained_from_reconciliation_id`, and a new `PUT /v1/accounts/{account_id}/reconciliations/order` bulk reorder endpoint alongside this step. `PUT /v1/reconciliations/{id}` rejects `beginning_balance_source: "chained" + beginning_balance_cents: <number>` with a field-scoped 422 — the CLI blocks the equivalent flag combination at parse time.

1. `reconcile list [--account-id]` — when filtered by account, sorted by `sort_order ASC, created_at ASC`. List rows surface `[chained from <id>]` / `[manual]` markers.
2. `reconcile create`, `get`, `update`, `delete`, `restore`. Beginning-balance UX:
   - omit `--beginning-balance` → engine chains from previous reconciliation (default for "next month follows last month")
   - pass `--beginning-balance <cents>` → engine forces `source = "manual"`, value stored verbatim
   - `--source manual|chained` toggle on `update` (mutually exclusive with `--beginning-balance` for `chained`).
3. `reconcile complete <id>` — prints the count of newly-locked transactions. Locks 4 transaction fields + 5 reconciliation fields (incl. `beginning_balance_source`).
4. `reconcile revert <id>` — requires `--yes`; unlocks all assigned transactions and the reconciliation's own balance/date fields. A meaningful audit event.
5. `reconcile move <id> --to <n> | --before <id> | --after <id>` — single-row reorder. CLI fetches current chain, computes the new `ordered_ids`, sends one `PUT /v1/accounts/{account_id}/reconciliations/order`.
6. `reconcile reorder --account-id <id>` — bulk reorder via `$EDITOR`. CLI writes the current order to a temp file, launches the user's editor, parses the saved result, sends one bulk request. Mirrors `git rebase -i` UX. First `subprocess + tempfile` pattern in the CLI; helper lives at `expense/_editor.py`.

**Verify:** `reconcile create` without `--beginning-balance` chains from previous month. `reconcile update <id> --source chained --beginning-balance N` rejected at parse time. `reconcile complete <id>` on an empty batch returns the engine's 422 with a friendly hint. `reconcile move <id> --after <other>` reorders with the cascade running engine-side. `reconcile reorder --account-id <id>` opens `$EDITOR`, accepts the rearranged file, and prints `recalculated_count` from the response.

**Commit:** `feat: reconcile — full lifecycle + sort_order, source toggle, bulk reorder`

---

## Step 7 — Sync

*Deliverable: cache-by-default CLI per [api-design-principles.md §3b](../../expense_world_engine/docs/api-design-principles.md). Shipped in two phases.*

The CLI is **cache-by-default by design**, not stateless-by-default. The local SQLite replica is a committed deliverable (matches iOS, web, every interactive client per §3b) — it powers instant reads via a `GET /sync`-backed local store. The stateless mode is the explicit escape hatch via `--no-cache` per command or `EXPENSE_STATELESS=1` process-wide.

Splitting into two phases so the rest of the engine surface (Step 8 onward) isn't blocked on the replica:

### Step 7a — `expense sync --full` (stateless milestone)

First ship. Calls `GET /v1/sync?sync_token=*`, prints a per-resource count summary plus the new `sync_token` and a local `pulled_at` timestamp, throws away the token. Stateless. Validates the engine's sync contract end-to-end through real CLI use — junction-flattened `hashtag_ids`, home-currency derivation, sign convention, error envelope — before the replica is built on top, and before web/iOS clients consume the same endpoint.

`--full` is the only mode that works in 7a. The bare `expense sync` form errors with a hint pointing to `--full`; bare is reserved for 7b's delta-sync default to avoid a breaking redefinition later.

**Verify:** `sync --full` returns all active records. Mutate on the server via another client, re-sync, confirm the new `sync_token` differs and the relevant count moved.

**Commit:** `feat: sync --full (stateless milestone)`

### Step 7b — Local SQLite replica (split into 7b.1 / 7b.2 / 7b.3)

Replica file under `~/.expense-cache.sqlite3` keyed by `(user_id, X-Client-Id)`. Built incrementally so the rest of the engine surface (Step 8+) isn't blocked on replica-backed reads.

#### Step 7b.1 — Foundation (cache built, not yet consumed)

SQLite layer, schema, WAL setup, cold start, delta sync, tombstone application, `sync_token` persistence. Bare `expense sync` becomes meaningful (delta against cache; cold-starts on first run). `--full` rebuilds cache from scratch. `--no-cache` (root flag) and `EXPENSE_STATELESS=1` (env var) preserve the 7a stateless behavior. Read commands still hit the engine — `--no-cache` is a no-op on reads in 7b.1.

**Verify:** `expense sync --full` populates cache; second `expense sync` shows mostly-zero deltas; mutate via `expense transactions create`, re-sync, confirm `+1` insert and the row is in the SQLite cache; corrupt the stored `sync_token`, re-sync, confirm engine 422 falls back to cold start.

**Commit:** `feat: local SQLite replica foundation (Step 7b.1)`

#### Step 7b.2 — Read consumption + auto cold-start (split into 7b.2.1 / 7b.2.2 / 7b.2.3)

Split by resource complexity so the auto-cold-start UX and `--no-cache` engine fallback pattern bake on cheap cases first.

**Step 7b.2.1 (shipped) — Simple resources + auto cold-start.** `list`/`get` for accounts, categories, hashtags switched to replica-backed default. Filters are pure SQL (booleans only). Established the auto-cold-start UX (stderr notice on first-time empty cache) and the `--no-cache` engine fallback pattern. Accounts cached read returns `current_balance_home_cents: null` per §3b drift policy — users wanting current home balances run `expense dashboard` or pass `--no-cache`.

**Commit:** `feat: replica-backed reads for simple resources + auto cold-start (Step 7b.2.1)`

**Step 7b.2.2 (shipped) — Inbox + reconciliations.** `inbox list/get` and `reconcile list/get` switched to replica-backed default. Inbox `ready` filter fully replicated as SQL JOIN against cached accounts/categories (engine: title set + non-UNTITLED, amount nonzero, date ≤ today, account & category present and active); `overdue` is `date < today`. `reconcile get` embeds paginated transactions from the transactions cache (sort `date DESC, created_at DESC`). Schema bump to v2 (added indexed `category_id` to inbox table) — existing 7b.2.1 caches auto-wipe + cold-start on first sync. `reconcile move`/`reorder` internal read loops stay engine-direct (write-path workflows).

**Commit:** `feat: replica-backed reads for inbox + reconciliations (Step 7b.2.2)`

**Step 7b.2.3 (shipped) — Transactions.** `transactions list/get` switched to replica-backed default. 8 filters: account_id, category_id, hashtag_id, reconciliation_id, date_from, date_to, cleared, search. `hashtag_id` uses SQLite `json_each(body, '$.hashtag_ids')` containment subquery; `search` uses `LIKE … COLLATE NOCASE` against `json_extract(body, '$.title')` and `'$.description'` (ASCII-equivalent to engine's `ILIKE`; non-ASCII caveat documented in cli-runtime.md). `hashtag_ids` stripped from cached `list`/`get` output to match engine response shape per §3a. No schema bump — every filterable indexed column already in place from 7b.1.

**Commit:** `feat: replica-backed reads for transactions (Step 7b.2.3)`

After 7b.2.3 ships, all 6 cacheable resources have replica-backed reads. The only remaining 7b sub-phase is **7b.3 — write-path refresh** (auto delta-sync after every successful write).

#### Step 7b.3 — Write-path refresh (shipped)

After every successful write, the CLI automatically runs a delta sync to keep the cache consistent. Errors during the post-write sync are non-fatal (the write already landed on the engine — the CLI prints a one-line stderr warning and exits 0). `--no-sync-after` (root flag, env `EXPENSE_NO_SYNC_AFTER`) skips the refresh — symmetric with `--no-cache` for reads, and useful when batching writes in a script that runs `expense sync` once at the end. Wired into every write site via a small `cache.refresh_after_write` helper plus `cache_after_write` in `expense.commands._resource` (one-liner in each command body and inside `run_toggle`); the HTTP client itself stays cache-agnostic.

**Commit:** `feat: cache refresh on writes (Step 7b.3)`

See [cli-runtime.md](cli-runtime.md) for the full runtime semantics across all phases.

---

## Step 8 — Activity + Exchange Rates

*Deliverable: niche read commands for audit trail and rate lookups. Both engine-direct (not on the §3b sync resource list).*

Shipped in two sub-steps so each lands as a reviewable unit; they share no code.

### Step 8.1 — `expense activity list` (shipped)

`GET /v1/activity` with optional `--resource-type` / `--resource-id` filters and `--limit` / `--offset` pagination. Human renderer maps action codes 1–4 to `CREATED` / `UPDATED` / `DELETED` / `RESTORED` (unknown codes fall through as the integer for forward compatibility) and deliberately omits `before_snapshot` / `after_snapshot` — those are large nested dicts, accessible via `--json`. Pagination hint reuses the existing `render_pagination_hint` helper.

**Commit:** `feat(activity): expense activity list — engine-direct audit log read (Step 8.1)`

### Step 8.2 — `expense rates get` (shipped)

`GET /v1/exchange-rates`. `--target` is required; `--base` and `--date` are omitted client-side when not provided so the engine's defaults (USD, today) apply rather than baking them into the CLI. `RATE_UNAVAILABLE` 422s flow through the standard `@handle_errors` envelope renderer — no command-specific hint, since the engine's `fields.exchange_rate` message is more accurate than anything the CLI could synthesize.

**Commit:** `feat(rates): expense rates get — exchange-rate lookup (Step 8.2)`

**Follow-on (shipped 2026-07-06, polish-backlog §4.8):** `expense rates list [--date] [--limit] [--offset]` → `GET /v1/exchange-rates/history` — stored daily rates as a table (newest first, one row per pair per day, exact-day filter). Landed as the flat contract validator for the TUI's Rates history screen.

**Commit:** `feat(rates): history table — CLI rates list + TUI Rates screen (backlog §4.8)`

---

## Step 9 — CLI Complete (Done)

All command groups from [cli-spec.md](cli-spec.md) work end-to-end against the live engine. Gate closed 2026-05-10. Verification:

- **Every command has `--help` with an Example block.** Enforced by [tests/unit/test_command_surface.py](../tests/unit/test_command_surface.py), which walks the Typer tree (~63 leaves) and asserts an `Example:` block in every docstring. Caught 6 gaps during gate work — fixed in a separate commit (`version` + `reconcile update/delete/restore/complete/revert`).
- **`--json` works on every read command.** Same test asserts `json_output` parameter presence on the read-command allowlist + every `list`/`get` leaf.
- **Engine errors surface cleanly.** Five live smokes ran clean: bad PAT → 401 with `expense config set` hint; engine unreachable → exit 6 with friendly URL message; missing config → exit 3 with `expense config set` hint; incomplete `inbox promote` → 422 fields table + `expense inbox update` hint; account/category delete with active transactions → 409 with `expense <resource> archive` hint. Zero Python tracebacks across all paths.
- **A fresh user walks `expense config set` → `auth bootstrap` → `dashboard` with no surprises.** Wired as a live contract test at [tests/contract/test_freshman_flow.py](../tests/contract/test_freshman_flow.py), gated on `PYTEST_LIVE=1` + `EXPENSE_PAT`. Uses `CliRunner` with isolated `EXPENSE_CONFIG` / `EXPENSE_CACHE` paths so it never clobbers the dev install.
- **Archive/delete distinction respected.** `accounts/categories/hashtags list` accept `--include-archived` + `--include-deleted`; `inbox/transactions list` accept `--include-deleted` only (those resources have no archive state, per engine spec).

Next after this gate was Step 9.5 (interactive shell — shipped, then deleted at Step 10.X), then the `expense import` bulk importer and Step 10 (Textual TUI, current work). Post-Step-9 ergonomics (quick-add parser, shell completions, color conventions) follow Step 10.

---

## Step 9.5 — Interactive shell (`expense menu`)

*Deliverable: a menu-driven UI that wraps the now-complete flat command surface, for management/inspection workflows.*

The CLI ships two complementary front doors after Step 9:

- **`expense <command> [flags]`** (current) — flat invocations. Power users, scripting, automation, the future quick-add parser. Stays the canonical interface.
- **`expense menu`** — drops into an interactive walkdown over the same actions. For first-time discovery, infrequent management tasks ("archive an account I haven't touched in months"), and any case where the user prefers navigating to remembering flag names.

Both paths call the same underlying flat-command implementations. The menu is a thin presentation layer; it does not duplicate logic.

`expense` (no args) keeps its current behavior — prints the group help. Menu is opt-in via the explicit `expense menu` invocation.

**Shared design choices (apply to every sub-step below):**

- **Library:** `questionary` (built on `prompt_toolkit`). One dev dep. Supports text, single/multi-select, checkboxes, confirmations. Lighter than Textual; no full-screen panels in v1.
- **Inputs:** reads prompt only for filters (Enter = skip); writes prompt required fields first, then a "set additional optional fields?" yes/no fork. Foreign-key flags (`--account-id`, `--category-id`, `--hashtag-id`, `--reconciliation-id`) drive list-pickers off the local cache — UUIDs are never typed by hand.
- **Confirmations:** destructive actions reuse the same `--yes`-equivalent prompts the flat commands already gate on.
- **Quit / back:** `q` or Ctrl-C at any sub-menu returns to the previous menu; from the root, exits cleanly.
- **Output:** same renderers the flat commands use — no parallel formatting code. After an action, the menu prints the result and returns to the parent menu.
- **No `--json` in the menu UI**, no `--no-cache` toggle. Menu users want human output; scripters use flat commands.

**Out of scope for v1 of the menu:** no full-screen TUI panels, no live dashboards, no mouse, no color theming. Just menus → prompts → invoke → show result → back to menu.

**Phase structure:** split into 15 sub-steps, one per menu option (plus the foundation). Same precedent as Step 7b's per-resource slicing. Each phase is a reviewable PR ~100–300 LOC. Order is: foundation first, then daily-driver capture, then reads, then resource management, then plumbing.

### Step 9.5.1 — Foundation (mandatory first, shipped)

*Deliverable: `expense menu` opens the root menu, can quit cleanly, and the shared helpers later phases will reuse are in place.*

1. Add `questionary>=2.0` to `pyproject.toml`.
2. Scaffold `expense/menu/` package: `app.py` (entry + root menu loop), `prompts.py` (shared helpers — `pick_account`, `pick_category`, `pick_hashtag`, `pick_reconciliation`, `pick_date_range`, `prompt_signed_amount`, `confirm_destructive`, `confirm_and_submit`), `dispatch.py` (boundary to `expense.commands.*`).
3. Register `expense menu` as a Typer command in `expense/__main__.py`.
4. Root menu lists every group + `Quit`; selecting any non-Quit option is a stub that prints "(not yet wired)" and returns. Wiring lands per phase below.
5. `q` / Ctrl-C / `← Back` semantics implemented once, shared across all later phases.

**Verify:** `expense menu` opens the root menu, arrow-keys navigate, `q` exits with code 0, every group option is selectable (stubs OK).

**Commit:** `feat(menu): foundation — questionary, root menu, shared helpers (Step 9.5.1)`

### Step 9.5.2 — Log a transaction (root shortcut, shipped)

*Deliverable: the most-used action wired end-to-end through the menu.*

Wires the root-level "Log a transaction" entry to a required→optional fork flow (Title → Amount → Account picker → Category picker → "set optional?" → recap → confirm → submit). Includes the transfer-pair sub-flow (`--transfer --to-account-id --to-amount`).

**Verify:** menu-walk logs a real transaction against the live engine; transfer flow creates both legs paired via `transfer_transaction_id`.

**Commit:** `feat(menu): Log a transaction — root shortcut (Step 9.5.2)`

### Step 9.5.3 — Inbox menu (shipped)

*Deliverable: Inbox group menu + all 7 inbox flows.*

Wires `add`, `list`, `get`, `update`, `delete`, `restore`, `promote`. `add` reuses the same required→optional fork as `log`; `promote` surfaces the engine's 422 field hints inline.

**Verify:** add an incomplete inbox item via menu, try to promote (helpful error), fill in, promote, confirm transaction appears via `Transactions → List`.

**Commit:** `feat(menu): Inbox — add/list/get/update/delete/restore/promote (Step 9.5.3)`

### Step 9.5.4 — Transactions menu (shipped)

*Deliverable: Transactions group menu + all 6 transactions flows.*

Wires `list` (filter prompts: account, category, hashtag, reconciliation, date range presets, search, cleared tri-state, include-deleted, page size), `get`, `update`, `delete`, `restore`, `batch` (file-path prompt + local pre-check + atomic submit confirm).

**Verify:** list with each filter dimension individually; update a transaction; delete + restore; batch-import a 3-tx JSON file.

**Commit:** `feat(menu): Transactions — list/get/update/delete/restore/batch (Step 9.5.4)`

### Step 9.5.5 — Outstanding Amounts menu (shipped)

*Deliverable: the "Outstanding Amounts" menu entries (the `expense dashboard` / `GET /v1/dashboard` wrapper) + both variants.*

Wires `Outstanding Amounts (current month)` and `Outstanding Amounts (with archived panels)`. No further prompts — both go straight to render. (Surfaced under the Reports umbrella menu; the entries were renamed from "Dashboard" while still wrapping the engine's `dashboard` endpoint.)

**Verify:** both variants render against the live engine; archived panels show only when opted in.

**Commit:** `feat(menu): Dashboard — current month + archived variant (Step 9.5.5)`

> **Reordered 2026-05-12.** Config + Auth & profile were promoted ahead of Reports/Reconcile/Accounts/etc., and then Accounts/Categories/Hashtags were promoted ahead of Reconciliations/Sync/Activity/Rates — because the menu's whole point is "freshman walks the surface without `--help`" and the freshman gate at 9.5.16 unlocks the moment Accounts + Categories are wired (Reconcile/Sync/Activity/Rates aren't on the critical path). Shipped steps (9.5.1–9.5.8) keep their original numbers; only pending steps were renumbered. The Step 9.5 closeout (freshman-flow menu gate) was split out as 9.5.16 because it can only run once Config + Auth + Accounts + Categories are all wired.

### Step 9.5.6 — Config menu (shipped)

*Deliverable: Config group menu + all 5 config flows.*

Wires `Show current config`, `Set engine URL`, `Set token (PAT)`, `Set main currency (local default)`, `Clear all config` (destructive — double-confirm). First step a freshman walks: with this in place, the entire bootstrap is reachable from `expense menu`.

**Verify:** new user sets engine URL and PAT from the menu only; `Show current config` reflects the change; `Clear all config` requires double-confirm and wipes both fields.

**Commit:** `feat(menu): Config — show/set engine-url/set token/set main-currency/clear (Step 9.5.6)`

### Step 9.5.7 — Auth & profile menu (shipped)

*Deliverable: Auth group menu + all 5 auth flows.*

Wires `Show my profile (whoami)`, `Bootstrap (first-time login)`, `Update display name`, `Update settings…` (inner picker for theme, start_of_week, transaction_sort_preference, display_timezone, and the three sidebar toggles), `Update main currency` (its own menu entry with warning + double-confirm via `confirm_destructive` because the engine synchronously recalculates home-currency amounts).

**Verify:** bootstrap, profile update, settings update, main-currency change with double-confirm all round-trip against the engine and via `tests/unit/test_menu_auth.py` (deleted at 10.X); decline path on the main-currency confirm makes no PUT. Main-currency change surfaces the engine's inline `recalculation` summary (`Rewrote N transaction(s) in home currency.` from `total`, plus a yellow warning if `orphan_transfer_legs > 0`) — engine ships this on `PUT /v1/auth/settings` per the null-over-omission rule; the renderer skips the field cleanly when null.

**Commit:** `feat(menu): Auth & profile — whoami/bootstrap/profile/settings/main_currency (Step 9.5.7)`

### Step 9.5.8 — Reports menu (shipped)

*Deliverable: Reports group menu + single-month + range flows.*

Wires `Monthly report (single month)` (month prompt + "show hashtag breakdown?" toggle) and `Monthly report (range)` (from/to prompts + "expand by hashtag?" toggle + 24-month span guard). If the underlying renderer doesn't yet resolve hashtag UUIDs to names, this phase upgrades it — small CLI-side join against the cached hashtag list, no engine change.

**Verify:** single-month tree shows multi-hashtag combos like `Food + Club`; range matrix renders compactly by default; expand-by-hashtag toggle adds one row per combo per category.

**Commit:** `feat(menu): Reports — single month + range with hashtag tree (Step 9.5.8)`

### Step 9.5.9 — Accounts menu (shipped)

*Deliverable: Accounts group menu + all 8 account flows.*

Wires `list` (with archived/deleted/people toggles), `get`, `create` (with currency-code immutability warning), `update`, `archive`, `unarchive`, `delete`, `restore`.

**Verify:** full CRUD + archive/unarchive/delete/restore round trip; `update --currency-code` blocked at parse time with friendly hint.

**Commit:** `feat(menu): Accounts — CRUD + archive/restore (Step 9.5.9)`

### Step 9.5.10 — Categories menu (shipped)

*Deliverable: Categories group menu + all 8 category flows.*

Wires the same template as Accounts, with system-category guard (engine 403 on `@Debt` / `@Transfer` rename/delete/archive rendered as "System categories cannot be modified").

**Verify:** full CRUD round trip; system-category rejection renders cleanly.

**Commit:** `feat(menu): Categories — CRUD + archive/restore + system guard (Step 9.5.10)`

### Step 9.5.11 — Hashtags menu (shipped)

*Deliverable: Hashtags group menu + all 8 hashtag flows.*

Wires the same template; `delete` warning mentions junction-row cascade (restore does NOT undo).

**Verify:** full CRUD round trip; delete-cascade warning surfaces before submit.

**Commit:** `feat(menu): Hashtags — CRUD + archive/restore (Step 9.5.11)`

### Step 9.5.11b — Clear-on-navigate UX (shipped)

*Deliverable: terminal wipes on every menu transition; status messages stay readable.*

Adds `expense/menu/term.py` (deleted at 10.X) with `clear_screen()` (gentle viewport clear via `click.clear()`, preserves scrollback so `print_recap()` audit stays intact). Two-point clear in every menu loop (root + 9 groups): before each `questionary.select` and before each handler dispatch. Coupled audit: every early-return that prints user-facing status (`Aborted.` / `No changes.` / `Could not load …` / file errors) now calls `common.pause()` before returning, so the message stays readable instead of flashing under the next clear. Opt-out via `EXPENSE_NO_CLEAR=1` (matches `EXPENSE_NO_SYNC_AFTER` convention); no `--no-clear` flag since menu is TTY-only.

**Verify:** menu transitions render on a clean screen; abort/no-changes paths show `Press Enter to return…`; scrollback still contains prior recap lines (Cmd+UpArrow); `EXPENSE_NO_CLEAR=1 expense menu` matches pre-9.5.11b behavior.

**Commit:** `feat(menu): clear-on-navigate UX — wipe viewport on every menu transition (Step 9.5.11b)`

### Step 9.5.12 — Reconciliations menu (shipped)

*Deliverable: Reconciliations group menu + all 10 reconcile flows including `$EDITOR` reorder.*

Wires `list`, `get`, `create` (with `--source manual|chained` + `--beginning-balance` mutual-exclusion guard), `update`, `delete`, `restore`, `complete`, `revert` (extra-strong confirm), `move` (with `--to | --before | --after` mutex), `reorder` (reuses [expense/_editor.py](../expense/_editor.py) without modification).

**Verify:** create chained vs manual; complete + revert prints lock/unlock counts; `move` reorders a single row; `reorder` opens `$EDITOR`, accepts the rearranged file, prints recalculated_count.

**Commit:** `feat(menu): Reconciliations — full lifecycle + $EDITOR reorder (Step 9.5.12)`

### Step 9.5.13 — Sync menu (shipped)

*Deliverable: Sync group menu + both sync variants.*

Wires `Refresh (delta sync)` and `Full rebuild (--full)`. Each prints the per-resource count summary the flat command already renders.

**Verify:** delta sync after a no-op shows mostly zeros; `--full` rebuilds cache.

**Commit:** `feat(menu): Sync — delta + full rebuild (Step 9.5.13)`

### Step 9.5.14 — Activity log menu (shipped)

*Deliverable: Activity group menu + 3 activity flows.*

Wires `List all recent activity`, `Filter by resource type`, `Filter by specific record` — same underlying `activity list` with different flag presets.

**Verify:** each entry surfaces the expected activity rows; pagination hint renders.

**Commit:** `feat(menu): Activity log — list + filter variants (Step 9.5.14)`

### Step 9.5.15 — Exchange rates menu (shipped)

*Deliverable: Exchange rates group menu + lookup flow.*

Wires `Look up a rate` (target required; base + date optional with engine-default fallbacks).

**Verify:** `USD → PEN` lookup returns a number; missing target prompts; engine `RATE_UNAVAILABLE` 422 renders cleanly.

**Commit:** `feat(menu): Exchange rates — lookup (Step 9.5.15)`

### Step 9.5.16 — Step 9.5 closeout (freshman-flow menu gate) (shipped)

*Deliverable: Extend [tests/contract/test_freshman_flow.py](../tests/contract/test_freshman_flow.py) (or add a sibling) to drive the menu end-to-end. Closes Step 9.5.*

Shipped as a sibling, `tests/contract/test_freshman_flow_menu.py` (deleted at 10.X), driving the menu group flows per-leg against the live engine; the flat-command gate stays untouched alongside it.

Walks `expense menu` through `Config → Set engine URL → Set token → Auth → Bootstrap → Accounts → Create → Categories → Create → Log → Outstanding Amounts` against the live engine without consulting `--help` or memorizing a flag. No new feature code — purely a gate that proves the freshman UX holds together. Depends on Config (9.5.6), Auth (9.5.7), Accounts (9.5.9), Categories (9.5.10).

**Verify:** the live freshman walk passes under `PYTEST_LIVE=1 EXPENSE_PAT=<token>`.

**Commit:** `test(menu): freshman flow E2E via menu — Step 9.5 closeout (Step 9.5.16)`

---

**Step 9.5 done** — 9.5.16 landed; the freshman-flow menu walk passes against the live engine.

> **Deleted 2026-07-02 (Step 10.X).** The questionary `expense menu` built in Step 9.5 was superseded by the Textual TUI (`expense world`, Step 10) and has been **removed** — `expense/menu/`, the `test_menu_*.py` suite, `test_freshman_flow_menu.py`, the `expense menu` Typer command, and the now-unused `questionary` dependency are all gone. Retired ahead of full TUI parity by decision; no capability was lost because the flat commands are the complete contract-validator surface. The narrative below is retained as shipped history.

---

## Step 10 — Interactive TUI (`expense world`)

*Deliverable: a retained-mode Textual terminal app — the interactive front door, which replaced the questionary `expense menu` (deleted at Step 10.X). Full plan: [tui-plan.md](tui-plan.md).*

The TUI is a new **client** of the same engine-integration layer (HTTP client, SQLite replica, error envelope, name resolution, `refresh_after_write`). It implements **zero** business logic — the thin-wrapper rule holds. The one enabling refactor is the **fetch/print split**: commands that fetch *and* print get a pure `fetch_*(cfg, …) -> dict` extracted, which both the typer command and the TUI call. The synchronous engine client runs inside a Textual `@work(thread=True)` worker so the UI never blocks.

**Resolved open decisions** (from [tui-plan.md §9](tui-plan.md)): entry command is **`expense world`** (#1); the TUI **replaced** `expense menu`, now deleted (#2 — see 10.X); reconcile reorder **shells out to `$EDITOR`** for v1 (#4). Still open: designer's final theme tokens (#3), minimum terminal size fallback (#5).

### Step 10.P0 — Walking skeleton (shipped)
`expense world` launches; neutral theme; header banner + home menu with live status (the status line was later **removed by decision** at [polish-backlog.md](polish-backlog.md) §4.3 — it reported config presence as "connected" without ever probing the engine); Outstanding Amounts wired to live data (flat, then interactive category tree) via the worker helper. De-risked Textual + async + data-reuse.

### Step 10.P1 — Read views (shipped)
List screens for Inbox, Transactions, Accounts, Categories, Hashtags (chips); interactive `▼/▶` category tree on Outstanding Amounts; record detail modals; loading/empty/error states. Every read surface browsable.

### Step 10.P2 — Write flows (shipped — closed 2026-07-08)
Confirm modal (promote/delete/archive/restore/complete/revert/sync); the transaction form (Log / Inbox-add / edit — signed-amount validation, tri-state cleared, hashtag multi-select, conditional transfer sub-flow, inline 422s); small create/edit forms (account/category/hashtag); reconciliation lifecycle incl. `$EDITOR` reorder; Config + Auth & profile forms. Post-write refresh reuses `refresh_after_write`.

**Shipped so far:** Log/quick-add + transfer, edit transactions + inbox drafts, create forms, full Reconciliations screen, Config, Auth & profile, and the **System reads (Sync · Activity · Rates)** screens ([expense/tui/screens/system.py](../expense/tui/screens/system.py) — wired as three direct System-group entries in [home.py](../expense/tui/screens/home.py); enabling refactor was the `fetch_activity` / `fetch_rate` extractions on the flat commands). Two bugs surfaced and were fixed while landing these: (1) the shared modal CSS only centered `RecordModal`, so `SnapshotModal` (Activity's before/after detail) collapsed invisibly in the top-left — the `align: center middle` rule now covers every modal screen; (2) activity name resolution matched plural `resource_type` strings (`expense_transactions`, …) but the engine writes them **singular** (`transaction`, `account`, …), so the Resource column always fell back to the UUID prefix — `_resolve_resource_name` now maps the engine's real strings (fixing the flat `expense activity list` too).
**Closed 2026-07-08 with the final screen:** the **Monthly report** — a sliding **4-month grid** (categories × months, `▼/▶` hashtag rows, `[`/`]` slide the window), *not* the originally-sketched single-month view, which would have duplicated Outstanding Amounts (why + rejected alternatives: [decisions.md](decisions.md)). Enabling refactor was the `fetch_single_month`/`fetch_range`/`build_range_grid` extractions on the flat `reports` command. Every home-menu entry is now wired — no `"soon"` stubs remain. Detail: [tui-plan.md](tui-plan.md) Phase 2.

**Every new screen starts with an HTML mockup in [mockups/](mockups/) for review before code** (per [CLAUDE.md](../CLAUDE.md) "Mock every screen before building it").

### Step 10.P3 — Polish & hardening (in progress)
Shipped so far via the **2026-07-02 quality-review backlog — all seven sections closed 2026-07-06** (item-by-item record removed from the live file by decision; last full copy at commit `2d42482`): keymap contract (r always refreshes, y alone confirms, enter never mutates), theme-resolved sign-colored amounts with a literal-color guard test, fake home status removed, q scoped to Home, unarchive prompt-free, Rates as a history table, the CLI/TUI dedup refactors (`EngineWriteMixin.run_write`, one `FormScreen` base, shared `_resource.py` helpers), error-handling/help-text passes, shared test conftest + coverage, and the review's final nits (reconcile list table, Deleted columns, engine-owned report validation).
**Remaining:** the **2026-07-06 best-practices review** now open in [polish-backlog.md](polish-backlog.md); designer theme tokens; light theme + `NO_COLOR` paths; `?` help overlay; command palette; async edge cases + spinners; remaining Textual pilot tests. Exit criteria: shippable, feature-complete vs the flat command surface.

### Step 10.X — Delete `expense menu` (done — 2026-07-02)
Removed `expense/menu/` and its tests (`test_menu_*.py`, `test_freshman_flow_menu.py`), dropped the `expense menu` Typer command from `expense/__main__.py`, and pruned the now-unused `questionary` dependency from `pyproject.toml`. Done ahead of the original gate (which waited on 10.P2 + 10.P3) by decision — the flat commands are the complete surface, so nothing was lost. The two front doors are now the flat commands + `expense world`. The flat commands and their freshman-flow contract test ([test_freshman_flow.py](../tests/contract/test_freshman_flow.py)) are untouched.

---

## `expense import` — bulk `.xlsx` importer (shipped 2026-06-24)

Landed between Step 9.5 and Step 10, outside the numbered steps: `expense import <file.xlsx> [--apply] [--chunk-size N] [--json]` — parses a spreadsheet, resolves names to ids against the replica, plans, and writes via the engine's `transactions batch` endpoint. Dry-run preview is the default; `--apply` writes. Package: [expense/import_/](../expense/import_/) (`reader` / `parse` / `mapping` / `plan` / `apply`) + [expense/commands/import_cmd.py](../expense/commands/import_cmd.py); optional `openpyxl` dep under the `[import]` extra.

**Commit:** `feat(import): expense import — bulk .xlsx → engine via batch endpoint`

**Opening balances (added 2026-07-20):** rows titled `SALDO INICIAL` (case/whitespace-insensitive) are detected at parse time (`OpeningRow`), skip the category/hashtag requirement, dedupe per (account, currency) with `duplicate-opening` skips (first line wins), and route to the engine's `POST /accounts/{id}/opening-balance` (engine Step 9.4) instead of the batch — seeding the account under the `@Opening` system category, which flow reports exclude. Companion flat command: `expense accounts opening-balance`. Why + rejected alternatives: [decisions.md](decisions.md) "Opening balances are an engine concept".

---

## Post-Step-9 ergonomics

Land in this order, separately from Step 10:

1. **Quick-add natural-language parser** — `expense $20 today #food` → parses amount, sign, date, hashtag, title from free text and dispatches to the flat `log` command. Sign stays literal (`$20` = income, `-$20` = expense). The "low-friction capture" half of the dual-UX strategy; the TUI (`expense world`) is the "discoverable management" half.
2. **Shell completions** — zsh, bash, fish. `expense <TAB>` shows commands; `expense auth <TAB>` shows subcommands. Lowest-effort discoverability win for the flat path.
3. **`expense import csv`** — CSV variant of the shipped `.xlsx` importer (see "`expense import`" above). Only if a real migration needs it; the xlsx path already covers the original migration use case.
4. **Color conventions** — Rich-based output styling; opt-out flag for plain ANSI.
5. **Human-name resolution for reference flags** — accept either UUIDs or human-readable names on every command that takes an `--account-id` / `--category-id` / `--hashtag-id` / `--reconciliation-id`. CLI-side lookup via the existing list endpoints with disambiguation rules (case-insensitive exact match; reject ambiguous matches with a "be more specific" error pointing at `expense <resource> list`). UUIDs continue to pass through unchanged. Significant feature; deserves its own plan-mode session.

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
- **Testing.** Unit tests under `tests/unit/` use `respx` to mock httpx — fast, deterministic, engine-response fixtures checked in. Contract tests under `tests/contract/` hit the live engine (the local deployment since 2026-07-30) and run only when `PYTEST_LIVE=1` is set; they're the safety net for engine-shape drift. Every new command lands with at least one unit test covering the happy path and one covering the primary error shape.
- **Pagination.** Any endpoint the engine paginates (activity, transactions list, etc.) exposes `--limit` and `--cursor` flags. Human mode prints `next_cursor` as a hint under the table; `--json` passes it through verbatim.
- **`--verbose`.** Global flag handled by the HTTP client wrapper. Prints request + response (method, URL, status, headers, body) to stderr. Redacts the `Authorization` header.

---

*Last updated: 2026-07-06 (Step 10 TUI: P2 lacks only the Reports screen, P3 polish backlog fully closed; `expense import` + `rates list` recorded).*
