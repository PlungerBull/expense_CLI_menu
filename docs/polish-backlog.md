# Polish backlog — quality review 2026-07-02

Source: multi-agent review (6 dimensions, every medium/high finding adversarially
verified; 29 confirmed, 0 refuted). Scope rule: **polish only — no new features.**
Full finding detail lives in the review transcript; this file is the working list.

Baseline at review time: 605 unit tests passing / 41 skipped (~8s), 88% line
coverage, ruff clean, no orphans from the deleted `expense/menu`.

> **Mockup rule reminder:** items marked **[UI]** change something the user sees
> in the TUI — per CLAUDE.md they need a mockup/proposal pass before implementation.
> Pure refactors, error-text fixes, and help-text corrections do not.

---

## 1. Correctness & convention violations (do first)

- [x] **1.1 Unify the sign convention across cache modes.**
  Cached reads show expenses negative (replica populated with
  `debit_as_negative=true` hardcoded, `expense/cache/sync.py:183`); stateless
  reads only send the param when `--debit-as-negative` is passed
  (`expense/commands/transactions_cmd.py:149,186-187`), so
  `transactions list` and `transactions list --no-cache` disagree on sign for
  the same expense. Same split in inbox (`inbox_cmd.py:103,128-129,191-196`);
  `reconcile get --no-cache` never sends it. Fix: send
  `debit_as_negative=true` unconditionally on stateless reads (matching what
  sync.py already stores) so both paths agree.

- [ ] **1.2 Archive commands must confirm (CLAUDE.md non-negotiable).**
  `accounts archive` (`accounts_cmd.py:306-324`), `categories archive`
  (`categories_cmd.py:287-295`), `hashtags archive` (`hashtags_cmd.py:265-273`)
  have no `--yes` and no prompt; the TUI confirms the same action. Fix: add
  `--yes/-y` + `require_yes(...)` before `run_toggle`. Unarchive stays
  prompt-free.

- [ ] **1.3 Guard the three unguarded TUI fetch workers (app-crash bug).**
  Textual `@work` defaults to `exit_on_error=True`, so an engine/config error
  inside `NewReconciliationScreen._load_accounts`
  (`reconciliations.py:398-416`), `ReconciliationDetailScreen._load_txns`
  (`reconciliations.py:721-771`), or `QuickAddLogScreen._load_entities`
  (`quick_log.py:222-249`) exits the whole app (verified live). Fix: same
  try/except → `call_from_thread(error banner/notify)` pattern
  `SectionScreen._load` already uses (`_base.py:54-58`).

- [ ] **1.4 Corrupt `~/.expense-config` → clean error, not traceback.**
  `config.load()` raises bare `ValueError` on bad JSON and lets pydantic
  `ValidationError` escape (`expense/config.py:29-33`); `handle_errors`
  re-raises both (verified live: full Rich traceback). Fix: raise
  `ConfigMissingError` or a sibling `ConfigInvalidError` rendered the same
  way, with the existing `expense config set ...` recovery hint. Add unit test.

- [ ] **1.5 Corrupt SQLite cache → wipe and rebuild, not crash.**
  `db.connect()` has no corruption guard; a garbage cache file raises
  `sqlite3.DatabaseError` at the WAL pragma (`expense/cache/db.py:28-41`,
  verified live). The module's own contract is wipe + cold-start and `wipe()`
  exists (`db.py:171`). Fix: catch `sqlite3.DatabaseError` in `connect()`,
  wipe, retry once. Add unit test in `test_cache.py`.

- [ ] **1.6 `transactions batch` human output dumps a Python repr.**
  After the `Created: <id>` lines, the batch envelope `{"created": [...]}` is
  passed to `_render_transaction`, printing a single-quoted repr of the whole
  array (`transactions_cmd.py:471-476`, verified by reproduction). Fix: render
  a count summary (and/or per-item key/value dumps); assert the repr never
  appears in output.

