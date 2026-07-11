# CLI Runtime Behavior

How the CLI behaves at runtime — sync model, write semantics, identity, error handling. Companion to [cli-spec.md](cli-spec.md) (which catalogs commands and flags). The architectural standard this document implements is [api-design-principles.md §3b](../../expense_world_engine/docs/api-design-principles.md) ("Client Local Replica Standard"); this file is the CLI-side specifics.

## Overview

The CLI is a thin wrapper around the engine. It holds no business logic. The engine is the only authoritative store; anything cached client-side is a disposable performance optimization that can be rebuilt at any time from `GET /sync`.

Everything in this document applies equally to the Textual TUI (`expense world`): it is another client of the same layer — same HTTP client, same replica, same `fetch_*` functions and `refresh_after_write` — not a separate runtime. Likewise the bulk importer (`expense import`), which is engine-direct batched writes (see "Write semantics").

Long-term the CLI is **cache-by-default** (matches iOS, web, every interactive client per §3b): a local SQLite replica under `~/.expense-cache.sqlite3` powers instant reads, with `GET /sync` keeping it current. The **stateless mode** is the explicit escape hatch — `--no-cache` (root flag) or `EXPENSE_STATELESS=1` (env var) — for CSV imports, CI, cron jobs, and `jq` automation where per-invocation freshness matters more than speed.

The replica is being built in three phases:

- **7a (shipped)** — stateless `expense sync --full` only. No cache.
- **7b.1 (shipped)** — SQLite layer, delta sync, cold start, tombstones, `sync_token` persistence. Cache exists; `expense sync` fills/refreshes it.
- **7b.2.1 (shipped)** — replica-backed `list`/`get` for accounts, categories, hashtags. Auto cold-start when a read hits an empty cache. `--no-cache` is now meaningful on these commands.
- **7b.2.2 (shipped)** — replica-backed reads for inbox + reconciliations. Inbox `--ready` filter fully replicated as SQL JOIN against cached accounts/categories; `--ready`/`--overdue` mirror the engine's UTC timestamp comparisons (`i.date <= now()` / `< now()`) with `now` passed as a parameter (backlog 2.3). `reconciliations get` embeds paginated transactions from the cached transactions table.
- **7b.2.3 (shipped)** — replica-backed reads for transactions. 8 filters incl. `--hashtag-id` (SQLite `json_each` containment) and `--search` (`LIKE … COLLATE NOCASE`, ASCII-equivalent to engine `ILIKE`). `hashtag_ids` is stripped from cached `list`/`get` output to match engine response shape.
- **7b.3 (shipped)** — write-path refresh. Every successful write fires a follow-up `GET /sync` to keep the replica current. Errors during the post-write sync are non-fatal (the write already landed). `--no-sync-after` (root flag, env `EXPENSE_NO_SYNC_AFTER`) skips the refresh for batch scripts.

## Sync model

The engine endpoint `GET /v1/sync` accepts `sync_token` with two meanings:

- **`sync_token=*`** → full snapshot. Engine returns every active row across all resources, cuts a fresh server-side checkpoint under `(user_id, X-Client-Id)`, and returns a new opaque token. No tombstones.
- **`sync_token=<uuid>`** → delta. Engine looks up the checkpoint for `(user_id, X-Client-Id)`, returns only rows whose `updated_at` is newer than that checkpoint, **including tombstones** (so the client can prune its local replica). Returns a new token.

The CLI maps onto these two modes through different invocation forms.

## Phasing

