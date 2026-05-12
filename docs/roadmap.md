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

1. `reconcile list [--account]` — when filtered by account, sorted by `sort_order ASC, created_at ASC`. List rows surface `[chained from <id>]` / `[manual]` markers.
2. `reconcile create`, `get`, `update`, `delete`, `restore`. Beginning-balance UX:
   - omit `--beginning-balance` → engine chains from previous reconciliation (default for "next month follows last month")
   - pass `--beginning-balance <cents>` → engine forces `source = "manual"`, value stored verbatim
   - `--source manual|chained` toggle on `update` (mutually exclusive with `--beginning-balance` for `chained`).
3. `reconcile complete <id>` — prints the count of newly-locked transactions. Locks 4 transaction fields + 5 reconciliation fields (incl. `beginning_balance_source`).
4. `reconcile revert <id>` — requires `--yes`; unlocks all assigned transactions and the reconciliation's own balance/date fields. A meaningful audit event.
5. `reconcile move <id> --to <n> | --before <id> | --after <id>` — single-row reorder. CLI fetches current chain, computes the new `ordered_ids`, sends one `PUT /v1/accounts/{account_id}/reconciliations/order`.
6. `reconcile reorder --account <id>` — bulk reorder via `$EDITOR`. CLI writes the current order to a temp file, launches the user's editor, parses the saved result, sends one bulk request. Mirrors `git rebase -i` UX. First `subprocess + tempfile` pattern in the CLI; helper lives at `expense/_editor.py`.

**Verify:** `reconcile create` without `--beginning-balance` chains from previous month. `reconcile update <id> --source chained --beginning-balance N` rejected at parse time. `reconcile complete <id>` on an empty batch returns the engine's 422 with a friendly hint. `reconcile move <id> --after <other>` reorders with the cascade running engine-side. `reconcile reorder --account <id>` opens `$EDITOR`, accepts the rearranged file, and prints `recalculated_count` from the response.

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

---

## Step 9 — CLI Complete (Done)

All command groups from [cli-spec.md](cli-spec.md) work end-to-end against the live engine. Gate closed 2026-05-10. Verification:

- **Every command has `--help` with an Example block.** Enforced by [tests/unit/test_command_surface.py](../tests/unit/test_command_surface.py), which walks the Typer tree (~63 leaves) and asserts an `Example:` block in every docstring. Caught 6 gaps during gate work — fixed in a separate commit (`version` + `reconcile update/delete/restore/complete/revert`).
- **`--json` works on every read command.** Same test asserts `json_output` parameter presence on the read-command allowlist + every `list`/`get` leaf.
- **Engine errors surface cleanly.** Five live smokes ran clean: bad PAT → 401 with `expense config set` hint; engine unreachable → exit 2 with friendly URL message; missing config → exit 3 with `expense config set` hint; incomplete `inbox promote` → 422 fields table + `expense inbox update` hint; account/category delete with active transactions → 409 with `expense <resource> archive` hint. Zero Python tracebacks across all paths.
- **A fresh user walks `expense config set` → `auth bootstrap` → `dashboard` with no surprises.** Wired as a live contract test at [tests/contract/test_freshman_flow.py](../tests/contract/test_freshman_flow.py), gated on `PYTEST_LIVE=1` + `EXPENSE_PAT`. Uses `CliRunner` with isolated `EXPENSE_CONFIG` / `EXPENSE_CACHE` paths so it never clobbers the dev install.
- **Archive/delete distinction respected.** `accounts/categories/hashtags list` accept `--include-archived` + `--include-deleted`; `inbox/transactions list` accept `--include-deleted` only (those resources have no archive state, per engine spec).

Next: Step 9.5 (interactive shell) immediately after this gate, then Post-Step-9 ergonomics (quick-add parser, CSV import, shell completions, color conventions).

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

### Step 9.5.5 — Dashboard menu

*Deliverable: Dashboard group menu + both dashboard variants.*

Wires `View dashboard (current month)` and `View dashboard with archived panels`. No further prompts — both go straight to render.

**Verify:** both variants render against the live engine; archived panels show only when opted in.

**Commit:** `feat(menu): Dashboard — current month + archived variant (Step 9.5.5)`

### Step 9.5.6 — Reports menu

*Deliverable: Reports group menu + single-month + range flows.*

Wires `Monthly report (single month)` (month prompt + "show hashtag breakdown?" toggle) and `Monthly report (range)` (from/to prompts + "expand by hashtag?" toggle + 24-month span guard). If the underlying renderer doesn't yet resolve hashtag UUIDs to names, this phase upgrades it — small CLI-side join against the cached hashtag list, no engine change.

**Verify:** single-month tree shows multi-hashtag combos like `Food + Club`; range matrix renders compactly by default; expand-by-hashtag toggle adds one row per combo per category.

**Commit:** `feat(menu): Reports — single month + range with hashtag tree (Step 9.5.6)`

### Step 9.5.7 — Reconciliations menu

*Deliverable: Reconciliations group menu + all 10 reconcile flows including `$EDITOR` reorder.*

Wires `list`, `get`, `create` (with `--source manual|chained` + `--beginning-balance` mutual-exclusion guard), `update`, `delete`, `restore`, `complete`, `revert` (extra-strong confirm), `move` (with `--to | --before | --after` mutex), `reorder` (reuses [expense/_editor.py](../expense/_editor.py) without modification).

**Verify:** create chained vs manual; complete + revert prints lock/unlock counts; `move` reorders a single row; `reorder` opens `$EDITOR`, accepts the rearranged file, prints recalculated_count.

