# Polish backlog — best-practices review 2026-07-06

Source: four-dimension parallel review (core infra / commands layer / TUI +
import / tests + CI), with every high finding spot-verified at its cited line
before filing. Scope rule unchanged: **polish + correctness only — no new
features.**

Baseline at review time: 805 unit tests passing (~17s), `ruff check` clean,
`ruff format --check` clean (113 files). Every CLAUDE.md non-negotiable
convention is pinned by a real test (verified item by item).

The previous backlog (quality review 2026-07-02, sections 1–7) was **fully
worked off** and its item-by-item record was removed from this file on
2026-07-06 by decision — see git history (last full copy at commit 2d42482)
if you need the old detail.

> **Mockup rule reminder:** items marked **[UI]** change something the user
> sees — per CLAUDE.md they need a mockup/proposal pass before implementation.
> Pure refactors, error-text fixes, and internal robustness do not.

---

## 1. Security & silent data loss (do first)

- [x] **1.1 Token swap serves the previous user's cached financial data.**
  `ensure_synced` calls `state.is_healthy(cur_state,
  expected_user_id=cur_state.user_id, ...)` (`expense/cache/sync.py:231-233`)
  — comparing the cache's stored user id **to itself**, a tautology; the
  token-swap wipe documented in `expense/cache/state.py:6` can never fire.
  And `config set --token` (`config_cmd.py:39-44`) preserves `client_id` and
  never wipes the cache (nothing outside `expense/cache/` calls `wipe()`,
  despite `db.py:189` claiming "used by config changes"). Result: install
  user B's PAT and pure reads keep serving user A's accounts/transactions/
  balances from the replica until the next write or explicit sync. Fix: wipe
  the cache on `config set --token` (and `config clear`), or verify the
  authenticated user id against the engine on the read path so
  `expected_user_id` is real. Add a regression test for the swap scenario.

- [x] **1.2 TUI hashtag edits are silently dropped.**
  `QuickAddLogScreen` snapshots the form with a shallow copy
  (`quick_log.py:153` — `self._original = dict(self._values)`), so
  `_original["hashtags"]` aliases the live list that `_commit_hashtag`
  (`quick_log.py:399`) appends to in place; the edit-payload diff
  (`quick_log.py:480`) therefore always sees hashtags as unchanged and omits
  `hashtag_ids` from the PUT. The screen toasts "Saved." but the change never
  reaches the engine. Fix: deep-copy (or copy the list explicitly); pilot
  test that edits hashtags on a record that already has one and asserts
  `hashtag_ids` is in the PUT body.

- [x] **1.3 Import re-run silently drops appended rows.**
  The engine batch endpoint is atomic and 409s if *any* client-supplied id
  pre-exists; `apply_plan` counts a 409'd chunk entirely as
  `tx_skipped_existing` (`expense/import_/apply.py:166-167`). The natural
  workflow — append rows to the sheet, re-run `--apply` — puts old + new ids
  in one chunk, 409s, and the new rows are never imported while the summary
  reports success (exit 0). The `import_cmd.py:117-119` "re-running --apply
  is safe" claim only holds for byte-identical sheets. Related fragility:
  `stable_row_key` embeds `row.line` (`plan.py:33-43`), so inserting/deleting
  a mid-sheet row shifts every subsequent id — re-runs then duplicate shifted
  rows *and* can trip 1.3's boundary case. Fix: on chunk 409, fall back to
  per-row (or bisected) posts so pre-existing and new rows are separated;
  document the line-number dedup contract in `import --help`.

- [x] **1.4 Cached `--include-deleted` is wrong for every resource; silently
  no-ops for transactions.**
  Sync purges tombstoned rows from the replica (`sync.py:132-135`), so cached
  `--include-deleted` returns fewer rows than `--no-cache` everywhere and the
  §7 Deleted column is always empty on cached reads; `cache.list_transactions`
  has no `include_deleted` parameter at all, so `transactions_cmd.py:180-182`
  drops the flag without a word (a known quirk — preserved verbatim in the
  old §5.3 — but never disclosed to the user). Decide one: (a) store
  tombstones in the replica, (b) route `--include-deleted` to the live path
  automatically, or (c) warn loudly that the flag forces/needs `--no-cache`.
  Whatever the pick, cache and live must stop returning different data for
  the same command.

