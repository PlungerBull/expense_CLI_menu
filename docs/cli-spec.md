# Expense CLI — Spec

> The `expense_CLI_menu` is the Hands. A Python (Typer) terminal interface that talks to the `expense_world_engine` via its HTTPS API. Every command is a thin wrapper around engine endpoints — no business logic lives in the CLI.
>
> Engine spec: [../../expense_world_engine/docs/engine-spec.md](../../expense_world_engine/docs/engine-spec.md) — request/response conventions (error shape, null-over-omission, idempotency, sign) live in the engine's CLAUDE.md and engine-spec.md since the api-design-principles doc was retired (engine commit b75482b, 2026-08-04)
> Roadmap: [roadmap.md](roadmap.md)

---

## Status

Flat CLI is **complete** (Step 9 gate closed 2026-05-10, plus the `expense import` bulk importer and `rates list`). This document catalogs that surface; per-step status lives in [roadmap.md](roadmap.md), TUI status in [tui-plan.md](tui-plan.md).

---

## Principles

- Every command is a thin wrapper around one or more engine API calls. No business logic in the CLI.
- Output is human-readable by default. Every read command supports `--json` for machine-readable output.
- The `debit_as_negative` convention is used end-to-end (negative = expense, positive = income). Enforced at input parsing and output rendering.
- An idempotency-key UUID is minted per logical write and sent as `X-Idempotency-Key`; on timeout or 5xx the client re-sends the same key (bounded retry, see [cli-runtime.md](cli-runtime.md) Write semantics) so a retry can never double-apply.
- Engine errors surface intact: human mode may prettify, `--json` passes through verbatim — never swallow, never reformat lossily. (Deviations: see Sanctioned exceptions below.)
- Destructive operations (delete, revert) prompt for confirmation unless `--yes` / `-y` is passed. Archive/unarchive/restore are prompt-free — reversible toggles, not destruction (archive reclassified 2026-07-11; see [decisions.md](decisions.md)).
- Archive vs delete distinction is honored (see [../../expense_world_engine/docs/engine-spec.md](../../expense_world_engine/docs/engine-spec.md) — archive = retired-but-real, delete = mistake/scrubbed).

### Sanctioned exceptions

Deliberate, reviewed deviations from the principles above — do not re-flag in future reviews (backlog 2.6):

- **`accounts update --currency-code`** — exists solely to be rejected client-side with honest help text; currency is immutable after creation (the engine would 422 anyway). Fail-fast UX, not business logic. [`expense/commands/accounts_cmd.py`]
- **`import --json`** — emits a client-composed plan/result summary. The import pipeline is a composite of many engine calls (resolve, create, batch) with no single engine response to pass through — the only non-verbatim `--json` in the layer. [`expense/commands/import_cmd.py`]
- **TUI transfer "To amount" auto-sign** — the Log form takes a magnitude and applies the sign opposite to Amount, mirroring the engine's zero-sum transfer rule (both legs same sign → 422); the computed signed value is always visible before submit. Kept by explicit user decision (backlog 2.1, mockup `expense-world-transfer-to-amount-2.1.html`). [`expense/tui/screens/quick_log.py` `_commit_to_amount`]

---

## Auth model

**Resolved 2026-04-23 — PAT (Option B).** The engine ships long-lived Personal Access Tokens prefixed `ewe_pat_`; the middleware branches on the prefix and falls through to JWT verification (HS256 shared-secret or ES256 via Supabase JWKS) for anything else. The CLI treats the PAT as an opaque Bearer token and does no client-side validation. See engine commits `3f729b2` + `b001b85` and the PAT project memory for details.

The user obtains a PAT out-of-band for now. Local profile (active since 2026-07-30): mint by direct insert into `personal_access_tokens` (SHA-256 of the plaintext + `token_prefix`; see engine `deploy/local/README.md`) — no JWT needed, since PATs are engine-native. Cloud profile: `POST /v1/auth/pat` with a Supabase JWT, plaintext returned exactly once. A future web dashboard will issue PATs; CLI-side `auth pat create` / `auth pat revoke` commands are deferred until the core daily-driver flow is proven.