- [ ] **1.7 Auth writes skip the post-write replica refresh.**
  `auth settings` / `auth profile` / `auth bootstrap`
  (`auth_cmd.py:281-287,209-210,131-132`) never call `cache_after_write`,
  unlike every other write. A `--main-currency` change rewrites
  `amount_home_cents` server-side, leaving the replica stale. The TUI
  equivalents already refresh. Fix: call `cache_after_write` in all three.

## 2. Error-handling consistency

- [ ] **2.1 Route TUI errors through the canonical renderer.**
  All 13 TUI error sites notify `str(exc)`, dropping the engine error `code`,
  per-field 422 hints, and the "could not reach engine at {url}" guidance that
  flat commands render (`_base.py:56-57,142-143`, `system.py:126,247,272,407,624`,
  `create_forms.py:237`, `quick_log.py:610`,
  `reconciliations.py:303,628,808,887`). Fix: add `format_error(exc) -> str`
  in `expense/errors.py` sharing `render()`'s human branch; use it at all 13
  sites. Same banners/toasts, richer text.

- [ ] **2.2 Importer: survive mid-run connection failure.**
  `apply_plan`'s chunk loop catches only `EngineError`
  (`expense/import_/apply.py:161-171`); an `EngineConnectionError` mid-run
  aborts before `_render_result`, so committed chunks go unreported and
  `cache_after_write` is skipped. Fix: catch `EngineConnectionError` in the
  loop, mark remaining chunks failed, break, still render the summary and
  exit non-zero.

- [ ] **2.3 One destructive-confirm implementation, one exit code.**
  `require_yes` (`_resource.py:216-232`, exits 1) is re-implemented inline in
  `auth settings` (`auth_cmd.py:267-279`, exits 1) and `config clear`
  (`config_cmd.py:103-109`, exits **3** — colliding with CONFIG_MISSING).
  Fix: both call `require_yes`; missing-confirmation exits 1 everywhere.

## 3. Help text & CLI output polish (highest polish-per-effort)

- [ ] **3.1 Fix the four broken docstring examples.**
  `reconcile list/create/reorder` examples say `--account` but the flag is
  `--account-id` (`reconcile_cmd.py:224,314,817-818`); `auth settings` example
  uses `--theme dark --start-of-week monday` on int-typed options
  (`auth_cmd.py:244`) — fails Typer parsing if copy-pasted. Consider a small
  test that extracts `Example:` lines and asserts each flag exists.

- [ ] **3.2 Fix the `--resource-type` guidance.**
  Help, docstring example, and the `transactions get` cross-reference all
  recommend `expense_transactions` (`activity_cmd.py:206,222`,
  `transactions_cmd.py:270-272`) but the engine writes singular
  (`transaction`) — following the help returns a silently empty list. Keep the
  plural aliases in `_RESOURCE_KIND` for display robustness only.

- [ ] **3.3 Strip internal roadmap leakage from user-facing text.**
  "once Step 8 ships" for a shipped feature (`transactions_cmd.py:270-272`),
  "(Step 6: …)" (`transactions_cmd.py:38-39`), "(Step 4)"
  (`inbox_cmd.py:357-358`). Keep just the concrete command suggestions.

- [ ] **3.4 Consistent option help text via shared option constants.**
  Many flags render bare in `--help` (`transactions_cmd.py:219-227` documents
  4 of 10 options; `accounts_cmd.py:122-125` documents none) and `--json` has
  six different wordings. Fix: hoist `JSON_OPT` / `LIMIT_OPT` / `OFFSET_OPT` /
  `INCLUDE_DELETED_OPT` etc. into `_resource.py` with one wording; reuse
  everywhere (bespoke semantics like `reconcile reorder --json` stay bespoke).

## 4. TUI polish — **[UI] items need mockup review first**

- [ ] **4.1 [UI] Resolve the `r` keybinding collision.**
  `r` = Refresh on every SectionScreen (`_base.py:28`) but Revert (a write!)
  on `ReconciliationDetailScreen` (`reconciliations.py:664-669`), which has no
  refresh key at all — and `ConfirmModal` accepts plain `enter`
  (`modals.py:90`), so refresh muscle-memory can revert a batch. Also audit:
  `d` Delete vs Date, `b` Bootstrap vs Base currency, `t` Token vs Target
  (`system.py`). One meaning per key per verb class.