- [x] **1.5 TUI inbox filter is dead code.**
  `action_cycle_filter` calls the *async* `action_reload()` without awaiting
  it (`inbox.py:132`; `action_reload` is `async def` at `_base.py:111`), so
  the coroutine is created and discarded — pressing `f` mutates the filter
  but never reloads (plus a "never awaited" RuntimeWarning). No test covers
  it (existing tests only exercise `r` via key press, which the dispatcher
  awaits). Fix: `run_worker`/await properly; add a pilot test that presses
  `f` and asserts the row set changed.

- [x] **1.6 The Step-9 live contract test cannot run at all.**
  `CliRunner(mix_stderr=False)` raises `TypeError` under installed
  click 8.3.2 (`tests/contract/test_freshman_flow.py:44`; the kwarg was
  removed upstream — `_assert_ok`'s `result.stderr` access needs the same
  update). Gated behind `PYTEST_LIVE=1`, so CI stays green while the
  flagship gate test rots. Root cause is unpinned deps (see 4.4) — this is
  the concrete bite. Fix the runner call, then run the live gate once to
  confirm it still passes end to end.

## 2. Convention drift — engine-owned logic re-implemented client-side

The same pattern §7 deliberately retired from `reports monthly` survives in
five spots. Thin-wrapper rule: surface the engine's 422, don't pre-empt it.

- [x] **2.1 [UI-adjacent] Transfer form silently flips the sign the user
  typed.** Resolved (user decision, mockup
  `expense-world-transfer-to-amount-2.1.html`, variant A): the flip **stays**
  — the To-amount field takes a magnitude and the sign is always the
  opposite of Amount — but the field hint now states the rule explicitly
  and the summary keeps showing the computed signed value before submit.
  Recorded as a sanctioned exception in cli-spec.md (2.6) and pinned with a
  comment + tests in both directions.

- [x] **2.2 `transactions batch` re-validates "no transfers in batch"**
  (`transactions_cmd.py:444-451`) — engine-spec.md:476 already rejects the
  whole batch. Convert to an except-hint on the engine's 422 like every
  other command (same treatment §7 gave reports).

- [x] **2.3 Cache inbox `_READY_PREDICATE` re-implements the engine's
  readiness rule with a date/timestamp divergence.** (Correction on
  verification: the engine does **not** use the profile timezone — its rule
  is a plain UTC timestamp comparison, `i.date <= now()` for ready and
  `< now()` for overdue, per engine `app/routers/inbox.py`. The real
  divergence was the cache's `date('now')` **calendar-date truncation**,
  which marked an item dated later today as ready/not-overdue when the
  engine disagreed, plus the cache ignoring `overdue` whenever `ready` was
  set — the engine combines them.) Fixed: `list_inbox` mirrors the engine's
  conditions with `now` parameterized (frozen in tests); longer term,
  consider the engine exposing readiness in the sync payload so the client
  stops owning the rule.

- [x] **2.4 USD/PEN whitelist is hard-coded in three client spots**
  (`create_forms.py:30`, `system.py:194-195`, `import_/mapping.py:32`).
  Adding a currency engine-side means hunting client constants. Single-source
  it (one module constant referenced by all three), and note the schema-lock
  provenance where it's defined.

