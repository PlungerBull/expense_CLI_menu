# Expense CLI — Spec

> The `expense_CLI_menu` is the Hands. A Python (Typer) terminal interface that talks to the `expense_world_engine` via its HTTPS API. Every command is a thin wrapper around engine endpoints — no business logic lives in the CLI.
>
> Engine spec: [../../expense_world_engine/docs/engine-spec.md](../../expense_world_engine/docs/engine-spec.md) | Architecture: [../../expense_world_engine/docs/api-design-principles.md](../../expense_world_engine/docs/api-design-principles.md)
> Roadmap: [roadmap.md](roadmap.md)

---

## Status

Engine feature-complete through Phase 9.2 (archive/unarchive shipped on accounts, categories, hashtags + dashboard `include_archived` + attach guard). CLI work begins at Step 0 — see [roadmap.md](roadmap.md).

---

## Principles

- Every command is a thin wrapper around one or more engine API calls. No business logic in the CLI.
- Output is human-readable by default. Every read command supports `--json` for machine-readable output.
- The `debit_as_negative` convention is used end-to-end (negative = expense, positive = income). Enforced at input parsing and output rendering.
- A fresh idempotency-key UUID is generated per write and sent as `X-Idempotency-Key`.
- Engine errors surface intact: human mode may prettify, `--json` passes through verbatim — never swallow, never reformat lossily.
- Destructive operations (delete, archive, revert) prompt for confirmation unless `--yes` / `-y` is passed.
- Archive vs delete distinction is honored (see [../../expense_world_engine/docs/engine-spec.md](../../expense_world_engine/docs/engine-spec.md) — archive = retired-but-real, delete = mistake/scrubbed).

---

## Auth model

**Resolved 2026-04-23 — PAT (Option B).** The engine ships long-lived Personal Access Tokens prefixed `ewe_pat_`; the middleware branches on the prefix and falls through to JWT verification (HS256 shared-secret or ES256 via Supabase JWKS) for anything else. The CLI treats the PAT as an opaque Bearer token and does no client-side validation. See engine commits `3f729b2` + `b001b85` and the PAT project memory for details.

The user obtains a PAT out-of-band for now: direct call to `POST /v1/auth/pat` with their Supabase JWT, which returns the plaintext token exactly once. A future web dashboard will issue PATs; CLI-side `auth pat create` / `auth pat revoke` commands are deferred until the core daily-driver flow is proven.

All engine endpoints except `GET /health` are mounted under `/v1/`. The CLI HTTP client's base path is `<engine_url>/v1` with `/health` as the one unauthenticated, un-prefixed exception.

Config lives in `~/.expense-config` (chmod 600) with the following fields:

| Field | Purpose |
|---|---|
| `engine_url` | Base URL of the engine (prod: `https://expense-world-engine.onrender.com`) |
| `token` | PAT (prefix `ewe_pat_`). Sent verbatim as `Authorization: Bearer <token>`. |
| `client_id` | Persistent UUID used as `X-Client-Id` for sync checkpoints (auto-generated on first run) |
| `main_currency` | Cached from `/v1/auth/me` for offline formatting hints |

---

## Command groups

### `expense config` *(CLI-local — not an engine feature)*
- `config set [--token <t>] [--engine-url <u>]`
- `config get`
- `config clear`