All engine endpoints except `GET /health` are mounted under `/v1/`. The CLI HTTP client's base path is `<engine_url>/v1` with `/health` as the one unauthenticated, un-prefixed exception.

Config lives in `~/.expense-config` (chmod 600) with the following fields:

| Field | Purpose |
|---|---|
| `engine_url` | Base URL of the engine (local profile: `http://127.0.0.1:8000`; mothballed cloud: `https://expense-world-engine.onrender.com`) |
| `token` | PAT (prefix `ewe_pat_`). Sent verbatim as `Authorization: Bearer <token>`. |
| `main_currency` | Mirrored from `/v1/auth/me` for formatting hints |

(A legacy `client_id` field may linger in configs written before 2026-08-06; it is ignored on load. It keyed the deleted `/sync` checkpoints — see [decisions.md](decisions.md) "Delete the local replica".)

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
- `accounts opening-balance <id> --amount <signed-cents> [--date] [--title] [--exchange-rate]` → `POST /v1/accounts/{id}/opening-balance` — seeds the account's starting balance as a transaction under the `@Opening` system category (counts toward the balance, excluded from flow reports). One active opening per account; the engine's 409 says to edit/delete the existing seed instead.
- Currency immutability on update: pre-flight hint before the engine 422 lands.

### `expense categories`
- `categories list [--include-archived] [--include-deleted]`
- `categories get <id>`
- `categories create`, `update`, `delete`, `restore`
- `categories archive <id>`, `categories unarchive <id>`
- System categories (`@Debt`, `@Transfer`, `@Opening`) cannot be deleted or archived — the engine's 403 surfaces as a friendly message. (Renames are allowed; the engine resolves them by `system_key`.)

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

### `expense health` / `expense ping`
- `ping` → `GET /health`. Connectivity + auth sanity check.

### `expense import`
- `import <file.xlsx> [--apply] [--chunk-size N] [--json]` — bulk `.xlsx → engine` importer. Parses the spreadsheet, resolves names to ids, plans, then writes via the transactions batch endpoint. **Dry-run preview is the default**; `--apply` writes. Requires the `openpyxl` extra (`pip install -e ".[import]"`). Package: [expense/import_/](../expense/import_/).
- **Opening balances:** rows titled `SALDO INICIAL` (case/whitespace-insensitive) route to `POST /v1/accounts/{id}/opening-balance` instead of the batch — their category/hashtag cells may be blank. One per (account, currency): extra rows are skipped as `duplicate-opening` (first line wins) and listed in the dry-run. A 409 at apply time (re-run, or account already seeded) counts as already-present, mirroring batch dedup semantics.

### `expense world`
- `world` — launches the Textual TUI, the interactive front door over the same fetch/write layer. `expense` (no args) keeps group-help behavior. Replaced the questionary `expense menu` (deleted at Step 10.X, 2026-07-02). Full plan and status: [tui-plan.md](tui-plan.md).

---

## Global flags

| Flag | Applies to | Purpose |
|---|---|---|
| `--json` | every read command | Raw engine response, passed through verbatim |
| `--yes` / `-y` | every destructive command (delete, revert, clear) | Skip confirmation prompt |
| `--verbose` | every command (root flag) | Print HTTP request/response for debugging |
| `--include-archived` | every `list` on resources that support archive | Include archived rows |
| `--include-deleted` | every `list` | Include soft-deleted rows (recovery view) |

---

## Output conventions