- [x] **2.5 Sweep the remaining TUI pre-validations of engine rules** —
  resolved case by case (user decision): the three reconciliation action
  guards (complete-needs-≥1 / revert-only-completed / delete-draft-only)
  were **removed** — the engine's 422/409 messages surface via `run_write`
  toasts, and revert-on-draft rides the engine's idempotent 200 no-op
  (pinned by tests). The two quick_log mid-form guards (non-zero amount,
  transfer dest ≠ source) were **kept** as form-flow ergonomics, each with
  a comment pinning it to the engine rule it mirrors.
  *Engine-spec gap noted:* the same-account transfer rejection
  (engine `app/helpers/transfers.py`, 422 `transfer.account_id` "Must be a
  different account.") is enforced but undocumented in engine-spec.md — to
  be added in the engine repo.

- [x] **2.6 Document the two sanctioned exceptions** so future reviews stop
  re-flagging them: `accounts update --currency-code` exists solely to be
  rejected client-side with honest help text (deliberate UX,
  `accounts_cmd.py:216-233`); `import --json` emits a client-composed
  plan/result summary — the only non-verbatim `--json` in the layer,
  unavoidable for a composite pipeline (`import_cmd.py:31-41,68-85`). Add a
  short "sanctioned exceptions" note in cli-spec.md.

## 3. Robustness & error handling

- [x] **3.1 Idempotency key protects nothing today.**
  Resolved as implementation (user-approved plan): `_request` retries a
  timed-out/5xx write up to twice with the same key (1s/2s backoff, stderr
  notice); connect failures and reads still fail fast. Docs updated
  (cli-runtime.md Write semantics, cli-spec.md, CLAUDE.md).
  `http.py:81-82` mints a fresh UUID per request and no code path ever
  re-sends the same key (no transport retries, no retry loop) — so a re-run
  after a timeout double-applies, the exact failure CLAUDE.md says the key
  prevents. Decide: add a bounded same-key retry on timeout/5xx inside
  `_request` for writes (engine replay makes this safe), or amend CLAUDE.md
  to state the key is engine-side infrastructure awaiting client retry
  support. Implementation-or-docs, but the current letter-vs-spirit gap
  should close.

- [x] **3.2 TUI worker-group collisions.**
  `run_write` and `_load` are both `exclusive=True` in the *default* group
  on the same node (`_base.py:39`, `_base.py:117`), so a refresh or theme
  change mid-write cancels the write worker and vice versa —
  `reconciliations.py:590-591` documents and fixes exactly this, but only
  for the detail screen. Give writes and loads separate worker groups in the
  base. Related: rapid `space` toggles fire overlapping PUTs
  (`reconciliations.py:683-694`) — thread cancellation is cooperative and
  `run_write` never checks `is_cancelled`, so two requests race with no
  ordering guarantee and only *errors* resync. Serialize per-row toggles or
  disable the row while a toggle is in flight.

- [x] **3.3 Reconciliation detail fetches with `limit=500`** — above the
  engine's hard cap of 200 (`reconciliations.py:621,634`): 422s outright in
  `--no-cache` mode, and even cached it's a silent truncation ceiling for
  the checklist. Paginate (loop with the 200 cap) or use the cache-side
  query without a live-path limit violation.

- [x] **3.4 Catch the full httpx transport family.**
  `http.py:98` catches only `(ConnectError, TimeoutException)`;
  `ReadError`, `WriteError`, `RemoteProtocolError` (server closes
  mid-response — plausible on a cold-starting Render dyno), `ProxyError`,
  and `UnsupportedProtocol` (scheme-less `engine_url` — `config set` never
  validates it) all escape as raw tracebacks. Catch `httpx.TransportError`;
  validate the URL scheme at `config set` time.

- [x] **3.5 Refine the corruption-wipe guard (old §1.5) to not wipe on
  transient lock.** `db.py:36-39` treats every `sqlite3.DatabaseError` as
  corruption, but `OperationalError` ("database is locked" past the 5s busy
  timeout — concurrent TUI + CLI) is a subclass; a lock destroys a healthy
  replica, and `wipe()` unlinking files under a live connection in the other
  process risks split-brain. Exclude `OperationalError` from the wipe path
  (retry/fail cleanly instead).

- [x] **3.6 Two uncaught-traceback paths in commands.**
  `_detect_timezone()` raises bare `RuntimeError` (`auth_cmd.py:39`, reached
  from `bootstrap:126`) which `handle_errors` doesn't catch; `config set`
  lacks `@handle_errors` entirely yet calls `config_module.load()`
  (`config_cmd.py:13-14`), so a corrupted config file tracebacks on `set`
  but renders cleanly on `get`. Fix both; unit tests alongside.

- [x] **3.7 Fail loudly on a missing sync token.**
  `response.get("sync_token") or ""` (`sync.py:176`) silently stores an
  empty token; the next delta then runs `sync_token or "*"` (`sync.py:300`)
  — a full fetch applied *as a delta without wiping*, stranding rows deleted
  server-side. A broken engine contract should error, not degrade.

- [x] **3.8 `cold_start` wipes before fetching** (`sync.py:189-191`) — a
  network failure mid-cold-start leaves *no* cache instead of the stale one.
  Fetch first, wipe + apply only on success.

- [x] **3.9 Import chunk failures are unactionable.**
  One engine 422 fails all 200 rows in its chunk and `failures` records only
  `(chunk_index, message)` (`apply.py:161-170`) — no sheet line numbers, no
  bisect. Report the sheet line range per failed chunk at minimum; per-row
  fallback (see 1.3) would solve both.

## 4. CI, packaging, tooling

- [x] **4.1 Test the supported Python range.** CI runs only 3.12
  (`ci.yml:16`) while packaging promises `>=3.11` (`pyproject.toml:10`);
  matrix 3.11/3.12/3.13. Done: matrix with `fail-fast: false`; 3.14 is a
  later add.
- [x] **4.2 Add type checking** (mypy or pyright) to CI + pre-commit —
  ruff `E/F/W/I/B/UP` alone can't catch payload-shape mistakes in a codebase
  that passes engine JSON dicts everywhere. Start permissive on
  `expense/http.py`/`config.py`/`errors.py`/`cache/` and ratchet. While at
  it: `get() -> dict` in `http.py:44` is wrong for list-shaped endpoints
  (returns `list` at runtime; runtime-safe via the isinstance guard, but the
  hint misdocuments the contract). Resolved: scoped permissive `[tool.mypy]`
  on exactly those modules, run in CI and as a local pre-commit hook (dev
  venv's mypy, so it sees real deps); `get()`/`_request` now return `Any`
  (verbatim engine JSON, contract in the docstring) and `apply_response`'s
  `kind` carries the `SyncSummary` Literal — mypy clean; ratchet from here.
- [x] **4.3 Make coverage visible and reproducible.** CI runs plain
  `pytest tests/unit` with no coverage; `pytest-cov` isn't in the `dev`
  extra even though it's used locally (a `.coverage` file exists). Add
  `pytest-cov` to dev, report coverage in CI (gate optional). Done:
  `pytest-cov` in dev, `[tool.coverage.run] source` so bare `--cov` matches
  everywhere, CI reports `term-missing` — report only, no gate (92% at
  landing).
- [x] **4.4 Pin dependencies.** All deps are unpinned lower bounds with no
  lockfile/constraints; CI floats on latest — 1.6 is the concrete bite
  (click 8.2 removed `mix_stderr` unnoticed). Add a constraints file or
  upper bounds for the direct deps CI installs. Resolved: `constraints.txt`
  (not upper bounds) pins every direct dep at dev-venv-proven versions; CI
  installs with `-c constraints.txt`; pyproject ranges stay open. Refresh =
  bump a pin, merge on green CI.
- [x] **4.5 Local secret scanning.** CLAUDE.md's public-repo doctrine relies
  on discipline + GitHub push protection (post-commit). Add
  gitleaks/detect-secrets to `.pre-commit-config.yaml`. Done: gitleaks hook
  (v8.30.1); full-tree scan at install time came back clean.
- [x] **4.6 Add a LICENSE** (and `license` field in pyproject) — the repo is
  deliberately public but legally "all rights reserved" by default; if
  that's intended, state it. Resolved (user decision): it's intended —
  explicit all-rights-reserved LICENSE (source visible for reading, no
  rights granted); `license = "LicenseRef-Proprietary"` + `license-files`
  in pyproject (PEP 639, setuptools>=77).

## 5. Low-severity nits (batch opportunistically)

- [ ] Connection errors exit with code 2 (`errors.py:85-86`), colliding with
  Click's usage-error 2 — scripts can't tell "bad flags" from "engine
  unreachable"; move to an unused code.
- [ ] Cached `--search` doesn't escape `%`/`_` in `LIKE`
  (`queries.py:317-322`) — `--search "100%"` wildcards on the replica;
  verify engine semantics and match them.
- [ ] `reconcile move --json` on the "No changes." early-return prints
  nothing at all (`reconcile_cmd.py:778-781`) — emit a JSON document.
- [ ] Reports: `_render_range_table` hand-rolls the width/format loop the
  shared `render_table` covers (`reports_cmd.py:131-186`). (The other half
  of this item — the fetch/render split — shipped 2026-07-08 with the
  Monthly-report TUI screen: `fetch_single_month`/`fetch_range`/
  `build_range_grid`.)
- [ ] `reconcile complete` inlines the hint-haystack scan that
  `transactions_cmd.py:104-117` wraps in `_update_hint_for`
  (`reconcile_cmd.py:571-583`) — hoist to `_resource.py`.
- [ ] `_render_resource_counts`'s `label` param is dead at both call sites
  (`sync_cmd.py:19-29`).
- [ ] `_validate_source_choice` hand-rolls what an `Enum`-typed Typer option
  gives free (choices in `--help` + completion) (`reconcile_cmd.py:245-253`).
- [ ] **[UI]** Inbox and transactions lists accept `--include-deleted` but
  render no Deleted column (accounts/categories/hashtags/reconcile all have
  one) — needs a proposed-columns mockup first per the table rule; rides on
  the 1.4 decision.
- [ ] TUI: theme change triggers a full re-*fetch* on every subscribed screen
  when only a re-render is needed (`_base.py:108`); detail screen mutates
  `self._record` from the worker thread (`reconciliations.py:617`) —
  inconsistent with the `call_from_thread` discipline used elsewhere;
  `run_write` discards `refresh_after_write`'s stale-replica warning into a
  throwaway `StringIO` (`_base.py:74`) — surface it as a notify; System
  screens render replica corruption as "not synced yet" via bare
  `except Exception` (`system.py:68-69,306-307`) — add a verbose breadcrumb;
  (~~promote `auth_cmd._detect_timezone`~~ — done 2026-07-08 with 6.2d, it
  lives in `expense/dates.py` now); `Row = tuple` and bare `-> list` typing across widget plumbing
  (`cursor_list.py:23`, `checklist.py:25`) — a `NamedTuple`/`TypeAlias` for
  the `(id, cells[, style])` contract; HomeScreen's 13-branch `elif` chain
  with `f"{opt_id}:{label}"` round-tripping (`home.py:70-100`) — a dispatch
  dict; five screen docstrings still say "read-only … Phase 1" on screens
  with writes (`accounts.py`, `categories.py`, `hashtags.py`, `inbox.py`,
  `transactions.py` headers).
- [ ] Import: reader materializes all rows despite the streaming workbook
  (`reader.py:61`); text-formatted date cells skip as `bad-date` though
  `expense/dates.py` parses them (`parse.py:76-85`); exchange rate goes
  through `float` while amounts correctly use `Decimal` (`parse.py:97-104`);
  `resolve_or_create` aborts wholesale on the first failing POST
  (`apply.py:66-127`).
- [ ] Cache file perms: created umask-default then chmod'd, `_set_perms`
  swallows `OSError`, never re-checked (`db.py:20-25,46-49`) — re-assert 600
  on connect; `refresh_after_write`'s bare `except Exception`
  (`sync.py:271-277`) converts programming errors into the one-line sync
  hint — narrow it or log the class; `_apply_resource` loads every table id
  into a set per sync for insert/update counts (`sync.py:122`) — fine at
  personal scale, note as a non-goal or use `ON CONFLICT`.
- [ ] Tests: default-date test computes "today" after the CLI runs
  (`test_cmd_log.py:114`, midnight-straddle flake); two fixed
  `pilot.pause(0.05)` waits where `wait_for` is the file's own idiom
  (`test_tui_writes.py:32`, `test_tui_section_errors.py:88`); no network-off
  backstop for unit tests (pytest-socket or a global
  `respx.mock(assert_all_mocked=True)`).

## 6. Multi-agent review 2026-07-07 (since merged to `main`)

Source: 8-angle parallel review (line-by-line, removed-behavior, cross-file,
reuse, simplification, efficiency, altitude, conventions) over the review's
change set (since merged to `main` — the repo is single-branch). Items 6.1/6.2 were **spot-verified by reading the
cited code**; the rest were surfaced by the review and should be reconfirmed
at their line when picked up (same rule as the sections above). Findings that
merely duplicate an existing section-5 nit were dropped; **upgrades** to an
existing item are marked.

### 6.1 Crashes (verified)

- [x] **`cache/db.py:213` — `wipe()` crashes for an extensionless
  `EXPENSE_CACHE`.** `path.with_suffix(path.suffix + "-wal")` raises
  `ValueError: Invalid suffix '-wal'` when the cache path has no dot (a
  documented env override, e.g. `EXPENSE_CACHE=/home/u/expense-cache`).
  `wipe()` runs on every cold-start and on `config set --token`, so the first
  cached read or a token change dumps a raw traceback. Default path
  (`.sqlite3`) is unaffected, which is why tests miss it. Fix:
  `path.parent / (path.name + "-wal")`.

- [x] **`cache/sync.py:104,191` — bare `RuntimeError` escapes `handle_errors`
  as a raw traceback.** `_derive_user_id` (settings null + every resource
  empty) and `_fetch` (engine omits `sync_token`) raise `RuntimeError`, which
  `errors.handle_errors` does not catch (it catches only the five domain
  errors). Reachable: a fresh user installs a PAT and runs `expense accounts
  list` **before** `auth bootstrap` → cold-start derives no user_id → full
  traceback instead of a "run auth bootstrap" hint. The TUI path is fine (it
  wraps in `except Exception`). Fix: raise a domain error (or a new
  `SyncContractError` that `handle_errors` renders).

### 6.2 TUI correctness (verified / high-confidence)

- [x] **`tui/screens/reconciliations.py:682` — detail `_populate` does the
  unserialized `#rlist` swap that `SectionScreen._swap_lock` (just added in
  `0fc1513`) exists to prevent.** `_load_txns` never checks `is_cancelled`
  (cooperative cancellation), so pressing `r` while a toggle-failure resync is
  finishing lets two `_populate` coroutines interleave their
  remove/mount and stack two `CheckList`s with duplicate rows; toggles then
  fire against the stale one. Fix: reuse the same lock/cancellation discipline
  on the detail screen.

- [x] **`tui/screens/reconciliations.py:633` + list `fetch` (~:142) — refresh
  searches only page 1, falsely reports a batch deleted.**
  `_load_txns(refresh_record=True)` scans `items_of(fetch_reconciliations(cfg,
  **kw))` with no `limit/offset`, so a reconciliation past the cache's default
  100-row page is `None` → `_record_gone()` dismisses the open screen with
  "no longer exists"; the list screen truncates the same way, so
  `ctrl+up/down` reorder acts on wrong neighbors. Fix: fetch the single record
  by id (the `reconcile get` / `cache.get_reconciliation` path already
  exists) instead of scanning the collection.

- [x] **`tui/screens/reconciliations.py:217` — `on_cursor_list_highlighted`
  guards on `_mode` but not on the event's source list.** While `_mode ==
  "accts"`, a `Highlighted` from the *batches* pane (reachable by Tab/click
  focus without a select) is written to `self._acct_idx`, silently switching
  the selected account; a following `n` then creates the new batch under the
  wrong account. Fix: ignore events whose `event.control` isn't the accounts
  list.

- [x] **`tui/screens/system.py:224` — TUI Bootstrap crashes when timezone
  detection fails** (*upgrades the §5 "promote `_detect_timezone`" nit from
  cleanup to crash*). `_bootstrap` calls `auth_cmd._detect_timezone()` on the
  UI thread with no guard; it raises `typer.BadParameter` (whose text even
  says "Pass --timezone explicitly", a flag the TUI lacks) on systems where
  `/etc/localtime` isn't a zoneinfo symlink (some containers/WSL) → unhandled
  exception through Textual's message pump crashes the app. Promoting the
  helper to raise a neutral error the TUI can catch fixes both.

- [x] **`tui/screens/quick_log.py` name-resolution — `None[:8]` on a missing
  reference id.** The inline `names.get(id, id[:8])` copies (quick_log
  `_resolve`/`_tag_display_names`, `reconciliations.py:69,585`) raise
  `TypeError` on a null `account_id`/`category_id` where the shared
  `_resource.resolve_name` returns an em-dash. Fix folds into 6.4's
  resolve_name consolidation.

### 6.3 Convention / error surfacing

- [ ] **`import_/apply.py:192,234` — import error summary drops the engine
  envelope's `fields`.** Failure lines hand-roll `f"{err.code}: {err.message}"`
  instead of the shared `format_error` (already imported for connection errors
  in this file), so a 422 from `transactions batch` loses the per-row field
  detail — violates CLAUDE.md "Engine errors surface cleanly … never reformat
  lossily" (the sanctioned `import --json` exception covers the summary shape,
  not lossy human errors). Fix: render failures through `format_error`.

- [ ] **`tui/screens/system.py:112` — TUI ConfigScreen skips the engine-URL
  validation the CLI got in backlog 3.4.** `_save` writes `engine_url`
  straight through `config.save()`, so a scheme-less/malformed URL entered via
  the TUI saves "Config saved." then fails every later call with a generic
  connection error — the exact late-failure 3.4 removed for `config set`. Fix:
  hoist `_validate_engine_url` into `expense/config.py` so both entry points
  inherit it.

### 6.4 Reuse & altitude (maintenance risk, not live bugs)

- [x] **Three hand-rolled "fetch every page" loops with three different
  termination rules** — `import_/apply.py:51` (`_list_all`, stops on
  `total is None`), `tui/screens/reconciliations.py:500` (`_fetch_all_txns`,
  stops on short page), `commands/reconcile_cmd.py:~632` (chain, total-vs-len)
  — each hard-codes the engine's 200 cap in its own constant. This is the
  class behind backlog 3.3; the next cap/off-by-one fix must land in all three
  or one surface silently truncates. Hoist one `fetch_all_pages` helper into
  `_resource.py`.

- [x] **`run_write` (`_base.py`) doesn't actually serialize writes despite the
  exclusivity its docstring implies.** Thread-worker cancellation is
  cooperative and `run_write` never checks `is_cancelled`, so rapid repeated
  writes on any screen (e.g. double-pressing archive) fire overlapping,
  unordered PUTs — the general form of the checklist-toggle race fixed
  screen-locally in 3.2. Centralize serialization in the mixin.

- [x] **Duplicated inline id→name resolution and account-picker builders.**
  Four copies of `names.get(id, id[:8])` (see 6.2) and three copies of the
  `(id, name-or-'(unnamed)', currency)` account-choices build
  (`quick_log._load_entities`, `reconciliations._load_accounts`,
  `ReconciliationsScreen.fetch`) that already filter people differently —
  route through `_resource.resolve_name` and one shared account-choices helper.

- [ ] **Duplicated row/branch builders**: `batch_rows` vs `reconciliation_rows`
  (same file, differ only by the leading Account cell); `AccountsScreen` /
  `CategoriesScreen` / `HashtagsScreen` are the same ~80-line screen pasted
  three times; `errors.render` is four near-identical branches (two added
  recently) that a `{ExcType: (code, exit)}` table would collapse;
  `import_/apply.py:72 resolve_or_create` is three near-identical
  resolve-or-POST blocks; the 10-site quiet-fetch kwarg incantation
  (`cold_start_notice=False, notice_stream=StringIO()`) wants a
  `SectionScreen` helper. All one edit from silent drift.

- [ ] **`import_/plan.py:67` — unreachable duplicate-row skip branch.**
  `tx_id_for` hashes `stable_row_key`, which embeds the unique `row.line`, so
  `tid in seen_ids` can never be true; the branch is dead and advertises a
  content-dedup that doesn't exist (the misunderstanding behind 1.3). Delete
  it or make the key content-based if dedup is actually wanted.

### 6.5 Efficiency (personal-scale, note or fix opportunistically)

- [x] **Checklist toggle fires a full delta sync per toggle**
  (`reconciliations.py` `_pump_toggles` → `run_write` → `refresh_after_write`).
  Reconciling a statement (15–30 toggles) becomes 2 engine round-trips each
  against Render. Add a skip-refresh flag for queued toggles and run one delta
  sync when the queue drains.

- [x] **`quick_log._load_entities` reads each table twice** — `fetch_*` for the
  suggestion pools then `load_*_name_map()` again — six list queries per form
  open where three (with `include_archived`) would feed both.

- [x] **Name maps loaded on the UI thread** in `reconciliations._render_header`
  and `outstanding.build` (`load_*_name_map()` = a full-table SQLite read on
  the render path) — blocks first paint and can stall on the cache busy-timeout
  if a concurrent `expense sync` holds the lock. Resolve names worker-side like
  `transactions.py` does.

## Suggested sequencing

0. **Section 6 crashes first** — 6.1 (both are one-line fixes with an obvious
   regression test) then 6.2 reconciliation-detail race/paging before any more
   reconcile TUI work.
1. **Section 1** — the security hole and the four silent-data-loss bugs;
   each is small and independently shippable with a regression test.
2. **1.6 + 4.4 together** — fix the contract test and pin deps in one pass
   so the same class of rot can't recur; run the live gate once after.
3. **Section 3** — robustness items; 3.2 (worker groups) before any further
   TUI write features.
4. **Section 2** — drift removals; 2.1 needs a behavior decision (and is
   user-visible), the rest are mechanical.
5. **Section 4 rest** (CI matrix, typing, coverage, secrets, license).
6. **Section 5** — batch opportunistically; the two **[UI]** items ride the
   mockup rule.
