# CLI Runtime Behavior

How the CLI behaves at runtime — read/write semantics, identity, error handling. Companion to [cli-spec.md](cli-spec.md) (which catalogs commands and flags).

## Overview

The CLI is a thin wrapper around the engine. It holds no business logic and **no local state beyond `~/.expense-config`**. The engine is the only authoritative store, and it runs on the same machine (`http://127.0.0.1:8000`, local profile since 2026-07-30), so every read is a live loopback HTTP call.

Everything in this document applies equally to the Textual TUI (`expense world`): it is another client of the same layer — same HTTP client, same `fetch_*` functions — not a separate runtime. Likewise the bulk importer (`expense import`), which is engine-direct batched writes (see "Write semantics").

**History.** From Step 7b (2026-07) to 2026-08-06 the CLI kept a local SQLite replica (`~/.expense-cache.sqlite3`) hydrated from `GET /v1/sync`, and reads were cache-by-default with `--no-cache` as the escape hatch. That layer was deleted when the engine deleted `/sync` (engine rework WP4): with the engine on loopback, the replica's only value — hiding cloud latency — was gone, while its costs (staleness windows, a sync-contract error family, a dropped-writes bug class) remained. See [decisions.md](decisions.md) "Delete the local replica" for the full rationale. `--no-cache`, `--no-sync-after`, `EXPENSE_STATELESS`, `EXPENSE_NO_SYNC_AFTER`, `EXPENSE_CACHE`, and `expense sync` no longer exist.

## Read semantics

Every read command is a direct `GET` against the engine. There is no cache to warm, no staleness, and no drift: what a command prints is what the engine computed at that moment, including home-currency figures (converted at read time engine-side).

- List renderers resolve IDs to display names via live reference-list fetches (`load_account_name_map` / `load_category_name_map` / `load_hashtag_name_map` in [expense/commands/_resource.py](../expense/commands/_resource.py)) — the engine's responses are IDs-only by convention, and clients resolve names themselves. On any failure these maps degrade to `{}` and renderers fall back to 8-char short ids; a name-map hiccup never breaks a listing.
- `--include-deleted` is an ordinary query param — soft-deleted rows live engine-side only.
- Transactions and inbox reads always send `debit_as_negative=true`: every CLI/TUI surface renders debits negative, so the request pins the flag rather than depending on the engine default.

## Write semantics

Writes always go straight to the engine. There is **no offline write queue, no buffering, no replay**.

- Every write command (`transactions create`, `accounts update`, `reconcile complete`, …) is a direct API call the moment you press enter.
- Each write request carries an `X-Idempotency-Key` (UUID) minted once per logical write by `ExpenseClient`; retrying a failed write is safe — the engine returns the original response from `idempotency_keys` (24h TTL).
- `ExpenseClient` itself retries a timed-out or 5xx write up to twice (1s/2s backoff) **with the same key** before surfacing the error, printing a stderr notice per attempt — the engine replay is what makes this safe. Connect failures are not retried (the engine isn't reachable at all), and reads never auto-retry.
- Network errors otherwise fail fast. The CLI prints the error and exits non-zero. A developer at a terminal — or a script in CI — gets synchronous feedback. Silent buffering would corrupt the contract that the next command can rely on the previous command having landed.

An offline write queue remains a per-client commitment for a future mobile client, not an inherited default. The CLI does not get one.

The bulk importer (`expense import --apply`) is the same contract at scale: chunked `transactions batch` calls (default 200/request), each engine-direct with its own fresh idempotency key; the default invocation is a dry-run plan that writes nothing.

## CLI as equal client

The CLI does not get any endpoint, header, behavior, or shortcut that other clients won't get. Same REST endpoints, same `X-Idempotency-Key`, same auth scheme, same error envelope.

What stays CLI-specific (and is OK to live only here):

- `~/.expense-config` filesystem storage (a future mobile client would use its keychain)
- [expense/dates.py](../expense/dates.py) — date input forgiveness for terminal humans
- [expense/import_/](../expense/import_/) — the `.xlsx` reader behind `expense import`
- `--json` flag and the human-output renderers — terminal UX

What is NOT CLI-specific (and must never be): idempotency keys, sign convention (`debit_as_negative`), error envelope shape, RFC 3339 dates, IDs-only responses with client-side name resolution. These are multi-client contracts; the CLI uses them faithfully so future clients inherit working patterns, not just specs.

## Working against the live engine

There is exactly **one engine: the local deployment** (`http://127.0.0.1:8000`, launchd service on the owner's Mac — engine repo `deploy/local/README.md`; the Render/Supabase cloud profile is mothballed since 2026-07-30, see `deploy/cloud/README.md`). No staging, no sandbox — every PAT belongs to a real user and every write lands in the real ledger. "Live" means *your machine*, but the discipline is identical: it's the one true ledger.

**Developer default is live.** Plain `expense …` commands read `~/.expense-config` — the real credential — and hit the live local engine. Reads are always safe; ad-hoc writes are real writes. Don't run write commands casually to "see what happens"; use `--verbose` on a read, or the unit suite, to inspect behavior.

**Isolation levers, weakest to strongest:**

- `EXPENSE_CONFIG` env override redirects the config file to any path (this is how the contract suite sandboxes itself). This isolates *local config only* — the same PAT still writes to the same user's ledger.
- A **separate PAT for a separate user** is the only true data isolation. PATs are issued out-of-band: see [cli-spec.md](cli-spec.md) "Auth model" and the engine spec for the endpoint contract. CLI-side `auth pat create`/`revoke` are deferred.

**The contract suite** (`tests/contract/`) hits the live engine deliberately and is double-gated: `PYTEST_LIVE=1 EXPENSE_PAT=<token> pytest tests/contract`. `EXPENSE_ENGINE_URL` overrides the target (defaults suit the local profile). What it does: walks real flows (the freshman gate: config → ping → bootstrap → accounts/categories create → log → dashboard), redirects `EXPENSE_CONFIG` to a temp dir so the developer's install is untouched, and cleans up after itself best-effort in reverse dependency order. Cleanup means **soft-deletes** — the run leaves tombstoned rows in the PAT user's account (visible under `--include-deleted`). Run it at step gates, when engine-shape drift is suspected, or before calling a release done — never in CI (deps and gating are designed so CI stays hermetic).

**Unit tests never touch the network.** `tests/unit/` is respx-mocked and hermetic; autouse fixtures in [tests/unit/conftest.py](../tests/unit/conftest.py) redirect `EXPENSE_CONFIG` and block real sockets so a test can never read the developer's real config or ping a real engine. Never bypass them.

## Cross-references

- [CLAUDE.md](../CLAUDE.md) — non-negotiable conventions (terse, project-loaded)
- [cli-spec.md](cli-spec.md) — command surface and flags
- [decisions.md](decisions.md) — including "Delete the local replica" (2026-08-06)
- [roadmap.md](roadmap.md) — phasing (Step 7's replica is retired; see its banner)