- **Tables** — Default rendering for every `<resource> list` flow. Plain ASCII columns, header row + separator dashes, two-space gap between columns. Built via the shared helpers in [expense/commands/_resource.py](../expense/commands/_resource.py): `render_table(headers, rows, *, align_right)`, `pad_left`, `pad_right`, `visible_len`. Per-resource columns are chosen for at-a-glance scannability, not field-by-field completeness — the verbose key:value dump remains the `<resource> get <id>` view, and `--json` keeps raw passthrough.
  - **Process rule:** before adding a new `list` renderer (or new columns to an existing one), propose the column set explicitly and get user sign-off. Never invent columns from the engine response shape alone — the user has the final say on what's scannable. The recommended workflow is the HTML mockup pattern used for Step 9.5.9/9.5.10 tables: dump the available fields, propose a short list with rationale, iterate, then implement.
  - **Color swatches** — When a column carries a `#RRGGBB` value, render as a 2-char ANSI 24-bit block via `color_swatch(hex, color=color_supported())`. `color_supported()` gates on `sys.stdout.isatty()` + the `NO_COLOR` env var ([no-color.org](https://no-color.org)). Non-TTY (pipe, file, test) falls back to the hex string so output stays grep-able.
  - **Name resolution** — ID columns on `inbox` / `transactions` / `reports` resolve to human names via live reference-list maps (`load_account_name_map`, `load_category_name_map`, `load_hashtag_name_map`). Unresolvable IDs fall back silently to the first 8 chars (e.g. `de37af15`); null IDs render as `—`. No warning on miss — a name-map hiccup must never break a listing.
  - **Truncation** — Free-text columns (`title`, `description`) truncate at 24 visible chars with a trailing `…`. The full value is still in `get` / `--json`.
- **Pagination (human mode)** — every `<resource> list` defaults to `--limit 20` (`DEFAULT_PAGE_ROWS` in [expense/commands/_resource.py](../expense/commands/_resource.py); the TUI windows at min(20, what fits the terminal) since 2026-07-13, with 20 as its cap and pre-layout fallback); when more rows exist, `render_pagination_hint` appends `(showing 20 of 133; pass --offset 20 --limit 20 for more)`. Explicit `--limit`/`--offset` always win. `--json` sends **no** default limit — the request and body stay exactly what the flags say. `accounts list` carries the same flags (the engine pages `/accounts` despite the spec's flat-list wording — gap noted at commit `4ef5c55`). Decided 2026-07-11 (TUI side amended 2026-07-13); rationale + rejected alternatives in [decisions.md](decisions.md).
- **Amounts** — currency symbol prefix (`S/ 8,420.50`, `$5,200.00`). Native + home currency shown side-by-side when they differ. Outflows prefixed with `-`.
- **Dates (output)** — ISO 8601 by default (`2026-04-19`). Relative hints (`3 days ago`) only in detail (`get`) views.
- **Dates (input)** — Commands that accept `--date` (`expense log`, `expense inbox add`, `expense inbox update`, `expense transactions update`) accept `YYYY-MM-DD`, `YYYY-MM-DD HH:MM[:SS]`, `YYYY-MM-DDTHH:MM[:SS]`, `YYYY-MM-DDTHH:MM:SSZ`, or `YYYY-MM-DDTHH:MM:SS±HH:MM`. Naive forms get the user's local timezone attached automatically by the CLI's normalizer in [expense/dates.py](../expense/dates.py). The engine itself rejects naive datetimes with 422 — the CLI's normalizer is the only place that accepts them.
- **Errors** — engine's `{ error: { code, message, fields } }` rendered as:
  ```
  Error: VALIDATION_ERROR — Amount must not be zero.
    amount_cents: Must not be zero.
  ```
- **`--json`** — pass-through. No reshaping, no truncation, no key renaming.

---

## To Be Defined

- **Quick-add natural-language parser (Post-Step-9)** — Todoist-style single-line capture (`expense $20 today #food` → parses amount/date/hashtag/title from free text). Sign stays literal: `$20` = income, `-$20` = expense; no default-to-expense magic. Pairs with `expense world` as the "fast capture" half of the dual-UX strategy.
- Shell completions (zsh, bash, fish)
- `expense import csv` — CSV variant of the shipped `.xlsx` importer, only if a real migration needs it (see [roadmap.md](roadmap.md) Post-Step-9 ergonomics)

*(Resolved and moved above: `expense world` shipped as a command — see its group entry. The local SQLite cache shipped cache-by-default through Step 7b.3, then was deleted 2026-08-06 with the engine's `/sync` — see [decisions.md](decisions.md) "Delete the local replica".)*