- [ ] **4.2 [UI] Theme-resolve hardcoded colors; settle amount-coloring rule.**
  `"green"/"red"` by sign and `"green"/"dim"` in
  `widgets/checklist.py:91-97`, `"green"/"yellow"` status in
  `reconciliations.py:711` bypass `theme.py`'s documented palette. The
  reconciliation checklist is also the only place amounts are sign-colored —
  pick one rule (everywhere or nowhere) across Transactions/Inbox/Accounts/
  Outstanding.

- [ ] **4.3 [UI] Remove or wire the fake "● connected" home-screen status.**
  Hardcoded string that reflects nothing (`home.py:56`).

- [ ] **4.4 [UI] `#field` label column (width: 11) clips longer form labels**
  like "TRANSFER TO?" / "BEGIN BALANCE" (`app.tcss:59-65`).

- [ ] **4.5 Drop redundant re-declared escape/r bindings on System screens**
  (`system.py:50-55,135-140,305-310`) — inherited already; pure cleanup.

## 5. Deduplication refactors (pure, no behavior change)

- [ ] **5.1 Extend `run_write` and collapse the 9 copied write workers.**
  `_base.py:115-145` only supports body-less POST/DELETE, so the identical
  `ensure_loaded → ExpenseClient → write → refresh_after_write → except →
  notify` block is copy-pasted in `system.py:221-250,252-275`,
  `quick_log.py:589-612`, `create_forms.py:219-239`,
  `reconciliations.py:282-307,610-630,790-808,863-889` (~170 lines; copies
  already drifted — `_assign` and `quick_log.py:222` miss `exclusive=True`).
  Fix: accept `json_body`, PUT, and on_success/on_error callbacks; delegate
  all sites. At minimum align the `exclusive=True` drift immediately.

- [ ] **5.2 Unify the three bar-cycle form implementations.**
  `BarFormScreen` (`create_forms.py:48-248`) is the extracted abstraction, but
  `NewReconciliationScreen` (`reconciliations.py:343-639`) and
  `QuickAddLogScreen` (`quick_log.py:102-624`) re-implement it — `compose()`,
  `action_suggest`, `_failed`, summary rendering are verbatim/near-verbatim
  triplicates. Fix: subclass or extract one nav/suggest/summary/submit core;
  quick-log's dynamic field sequence stays a subclass hook.

- [ ] **5.3 `fetch_list` / `fetch_one` helpers for the cache-vs-live branch.**
  Six `fetch_*` functions and six `get` commands repeat the same
  `no_cache → ExpenseClient.get` / else `ensure_synced` + cache-query skeleton
  (`accounts_cmd.py:81-115,161-173`, `categories_cmd.py:72-108,153-165`,
  `hashtags_cmd.py:66-102,147-159`, `inbox_cmd.py:95-137`,
  `transactions_cmd.py:135-204`, `reconcile_cmd.py:29-67`). Hoist into
  `_resource.py`; each command keeps only its params/cache-query mapping.

- [ ] **5.4 One `render_record(body, *, json_mode, skip=())` in `_resource.py`.**
  The 6-line key/value renderer is copied 7× (`accounts_cmd.py:29-34`,
  `categories_cmd.py:29-34`, `hashtags_cmd.py:26-31`, `inbox_cmd.py:35-40`,
  `transactions_cmd.py:49-54`, `log_cmd.py:14-19`,
  `reconcile_cmd.py:107-114` with a skip). Also hoist `_fmt_bool` (×3),
  `_format_month` (×2); delete the five `_fmt_amount = format_cents` aliases.

- [ ] **5.5 One `items_of(body)` helper.**
  The `body.get("items", body) if isinstance(body, dict) else body` idiom is
  inline 14× across commands and TUI, plus two identical private `_items()`
  helpers (`quick_log.py:627-630`, `reconciliations.py:55-58`) — and the two
  spellings differ on falsy bodies (None vs []). Promote one into
  `_resource.py`; pick the falsy behavior deliberately.

