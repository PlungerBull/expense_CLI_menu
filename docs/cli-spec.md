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
- `transactions list` — filters: `--account`, `--category`, `--hashtag`, `--reconciliation`, `--from`, `--to`, `--cleared`, `--approved`, `--search`.
- `transactions get <id>` — full detail, optionally `--with-activity` to include activity log entries.
- `transactions update <id>` — partial update; `hashtag_ids` and `reconciliation_id` are editable via update. Field locking under completed reconciliations surfaces the engine's 422 clearly.
- `transactions delete <id>`, `transactions restore <id>`.
- `transactions batch` — atomic multi-tx create from flags or a stdin JSON payload.

### `expense reconcile`
- `reconcile list [--account]`
- `reconcile create`, `get`, `update`, `delete`, `restore`
- `reconcile complete <id>` — locks fields on included transactions; prints the count of newly-locked rows.
- `reconcile revert <id>` — unlocks fields; requires `--yes`.

### `expense dashboard`
- `dashboard` — current month: bank accounts, people, categories (with hashtag-combination breakdown), totals.
- `--include-archived` — adds `archived_accounts`, `archived_categories`, `archived_hashtags` panels with lifetime signed totals.
- `--month YYYY-MM` — switches to historical single month (uses `/reports/monthly`).
- `--json` — raw engine response.

### `expense reports`
- `reports monthly --year <y> --month <m>` — single month.
- `reports monthly --from YYYY-MM --to YYYY-MM` — inclusive range (max 24 months).

### `expense activity`
- `activity list [--resource-type <t>] [--resource-id <id>]` → `GET /v1/activity` (paginated audit log).

### `expense exchange-rates`
- `rates get --target <code> [--base USD] [--date YYYY-MM-DD]` → `GET /v1/exchange-rates`.

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

- **Tables** — monospace columns, header row + separator. Human mode only.
- **Amounts** — currency symbol prefix (`S/ 8,420.50`, `$5,200.00`). Native + home currency shown side-by-side when they differ. Outflows prefixed with `-`.
- **Dates** — ISO 8601 by default (`2026-04-19`). Relative hints (`3 days ago`) only in detail (`get`) views.
- **Errors** — engine's `{ error: { code, message, fields } }` rendered as:
  ```
  Error: VALIDATION_ERROR — Amount must not be zero.
    amount_cents: Must not be zero.
  ```
- **`--json`** — pass-through. No reshaping, no truncation, no key renaming.

---

## To Be Defined

- **Quick-add natural-language parser** — Todoist-style single-line capture (`expense $20 today #food` → parses amount/date/hashtag/title from free text). Deferred until after Step 9 so real usage patterns inform the grammar. Sign stays literal: `$20` = income, `-$20` = expense; no default-to-expense magic.
- Interactive TUI prompts (`expense inbox add` with no flags → interactive mode?)
- Import commands (`expense import csv`)
- Shell completions (zsh, bash, fish)
- Local SQLite cache for `--offline` reads (decision deferred to Step 7)
- Color conventions (Rich library? plain ANSI? none?)