**Commit:** `feat(menu): Reconciliations — full lifecycle + $EDITOR reorder (Step 9.5.7)`

### Step 9.5.8 — Accounts menu

*Deliverable: Accounts group menu + all 8 account flows.*

Wires `list` (with archived/deleted/people toggles), `get`, `create` (with currency-code immutability warning), `update`, `archive`, `unarchive`, `delete`, `restore`.

**Verify:** full CRUD + archive/unarchive/delete/restore round trip; `update --currency-code` blocked at parse time with friendly hint.

**Commit:** `feat(menu): Accounts — CRUD + archive/restore (Step 9.5.8)`

### Step 9.5.9 — Categories menu

*Deliverable: Categories group menu + all 8 category flows.*

Wires the same template as Accounts, with system-category guard (engine 403 on `@Debt` / `@Transfer` rename/delete/archive rendered as "System categories cannot be modified").

**Verify:** full CRUD round trip; system-category rejection renders cleanly.

**Commit:** `feat(menu): Categories — CRUD + archive/restore + system guard (Step 9.5.9)`

### Step 9.5.10 — Hashtags menu

*Deliverable: Hashtags group menu + all 8 hashtag flows.*

Wires the same template; `delete` warning mentions junction-row cascade (restore does NOT undo).

**Verify:** full CRUD round trip; delete-cascade warning surfaces before submit.

**Commit:** `feat(menu): Hashtags — CRUD + archive/restore (Step 9.5.10)`

### Step 9.5.11 — Sync menu

*Deliverable: Sync group menu + both sync variants.*

Wires `Refresh (delta sync)` and `Full rebuild (--full)`. Each prints the per-resource count summary the flat command already renders.

**Verify:** delta sync after a no-op shows mostly zeros; `--full` rebuilds cache.

**Commit:** `feat(menu): Sync — delta + full rebuild (Step 9.5.11)`

### Step 9.5.12 — Activity log menu

*Deliverable: Activity group menu + 3 activity flows.*

Wires `List all recent activity`, `Filter by resource type`, `Filter by specific record` — same underlying `activity list` with different flag presets.

**Verify:** each entry surfaces the expected activity rows; pagination hint renders.

**Commit:** `feat(menu): Activity log — list + filter variants (Step 9.5.12)`

### Step 9.5.13 — Exchange rates menu

*Deliverable: Exchange rates group menu + lookup flow.*

Wires `Look up a rate` (target required; base + date optional with engine-default fallbacks).

**Verify:** `USD → PEN` lookup returns a number; missing target prompts; engine `RATE_UNAVAILABLE` 422 renders cleanly.

**Commit:** `feat(menu): Exchange rates — lookup (Step 9.5.13)`

### Step 9.5.14 — Auth & profile menu

*Deliverable: Auth group menu + all 5 auth flows.*

Wires `Show my profile (whoami)`, `First-time bootstrap`, `Update display name`, `Update settings (theme, week start, sidebar, …)`, `Update main currency` (the last gets its own warning + double-confirm because of engine-side recalc).

**Verify:** bootstrap, profile update, settings update, main-currency change with confirm all round-trip; recalc count surfaces after main-currency change.

**Commit:** `feat(menu): Auth & profile — whoami/bootstrap/profile/settings/main_currency (Step 9.5.14)`

### Step 9.5.15 — Config menu

*Deliverable: Config group menu + all 5 config flows. Closes Step 9.5.*

Wires `Show current config`, `Set engine URL`, `Set token (PAT)`, `Set main currency (local default)`, `Clear all config` (destructive — double-confirm).

**Verify:** the Step 9.5 freshman-flow contract test ([tests/contract/test_freshman_flow.py](../tests/contract/test_freshman_flow.py) extended for the menu) walks `Config → Set engine URL → Set token → Auth → Bootstrap → Accounts → Create → Log → Dashboard` end-to-end without consulting `--help` or memorizing a flag.

**Commit:** `feat(menu): Config + Step 9.5 closeout (Step 9.5.15)`

---

**Step 9.5 done** when 9.5.15 lands and the freshman-flow menu walk passes against the live engine.

---

## Post-Step-9 ergonomics

Land in this order, separately from Step 9.5:

1. **Quick-add natural-language parser** — `expense $20 today #food` → parses amount, sign, date, hashtag, title from free text and dispatches to the flat `log` command. Sign stays literal (`$20` = income, `-$20` = expense). The "low-friction capture" half of the dual-UX strategy; the menu is the "discoverable management" half.
2. **Shell completions** — zsh, bash, fish. `expense <TAB>` shows commands; `expense auth <TAB>` shows subcommands. Lowest-effort discoverability win for the flat path.
3. **`expense import csv`** — bulk transaction import for migration.
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
- **Testing.** Unit tests under `tests/unit/` use `respx` to mock httpx — fast, deterministic, engine-response fixtures checked in. Contract tests under `tests/contract/` hit the live staging engine and run only when `PYTEST_LIVE=1` is set; they're the safety net for engine-shape drift. Every new command lands with at least one unit test covering the happy path and one covering the primary error shape.
- **Pagination.** Any endpoint the engine paginates (activity, transactions list, etc.) exposes `--limit` and `--cursor` flags. Human mode prints `next_cursor` as a hint under the table; `--json` passes it through verbatim.
- **`--verbose`.** Global flag handled by the HTTP client wrapper. Prints request + response (method, URL, status, headers, body) to stderr. Redacts the `Authorization` header.

---

*Last updated: April 2026*