- [ ] **5.6 Small consolidations:** token redaction ×3 with two masking formats
  (`system.py:30-35`, `config_cmd.py:57-62`, auth); move
  `load_hashtag_name_map` from `dashboard_cmd.py:53-70` next to its siblings
  in `_resource.py`; unify the hashtag-cell formatter drift between CLI and
  TUI (`tui/screens/transactions.py:33-37`).

## 6. Test infrastructure & coverage of existing behavior

- [ ] **6.1 Create `tests/unit/conftest.py`.**
  No conftest exists anywhere. Consolidate: the `configured` fixture
  (byte-identical in ~16 files), a `make_cli_app(sub_app, name)` factory for
  the Typer root wiring (duplicated 16×), and a `sync_payload(**overrides)`
  builder. Migrate files incrementally.

- [ ] **6.2 One canonical `FakeClient` + wait helper for TUI tests.**
  Six divergent `_FakeClient` classes (`test_tui_writes.py:18`,
  `test_tui_create_forms.py:15`, `test_tui_quick_log.py:38`,
  `test_tui_reconciliations.py:54`, `test_tui_reconcile_detail.py:73`,
  `test_tui_system.py:48`) with mutable class-level `calls` needing manual
  reset (state-leak hazard), plus the `for _ in range(50): await
  pilot.pause(0.02)` idiom copy-pasted ~20×. Superset recorder + autouse
  reset fixture + `wait_for(pilot, predicate)` helper.

- [ ] **6.3 Cover HomeScreen menu dispatch (48% coverage).**
  The 14-branch elif mapping menu entries to screens (`home.py:67-97`) has
  zero coverage — a typo'd branch leaves a menu entry dead with a green
  suite. One parametrized headless test selecting each option id.

- [ ] **6.4 Cover SectionScreen failure paths.**
  `action_reload`, fetch-exception → error banner, and `run_write`'s
  error-notify (`_base.py:41-58,98-102,142-144`) are all missed — no TUI test
  ever renders "Could not load." or a write-failure toast. Two small tests
  with a raising fetch/FakeClient.

- [ ] **6.5 Exercise `import --apply` through the CLI; test the xlsx reader.**
  Only dry-run and missing-openpyxl go through `runner.invoke`; the --apply
  wiring incl. `cache_after_write` and exit-1-on-failures
  (`import_cmd.py:138-149`) and both `--json` renderers are untested;
  `import_/reader.py` is 37% covered (real `read_workbook` never runs). Add a
  respx-mocked `--apply` test, a `--json` dry-run test, and one real tmp-path
  workbook test.

- [ ] **6.6 Smaller coverage items:** activity name resolution tested for 1 of
  6 resource kinds (`activity_cmd.py:80-107`); `expand_hashtags` range
  rendering unreachable + untested (`reports_cmd.py:134-150` — decide: cover
  or delete); surface guard emits 41 skips and doesn't enforce the
  confirm-destructive convention that has already drifted
  (`test_command_surface.py:69-77`).

## 7. Remaining low-severity nits (batch opportunistically)

- [ ] `reconcile list` is the only list command without a table
  (`reconcile_cmd.py:117-134`). **[UI-adjacent: propose columns first per
  table-approval rule.]**
- [ ] Deleted rows indistinguishable in accounts/categories lists despite
  `--include-deleted`, while hashtags shows a Deleted column
  (`hashtags_cmd.py:47-62` vs siblings).
- [ ] Client-side re-validation / silent correction of engine rules in three
  spots (`reports_cmd.py:20,321-331`) — thin-wrapper rule says surface the
  engine's 422 instead.

## Suggested sequencing

1. **Section 1** (correctness) — small, independent, behavior-correcting.
2. **Section 3** (help-text sweep) — highest user-visible polish per effort.
3. **Sections 2 + 5.1** — error consistency rides on the `run_write` refactor.
4. **Section 6.1/6.2** (conftest) — before adding the new tests in 6.3–6.5.
5. **Section 4** — mockup/proposal pass, then implement.
6. Sections 5 (rest) and 7 — opportunistic, pure refactors.