### `expense auth`
- `auth bootstrap` → `POST /v1/auth/bootstrap` (first-login upsert, idempotent). `--display-name` and `--timezone` are honored only on the first call; subsequent calls only bump `last_login_at`. Use `auth profile` / `auth settings --display-timezone` afterward to mutate.
- `auth me` (alias: `whoami`) → `GET /v1/auth/me`
- `auth profile` → `PUT /v1/auth/profile` — partial update of identity fields on the `users` row. v1 only exposes `--display-name`; engine rejects clearing to null. Bootstrap idempotency is preserved (re-bootstrap won't overwrite a profile-set name).
- `auth settings` → `PUT /v1/auth/settings` — partial update of `user_settings` fields only: `--theme`, `--start-of-week`, `--main-currency`, `--transaction-sort-preference`, `--display-timezone`, `--sidebar-show-bank-accounts`, `--sidebar-show-people`, `--sidebar-show-categories`. Changing `main_currency` triggers synchronous home-currency recalculation on the engine; the CLI confirms unless `--yes` is passed.
- `auth pat create` / `auth pat revoke` — **deferred.** For v1, PATs are issued via direct API call to `POST /v1/auth/pat` (requires a Supabase JWT); the CLI consumes the resulting token but does not issue/revoke.

### `expense accounts`
- `accounts list [--include-archived] [--include-deleted] [--include-people]`
- `accounts get <id>`
- `accounts create`, `update`, `delete`, `restore`
- `accounts archive <id>`, `accounts unarchive <id>`
- Currency immutability on update: pre-flight hint before the engine 422 lands.

### `expense categories`
- `categories list [--include-archived] [--include-deleted]`
- `categories get <id>`
- `categories create`, `update`, `delete`, `restore`
- `categories archive <id>`, `categories unarchive <id>`
- System categories (`@Debt`, `@Transfer`) cannot be renamed, deleted, or archived — the engine's 403 surfaces as a friendly message.

### `expense hashtags`
- Same shape as categories: `list`, `get`, `create`, `update`, `delete`, `restore`, `archive`, `unarchive`. Hashtag archive does not cascade to junction rows (per engine spec).

### `expense inbox`
- `inbox list [--ready] [--include-deleted]` — `--ready` excludes items missing required fields AND items pointing at archived categories.
- `inbox add`, `get`, `update`, `delete`, `restore`
- `inbox promote <id>` — atomic inbox-to-ledger. On 422, the CLI pretty-prints the missing/blocking fields.

### `expense log`
- `log` — direct ledger entry (all required fields supplied as flags).
- `log --transfer --to-account <id>` — paired transfer creation in a single call.

### `expense transactions`
- `transactions list` — filters: `--account-id`, `--category-id`, `--hashtag-id`, `--reconciliation-id`, `--from`, `--to`, `--cleared/--no-cleared`, `--search`, `--include-deleted`.
- `transactions get <id>` — full detail; activity entries surface via `expense activity list --resource-type transaction --resource-id <id>`.
- `transactions update <id>` — partial update; `hashtag_ids` and `reconciliation_id` are editable via update. Field locking under completed reconciliations surfaces the engine's 422 clearly.
- `transactions delete <id>`, `transactions restore <id>`.
- `transactions batch` — atomic multi-tx create from flags or a stdin JSON payload.

### `expense reconcile`
- `reconcile list [--account-id <id>] [--include-deleted] [--limit <n>] [--offset <n>] [--json]` — when `--account-id` is set, sorted by `sort_order ASC, created_at ASC` (matches engine).
- `reconcile get <id> [--limit <n>] [--offset <n>] [--json]` — embeds a paged window of assigned transactions; surfaces a `transactions_truncated` hint pointing at `expense transactions list --reconciliation-id <id>` for full filter power.
- `reconcile create --account-id <id> --name <n> [--date-start ...] [--date-end ...] [--beginning-balance <cents>] [--ending-balance <cents>] [--source manual|chained] [--sort-order <n>]`. Omit `--beginning-balance` to chain from the previous reconciliation in the account.
- `reconcile update <id>` — partial update; supports `--source manual|chained`. `--source chained` is mutually exclusive with `--beginning-balance` (CLI blocks at parse). `--sort-order` rejected — use `move` / `reorder`.
- `reconcile delete <id> [--yes]` — only allowed in draft (engine 409 otherwise; CLI hints "revert first"). Cascade-unassigns attached transactions.
- `reconcile restore <id>` — restored row comes back empty (engine doesn't re-link transactions).
- `reconcile complete <id>` — flips status → completed; prints count of newly-locked transactions. Locks `amount_cents`, `account_id`, `title`, `date` on every assigned transaction plus the reconciliation's own balance/date fields.
- `reconcile revert <id> --yes` — flips status → draft; required `--yes` (audit event).
- `reconcile move <id> --to <n> | --before <id> | --after <id>` — single-row reorder via `PUT /v1/accounts/{account_id}/reconciliations/order`.
- `reconcile reorder --account-id <id>` — opens `$EDITOR` on a temp file with the current order; save and exit applies the new order via the bulk endpoint (git-rebase-i style).

### `expense dashboard`
- `dashboard` — current month: bank accounts, people, categories (with hashtag-combination breakdown), totals. Current-month-only because `GET /v1/dashboard` is current-month-only.
- `--include-archived` — adds `archived_accounts`, `archived_categories`, `archived_hashtags` panels with lifetime signed totals.
- `--json` — raw engine response.
- For historical months, see `expense reports monthly`.

### `expense reports`
- `reports monthly --date YYYY-MM` — single month.
- `reports monthly --from YYYY-MM --to YYYY-MM` — inclusive range (max 24 months). Mutually exclusive with `--date`.
- `--json` — raw engine response.

### `expense activity`
- `activity list [--resource-type <t>] [--resource-id <id>]` → `GET /v1/activity` (paginated audit log).

### `expense exchange-rates`
- `rates get --target <code> [--base USD] [--date YYYY-MM-DD]` → `GET /v1/exchange-rates`.
- `rates list [--date YYYY-MM-DD] [--limit N] [--offset N]` → `GET /v1/exchange-rates/history`
  (stored daily rates, newest first, one row per pair per day; exact-day filter, no fallback).

### `expense sync`
- `sync --full` — wildcard `*`, prints per-resource counts. Stateless.
- `sync --cache` — optional local SQLite store under `~/.expense-cache.sqlite3`; persists `sync_token` per `X-Client-Id`. Enables `--offline` on read commands. Ship only if UX demands it.

### `expense health` / `expense ping`
- `ping` → `GET /health`. Connectivity + auth sanity check.

---

## Global flags

| Flag | Applies to | Purpose |
|---|---|---|
| `--json` | every read command | Raw engine response, passed through verbatim |
| `--yes` / `-y` | every destructive command | Skip confirmation prompt |
| `--verbose` | every command | Print HTTP request/response for debugging |
| `--include-archived` | every `list` on resources that support archive | Include archived rows |
| `--include-deleted` | every `list` | Include soft-deleted rows (recovery view) |

---

## Output conventions

- **Tables** — Default rendering for every `<resource> list` flow. Plain ASCII columns, header row + separator dashes, two-space gap between columns. Built via the shared helpers in [expense/commands/_resource.py](../expense/commands/_resource.py): `render_table(headers, rows, *, align_right)`, `pad_left`, `pad_right`, `visible_len`. Per-resource columns are chosen for at-a-glance scannability, not field-by-field completeness — the verbose key:value dump remains the `<resource> get <id>` view, and `--json` keeps raw passthrough.
  - **Process rule:** before adding a new `list` renderer (or new columns to an existing one), propose the column set explicitly and get user sign-off. Never invent columns from the engine response shape alone — the user has the final say on what's scannable. The recommended workflow is the HTML mockup pattern used for Step 9.5.9/9.5.10 tables: dump the available fields, propose a short list with rationale, iterate, then implement.
  - **Color swatches** — When a column carries a `#RRGGBB` value, render as a 2-char ANSI 24-bit block via `color_swatch(hex, color=color_supported())`. `color_supported()` gates on `sys.stdout.isatty()` + the `NO_COLOR` env var ([no-color.org](https://no-color.org)). Non-TTY (pipe, file, test) falls back to the hex string so output stays grep-able.
  - **Name resolution** — ID columns on `inbox` / `transactions` / `reports` resolve to human names via cache-backed maps (`load_account_name_map`, `load_category_name_map`, `load_hashtag_name_map`). Unresolvable IDs fall back silently to the first 8 chars (e.g. `de37af15`); null IDs render as `—`. No warning on miss — the cache is the source of truth, missing means out-of-sync.
  - **Truncation** — Free-text columns (`title`, `description`) truncate at 24 visible chars with a trailing `…`. The full value is still in `get` / `--json`.
- **Amounts** — currency symbol prefix (`S/ 8,420.50`, `$5,200.00`). Native + home currency shown side-by-side when they differ. Outflows prefixed with `-`.
- **Dates (output)** — ISO 8601 by default (`2026-04-19`). Relative hints (`3 days ago`) only in detail (`get`) views.
- **Dates (input)** — Commands that accept `--date` (`expense log`, `expense inbox add`, `expense inbox update`; later `expense transactions update`) accept `YYYY-MM-DD`, `YYYY-MM-DD HH:MM[:SS]`, `YYYY-MM-DDTHH:MM[:SS]`, `YYYY-MM-DDTHH:MM:SSZ`, or `YYYY-MM-DDTHH:MM:SS±HH:MM`. Naive forms get the user's local timezone attached automatically by the CLI's normalizer in [expense/dates.py](../expense/dates.py). The engine itself rejects naive datetimes with 422 — the CLI's normalizer is the only place that accepts them.
- **Errors** — engine's `{ error: { code, message, fields } }` rendered as:
  ```
  Error: VALIDATION_ERROR — Amount must not be zero.
    amount_cents: Must not be zero.
  ```
- **`--json`** — pass-through. No reshaping, no truncation, no key renaming.

---

## To Be Defined

- **`expense world` (Step 10)** — the interactive front door: a retained-mode Textual TUI over the entire flat command surface. Triggered explicitly via `expense world`; `expense` (no args) keeps current group-help behavior. The TUI calls the same command implementations under the hood — single source of truth for behavior. Designed for management/inspection workflows; capture goes through quick-add. Replaced the questionary `expense menu` (Step 9.5), which was deleted at Step 10.X (2026-07-02). See [roadmap.md](roadmap.md) Step 10 and [tui-plan.md](tui-plan.md).
- **Quick-add natural-language parser (Post-Step-9)** — Todoist-style single-line capture (`expense $20 today #food` → parses amount/date/hashtag/title from free text). Sign stays literal: `$20` = income, `-$20` = expense; no default-to-expense magic. Pairs with `expense world` as the "fast capture" half of the dual-UX strategy.
- Import commands (`expense import csv`)
- Shell completions (zsh, bash, fish)
- Local SQLite cache for `--offline` reads (decision deferred to Step 7)