| Invocation | Behavior (today, Step 7b.3) |
|---|---|
| `expense sync` (bare) | Delta sync against cache; cold-starts on first run |
| `expense sync --full` | Cold start: wipe + full pull + rebuild cache |
| `expense sync --no-cache` | Stateless full snapshot; cache untouched |
| `EXPENSE_STATELESS=1 expense sync` | Same as `--no-cache` |
| `expense accounts list/get` | **Replica-backed** by default; `--no-cache` round-trips engine |
| `expense categories list/get` | **Replica-backed** |
| `expense hashtags list/get` | **Replica-backed** |
| `expense inbox list/get` | **Replica-backed** |
| `expense reconcile list/get` | **Replica-backed** (`get` embeds paginated cached transactions) |
| `expense transactions list/get` | **Replica-backed** (8 filters incl. `--hashtag-id`, `--search`; `hashtag_ids` stripped from output) |
| `expense dashboard`, `reports/*`, `activity`, `rates`, `whoami`, `ping` | Engine-only (FX drift / audit log and rates aren't in `/sync`) |
| `expense reconcile move/reorder` | Engine-direct internal reads (write-path workflow) |
| Writes (`create`/`update`/`delete`/`complete`/`log`/etc.) | Engine-direct; **post-write auto delta sync** keeps the cache current. `--no-sync-after` (or `EXPENSE_NO_SYNC_AFTER=1`) skips the refresh for batch scripts. |

## Write semantics

Writes always go straight to the engine. There is **no offline write queue, no buffering, no replay**.

- Every write command (`transactions create`, `accounts update`, `reconcile complete`, …) is a direct API call over HTTPS the moment you press enter.
- Each write request carries an `X-Idempotency-Key` (UUID) minted once per logical write by `ExpenseClient`; retrying a failed write is safe — the engine returns the original response from `idempotency_keys` (24h TTL).
- `ExpenseClient` itself retries a timed-out or 5xx write up to twice (1s/2s backoff) **with the same key** before surfacing the error, printing a stderr notice per attempt — the engine replay is what makes this safe. Connect failures are not retried (the engine isn't reachable at all), and reads never auto-retry.
- Network errors otherwise fail fast. The CLI prints the error and exits non-zero. A developer at a terminal — or a script in CI — gets synchronous feedback. Silent buffering would corrupt the contract that the next command can rely on the previous command having landed.

The Todoist-style offline write queue is an iOS-only feature (§3b). The CLI does not get one. The web dashboard does not get one. If either client's product story changes, adding a queue is a per-client commitment, not an inherited default.

The bulk importer (`expense import --apply`) is the same contract at scale: chunked `transactions batch` calls (default 200/request), each engine-direct with its own fresh idempotency key; the default invocation is a dry-run plan that writes nothing.

**Post-write cache refresh.** After every successful write, the CLI fires a delta sync against `GET /v1/sync` to pull the engine's authoritative state for the affected rows into the local replica. This keeps cached reads consistent immediately after a user action — no manual `expense sync` required. Failures during the post-write sync are non-fatal: the write already landed on the engine, the CLI prints a one-line stderr warning (`Cache refresh failed after write: ... Run 'expense sync' to refresh.`) and exits 0. Pass `--no-sync-after` (root flag) or set `EXPENSE_NO_SYNC_AFTER=1` to skip the refresh — useful when a script batches many writes and runs `expense sync` once at the end. The flag is independent of `--no-cache`: with `--no-cache`, no post-write sync runs anyway (stateless mode means the replica is bypassed entirely).

## `X-Client-Id` lifecycle

- Generated once on first `expense config set` (a UUID, persisted in `~/.expense-config`).
- Stable across runs. Reused forever for this install. Never regenerated unless the user wipes the config.
- Sent on every request as `X-Client-Id: <uuid>`.
- Used by the engine to key per-client sync checkpoints in `sync_checkpoints`. Each `(user_id, client_id)` pair has independent checkpoint state.
- Forward-compat: the same UUID powers the future Step 7b replica's checkpoint — installing the replica later does not invalidate or rotate the client_id.

In stateless mode (Step 7b's `--no-cache`), the engine response with `sync_token=*` is identical regardless of `X-Client-Id`, so the implementation can either send the persisted ID or skip the header entirely. Today we send the persisted ID.

## Cache lifecycle

**Storage.** `~/.expense-cache.sqlite3` (override via `EXPENSE_CACHE` env var). `chmod 600` on creation. WAL journal mode for safe concurrent CLI invocations. Hybrid schema: typed columns for fields that 7b.2 read paths will filter or sort by (`id`, `user_id`, foreign keys, `date`, `deleted_at`, `version`, `updated_at`), plus a `body TEXT NOT NULL` column holding the full row as JSON. New non-indexed engine fields land in `body` without local migrations. Indexed-column changes bump `SCHEMA_VERSION` and trigger wipe + cold-start.

**Tables.** Seven resource tables (`accounts`, `categories`, `hashtags`, `transactions`, `inbox`, `reconciliations`, `settings`) plus a singleton `_cache_meta` row tracking `schema_version`, `user_id`, `client_id`, `engine_url`, `token_fingerprint` (SHA-256 of the config token — the client-side proxy for "same principal", since there is no `/me` endpoint), `sync_token`, `last_synced_at`. Junction-flattened `transactions.hashtag_ids` ([§3a](../../expense_world_engine/docs/api-design-principles.md)) lives inside the `body` JSON.

**Cold start.** Triggered by `expense sync --full`, by bare `expense sync` against a cache with no stored `sync_token`, or by any health-check failure (schema mismatch, token fingerprint mismatch — token swap, engine_url mismatch, client_id mismatch, unknown-token 422 from engine). One accepted trade-off: JWT users cold-start on every rotation because the fingerprint changes with the token even for the same user; PATs — the recommended long-lived credential — are unaffected. Sequence: wipe the cache file, fetch `GET /v1/sync?sync_token=*&debit_as_negative=true`, populate, persist new token + identity. Re-runnable safely.

**Auto cold-start on reads.** Replica-backed read commands (currently accounts/categories/hashtags `list` and `get`, more in 7b.2.2 / 7b.2.3) call `cache.ensure_synced(client, cfg)` before querying. If the cache is missing/empty/unhealthy, this triggers a cold-start with a one-line stderr notice ("First-run sync against `<engine_url>` — this may take a moment...") so users understand why the first read is slow. Subsequent reads against a healthy cache run with no engine round-trip and no notice. The notice goes to stderr so `--json` on stdout stays pipe-clean.

**Delta sync.** Bare `expense sync` against a healthy cache. Reads stored token, fetches `GET /v1/sync?sync_token=<stored>&debit_as_negative=true`, applies inserts/updates/tombstones inside one SQLite transaction, persists new token. On unknown-token 422 → falls through to cold start automatically.

**Tombstones.** A row arriving with `deleted_at != null` deletes the row from the cache (physical delete — once a row is pruned, it's gone; no need to keep tombstones around once applied). Wildcard fetches never include tombstones; only deltas do. `--include-deleted` therefore always reads live — deleted rows exist only engine-side; the flag implies an engine round-trip without needing `--no-cache`.

**Cache disposal.** `expense config set --token`/`--engine-url` (when the effective value changes) and `expense config clear` wipe the replica automatically — a different credential or engine may mean a different user, and the old rows must not survive the switch. Users wanting a clean slate can also `rm ~/.expense-cache.sqlite3` and re-run `expense sync --full`. The cache also auto-wipes when the engine returns an unknown-token 422 (see "Cold start" above), and the token-fingerprint health check catches hand-edited configs the commands never saw.

**Never repair from partial local state.** Any inconsistency → cold start. The replica is disposable by design ([§3b](../../expense_world_engine/docs/api-design-principles.md)); recovery is always a full re-pull, never a stitched repair.

**Transaction wire-shape: `hashtag_ids` is stripped from cached `list`/`get` output.** Per [§3a](../../expense_world_engine/docs/api-design-principles.md), `hashtag_ids` is wire-format-only for `/sync`; the engine's `GET /v1/transactions` and `GET /v1/transactions/{id}` endpoints don't return it. The cache stores the array (so `--hashtag-id` filtering works via `json_each`) but strips it from emitted responses for byte parity with engine list/get.

**`--search` ASCII caveat.** SQLite's `LIKE … COLLATE NOCASE` is case-insensitive for ASCII inputs but not for full Unicode. The engine uses PostgreSQL `ILIKE` which is locale-aware. For ASCII titles/descriptions (the realistic case) results match between cached and engine paths; for non-ASCII, results may differ. If precise non-ASCII case-insensitivity matters, pass `--no-cache`.

**Read defaults (limits).** A cache list read with no explicit limit returns up to 100 rows (`_list_paginated` in [expense/cache/queries.py](../expense/cache/queries.py)) vs the engine's default 50 — deliberately left unaligned: changing the replica default would silently alter `--json` cache-read output, and internal full-table consumers (name maps) pass no limit. Human-mode CLI and the TUI never hit either default — since 2026-07-11 they send `limit=20` explicitly (see [decisions.md](decisions.md)).

## Home-currency drift warning

`amount_home_cents` and related fields in cached rows reflect FX rates **at sync time**, not now. Across a multi-day cache they drift. **Accounts are stricter still:** `/sync` returns `current_balance_home_cents: null` for every account row by design — only `GET /v1/dashboard` computes it against current FX rates. So `expense accounts list/get` returns null where engine-direct calls would return a value. Run `expense dashboard` or pass `--no-cache` for current balances.

Replica readers must:

- Prefer `GET /v1/dashboard` and `GET /v1/reports/*` for any balance-sensitive aggregate display (current balances, monthly totals, net-worth views). The engine recomputes these against current rates.
- Never sum `amount_home_cents` across cached transaction rows to derive balances or totals.
- Treat cached `*_home_cents` values as point-in-time hints, not current values.

This is a §3b commitment, not a CLI peculiarity — it applies to every cached client.

## CLI as equal client

The CLI does not get any endpoint, header, behavior, or shortcut that other clients won't get. Same `GET /sync`, same `X-Idempotency-Key`, same auth scheme, same error envelope.

What stays CLI-specific (and is OK to live only here):

- `~/.expense-config` filesystem storage (mobile uses keychain, web uses localStorage)
- [expense/dates.py](../expense/dates.py) — date input forgiveness for terminal humans
- [expense/_editor.py](../expense/_editor.py) — `$EDITOR` flow for `reconcile reorder`
- `--json` flag and the human-output renderers — terminal UX

What is NOT CLI-specific (and must never be):

- Sync semantics, idempotency keys, sign convention (`debit_as_negative`), error envelope shape, RFC 3339 dates, tombstone handling, junction-flattening (`hashtag_ids`). These are multi-client contracts; the CLI uses them faithfully so iOS and web inherit working patterns, not just specs.

## Working against the live engine

There is exactly **one engine: production** (`https://expense-world-engine.onrender.com`, hosted on Render). No staging, no sandbox — every PAT belongs to a real user and every write lands in a real ledger.

**Developer default is live.** Plain `expense …` commands read `~/.expense-config` — the developer's real credential — and hit production. Reads are always safe; ad-hoc writes are real writes. Don't run write commands casually to "see what happens"; use `--verbose` on a read, or the unit suite, to inspect behavior.

**Isolation levers, weakest to strongest:**

- `EXPENSE_CONFIG` + `EXPENSE_CACHE` env overrides redirect the config file and replica to any path (this is how the contract suite sandboxes itself). This isolates *local state only* — the same PAT still writes to the same user's ledger.
- A **separate PAT for a separate user** is the only true data isolation. PATs are issued out-of-band: `POST /v1/auth/pat` with a Supabase JWT returns the plaintext token (`ewe_pat_` prefix) exactly once — see [cli-spec.md](cli-spec.md) "Auth model" and the engine spec for the endpoint contract. CLI-side `auth pat create`/`revoke` are deferred.

**The contract suite** (`tests/contract/`) hits production deliberately and is double-gated: `PYTEST_LIVE=1 EXPENSE_PAT=<token> pytest tests/contract`. `EXPENSE_ENGINE_URL` overrides the target if one ever exists besides prod. What it does: walks real flows (the freshman gate: config → ping → bootstrap → accounts/categories create → log → dashboard), redirects `EXPENSE_CONFIG`/`EXPENSE_CACHE` to a temp dir so the developer's install is untouched, and cleans up after itself best-effort in reverse dependency order. Cleanup means **soft-deletes** — the run leaves tombstoned rows in the PAT user's account (visible under `--include-deleted`). Run it at step gates, when engine-shape drift is suspected, or before calling a release done — never in CI (deps and gating are designed so CI stays hermetic).

**Unit tests never touch the network.** `tests/unit/` is respx-mocked and hermetic; an autouse fixture in [tests/unit/conftest.py](../tests/unit/conftest.py) redirects `EXPENSE_CONFIG`/`EXPENSE_CACHE` so a test can never read the developer's real config. Never bypass it.

## Cross-references

- [api-design-principles.md §3b](../../expense_world_engine/docs/api-design-principles.md) — Client Local Replica Standard (the architectural source of truth for this doc)
- [api-design-principles.md §11](../../expense_world_engine/docs/api-design-principles.md) — `expense_world_cli — The Hands` (the CLI's role in the polyrepo)
- [api-design-principles.md §4](../../expense_world_engine/docs/api-design-principles.md) — Idempotency Keys (write semantics)
- [api-design-principles.md §9](../../expense_world_engine/docs/api-design-principles.md) — `debit_as_negative` (sign convention)
- [CLAUDE.md](../CLAUDE.md) — non-negotiable conventions (terse, project-loaded)
- [cli-spec.md](cli-spec.md) — command surface and flags
- [roadmap.md](roadmap.md) — phasing
