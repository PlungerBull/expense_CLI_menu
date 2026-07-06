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

- [x] **1.2 Archive commands must confirm (CLAUDE.md non-negotiable).**
  `accounts archive` (`accounts_cmd.py:306-324`), `categories archive`
  (`categories_cmd.py:287-295`), `hashtags archive` (`hashtags_cmd.py:265-273`)
  have no `--yes` and no prompt; the TUI confirms the same action. Fix: add
  `--yes/-y` + `require_yes(...)` before `run_toggle`. Unarchive stays
  prompt-free.

- [x] **1.3 Guard the three unguarded TUI fetch workers (app-crash bug).**
  Textual `@work` defaults to `exit_on_error=True`, so an engine/config error
  inside `NewReconciliationScreen._load_accounts`
  (`reconciliations.py:398-416`), `ReconciliationDetailScreen._load_txns`
  (`reconciliations.py:721-771`), or `QuickAddLogScreen._load_entities`
  (`quick_log.py:222-249`) exits the whole app (verified live). Fix: same
  try/except → `call_from_thread(error banner/notify)` pattern
  `SectionScreen._load` already uses (`_base.py:54-58`).

- [x] **1.4 Corrupt `~/.expense-config` → clean error, not traceback.**
  `config.load()` raises bare `ValueError` on bad JSON and lets pydantic
  `ValidationError` escape (`expense/config.py:29-33`); `handle_errors`
  re-raises both (verified live: full Rich traceback). Fix: raise
  `ConfigMissingError` or a sibling `ConfigInvalidError` rendered the same
  way, with the existing `expense config set ...` recovery hint. Add unit test.

- [x] **1.5 Corrupt SQLite cache → wipe and rebuild, not crash.**
  `db.connect()` has no corruption guard; a garbage cache file raises
  `sqlite3.DatabaseError` at the WAL pragma (`expense/cache/db.py:28-41`,
  verified live). The module's own contract is wipe + cold-start and `wipe()`
  exists (`db.py:171`). Fix: catch `sqlite3.DatabaseError` in `connect()`,
  wipe, retry once. Add unit test in `test_cache.py`.

- [x] **1.6 `transactions batch` human output dumps a Python repr.**
  After the `Created: <id>` lines, the batch envelope `{"created": [...]}` is
  passed to `_render_transaction`, printing a single-quoted repr of the whole
  array (`transactions_cmd.py:471-476`, verified by reproduction). Fix: render
  a count summary (and/or per-item key/value dumps); assert the repr never
  appears in output.

- [x] **1.7 Auth writes skip the post-write replica refresh.**
  `auth settings` / `auth profile` / `auth bootstrap`
  (`auth_cmd.py:281-287,209-210,131-132`) never call `cache_after_write`,
  unlike every other write. A `--main-currency` change rewrites
  `amount_home_cents` server-side, leaving the replica stale. The TUI
  equivalents already refresh. Fix: call `cache_after_write` in all three.

## 2. Error-handling consistency

- [x] **2.1 Route TUI errors through the canonical renderer.**
  All 16 TUI error sites notified `str(exc)` (13 when filed; 3 fetch-worker
  sites were added by the 1.3 fix, commit 795c0cd), dropping the engine error
  `code`, per-field 422 hints, and the "could not reach engine at {url}"
  guidance that flat commands render. Fixed: `format_error(exc) -> str` in
  `expense/errors.py` shares `render()`'s human branch (render is now
  `"Error: " + format_error(err)`); all 16 sites in `_base.py`, `system.py`,
  `create_forms.py`, `quick_log.py`, `reconciliations.py` use it. Same
  banners/toasts, richer text.

- [x] **2.2 Importer: survive mid-run connection failure.**
  `apply_plan`'s chunk loop caught only `EngineError`
  (`expense/import_/apply.py`); an `EngineConnectionError` mid-run aborted
  before `_render_result`, so committed chunks went unreported. Fixed: the
  loop catches `EngineConnectionError`, marks the failing and remaining
  chunks failed, breaks, and returns normally — summary renders, exit 1.
  (The backlog's `cache_after_write` concern was moot: `refresh_after_write`
  already swallows all failures with a stderr warning.)

- [x] **2.3 One destructive-confirm implementation, one exit code.**
  `require_yes` (`_resource.py`, exits 1) was re-implemented inline in
  `auth settings` (exits 1) and `config clear` (exited **3** — colliding with
  CONFIG_MISSING). Fixed: both call `require_yes`; missing-confirmation exits
  1 everywhere.

## 3. Help text & CLI output polish (highest polish-per-effort)

- [x] **3.1 Fix the four broken docstring examples.**
  `reconcile list/create/reorder` examples say `--account` but the flag is
  `--account-id` (`reconcile_cmd.py:224,314,817-818`); `auth settings` example
  uses `--theme dark --start-of-week monday` on int-typed options
  (`auth_cmd.py:244`) — fails Typer parsing if copy-pasted. Consider a small
  test that extracts `Example:` lines and asserts each flag exists.

- [x] **3.2 Fix the `--resource-type` guidance.**
  Help, docstring example, and the `transactions get` cross-reference all
  recommend `expense_transactions` (`activity_cmd.py:206,222`,
  `transactions_cmd.py:270-272`) but the engine writes singular
  (`transaction`) — following the help returns a silently empty list. Keep the
  plural aliases in `_RESOURCE_KIND` for display robustness only.

- [x] **3.3 Strip internal roadmap leakage from user-facing text.**
  "once Step 8 ships" for a shipped feature (`transactions_cmd.py:270-272`),
  "(Step 6: …)" (`transactions_cmd.py:38-39`), "(Step 4)"
  (`inbox_cmd.py:357-358`). Keep just the concrete command suggestions.

- [x] **3.4 Consistent option help text via shared option constants.**
  Many flags render bare in `--help` (`transactions_cmd.py:219-227` documents
  4 of 10 options; `accounts_cmd.py:122-125` documents none) and `--json` has
  six different wordings. Fix: hoist `JSON_OPT` / `LIMIT_OPT` / `OFFSET_OPT` /
  `INCLUDE_DELETED_OPT` etc. into `_resource.py` with one wording; reuse
  everywhere (bespoke semantics like `reconcile reorder --json` stay bespoke).

## 4. TUI polish — **[UI] items need mockup review first**

- [x] **4.1 [UI] Resolve the `r` keybinding collision.** *(done 2026-07-05,
  per approved mockup `expense-world-keymap-4.1.html` v2, validated by a
  four-agent adversarial review)* Revert moved to `u` ("unlock", vim-style,
  opposite hand from r — `v` rejected: same finger column as r/f and reserved
  for a future "view"); recon detail gained `r` = refresh that refetches the
  batch record too (stale header/status would misrepresent state) on its own
  worker group; `ConfirmModal` now confirms on `y` only — `enter` CANCELS
  (safe default; dead-enter looks hung and flips meaning mid PromptModal→
  ConfirmModal chains); Sync `f` full rebuild now confirms (guards an
  f=Filter slip into a long re-download — not data loss; replica only).
  `d`/`b`/`t` cross-screen reuse kept deliberately: slips can't mutate
  (writes confirm; Rates letters open prompts). Keymap contract: **r always
  refreshes · y alone confirms · enter never mutates (submits typed
  forms/prompts, cancels confirms) · no single unmodified keypress performs
  an irreversible write without a modal.** Exempt by design: `space`
  checklist toggle + `ctrl+↑↓` chain reorder (modified chord, self-reversing).
  Future: rename on Manage screens must ship as `e`, never `r` (two older
  mockups show `r rename` — superseded).

- [x] **4.2 [UI] Theme-resolve hardcoded colors; settle amount-coloring rule.**
  *(done 2026-07-06, per approved mockup `expense-world-amount-colors-4.2.html`)*
  Rule picked: **A — sign-color everywhere** (transaction amounts, account
  balances, dashboard totals via theme $success/$error) with reconciliation
  begin/end **checkpoints plain** (positions, not judgments — per the approved
  remaining mockup) and the default cursor-row reverse (colored background)
  accepted. `theme.py` retuned to the approved mockup hexes (error `#cf8d8d`,
  warning `#d6b878`). Plumbing: `Palette`/`resolve_palette` in theme.py —
  reads `app.current_theme`, NOT `theme_variables` (its shade generation
  HSL-roundtrips and drifts a channel by one bit) — `amount_cell` in
  widgets/cells.py, palette threaded through the pure row builders (trailing
  optional param; `None` = today's plain strings, tests stay pure); checked
  marks → $success, recon status → $success/$warning; screens rebuild on
  `theme_changed_signal`, so ctrl+p live theme switching recolors Rich
  content too. Guard test bans literal green/red/yellow styles under
  expense/tui/ (create_forms swatch-name data exempt).

- [x] **4.3 [UI] Remove or wire the fake "● connected" home-screen status.**
  Hardcoded string that reflects nothing (`home.py:56`).
  *(done 2026-07-06, per gate mockup `expense-world-home-status-4.3.html`)*
  Pick: **A — removed** (over B local-only status and C live /health ping;
  both remain fully designed on the mockup if ever wanted). Deleted the
  Static + the `#status` tcss rule (its bottom gap moved onto `#brand`).
  This supersedes tui-plan.md Phase 0's "live status line" — decided
  against, not forgotten. Kept regardless: the autouse test-hermeticity
  fixture (every unit test gets tmp `EXPENSE_CONFIG`/`EXPENSE_CACHE`),
  landed as its own commit since any future home-screen state read would
  otherwise touch the developer's real config in 49 test launches.

- [x] **4.4 [UI] `#field` label column (width: 11) clips longer form labels**
  like "TRANSFER TO?" / "BEGIN BALANCE" (`app.tcss:59-65`).
  *(done 2026-07-06, per approved mockup `expense-world-field-width-4.4.html`)*
  Width 11 minus the 1-cell right padding left 10 content cells — so
  `END BALANCE` (11) clipped too, not just the two named. Fix: `width: 14`
  (longest label `BEGIN BALANCE` 13 + padding 1); `width: auto` rejected —
  the label swaps in-place while cycling fields, auto would jitter the
  input's left edge. Guard `tests/unit/test_tui_field_width.py` computes
  the longest label from the forms' own definitions (quick_log `_LABELS`,
  reconciliations `_R_LABELS`, create-form `FIELDS`) and pins the tcss
  width — a future longer label fails CI by name.

- [x] **4.5 Drop redundant re-declared escape/r bindings on System screens**
  (`system.py:50-55,135-140,305-310`) — inherited already; pure cleanup.
  *(done 2026-07-05, with 4.1)* Also dropped: the Reconciliations browse's
  `r` re-declare (it IS a SectionScreen; its custom `escape`→back stays) and
  Rates' `escape` re-declare. Sync's `s` relabeled "Refresh (delta)" → "Sync"
  to mirror the flat `expense sync` command (`f` ↔ `expense sync --full`).
  Verified against installed Textual 8.2.7: bindings merge per-key up the
  MRO, so the merged map (footer order/labels included) is bit-identical.

- [x] **4.6 [UI] `q` quits the app instantly from inside ConfirmModal and
  every list screen** (letters bubble to App's `q`=Quit, `app.py:23`; modals
  contain nothing focusable). Pre-existing, found by the 4.1 key audit.
  *(done 2026-07-06, per gate mockup `expense-world-quit-unarchive-4.6-4.7.html`)*
  Pick: **B — `q` scoped to HomeScreen** (App-level binding removed; quit
  from home stays one key, `q` is inert on sections and inside modals;
  `ctrl+q` remains the built-in everywhere-quit). Pilot tests pin all three
  behaviors: quits from home, inert on a section screen, inert inside an
  open ConfirmModal.

- [x] **4.7 Align unarchive-confirm philosophy across clients.** The TUI
  confirms both archive and unarchive (`_base.py:166-179`) while backlog 1.2
  deliberately made CLI `unarchive` prompt-free. Pick one rule.
  *(done 2026-07-06, per the same gate mockup)* Rule: **confirm the hiding
  direction only** — `archive_selected` now runs unarchive directly (toast
  "Unarchived."), archive keeps its ConfirmModal. One philosophy on both
  clients; covers Accounts/Categories/Hashtags via the shared helper.

- [ ] **4.8 Convert Rates to the bar-cycle form idiom** (like quick-log /
  create forms) instead of `t`/`b`/`d` letter-jumps — it's the only screen
  that sets form values via letters; converting dissolves the d/b/t
  cross-screen reuse at the root. Low priority (rare reference screen); do
  not add another letter-jump screen in the meantime.

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

- [x] **6.1 Create `tests/unit/conftest.py`.**
  Done: `tests/unit/conftest.py` (fixtures `configured` /
  `configured_stateless` / `configured_synced` / `fake_client`) +
  `tests/unit/helpers.py` (`make_cli_app`, `sync_payload`, `insert_*`,
  `FakeClient`, `wait_for`). All 16 files migrated in one pass (not
  incrementally); local `configured`/wiring/`_sync_payload`/`_insert_*`
  copies deleted.

- [x] **6.2 One canonical `FakeClient` + wait helper for TUI tests.**
  Done: the six `_FakeClient` classes are one instance-level
  `helpers.FakeClient` handed out by the `fake_client` fixture (per-test
  instance — no class-level state, nothing to reset; the fixture also bundles
  the ExpenseClient/ensure_loaded/refresh_after_write patches). All 25
  pause-loops and the 5 file-scoped `_wait*` helpers are
  `wait_for(pilot, predicate)`, which `pytest.fail`s at the wait site on
  timeout instead of falling through silently.

- [x] **6.3 Cover HomeScreen menu dispatch (48% coverage).**
  Done: `tests/unit/test_tui_home_dispatch.py` — parametrized headless test
  drives focus → highlight → enter for each of the 13 wired entries and
  asserts the pushed screen type; `soon` asserts the notify + stays home; an
  armor test keeps `_MENU` and the case list in lock-step.

- [x] **6.4 Cover SectionScreen failure paths.**
  Done: `tests/unit/test_tui_section_errors.py` — fetch error renders the
  "Could not load." banner with the canonical `format_error` text; `r`
  reloads and recovers after an error; a failing `run_write` toasts
  title=Failed/severity=error with no success toast and no replica refresh.

- [x] **6.5 Exercise `import --apply` through the CLI; test the xlsx reader.**
  Done: `test_cmd_import.py` gained a respx-mocked `--apply` happy path
  (asserts the post-write `/v1/sync` fired via `cache_after_write`), a
  `--json` dry-run test (pure JSON, no trailer), and a `--json` apply test
  with a mid-run failure (envelope + exit 1). New
  `tests/unit/test_import_reader.py` runs real openpyxl workbooks: happy
  path, reader→parser roundtrip (serial dates, major amounts), missing
  file/sheet, empty sheet, garbage file, missing-dependency guard.

- [x] **6.6 Smaller coverage items:** activity name resolution now covered for
  all 6 kinds incl. plural aliases, the `#` hashtag prefix, reconciliation
  composite labels, and every fallback; `expand_hashtags` **deleted** from
  `reports_cmd.py` (decision: the single-month report already renders the
  breakdown by default and `--json` carries it for ranges — the range-table
  variant was unreachable); surface guard parametrizes read leaves only
  (41 skips → 0) and a new check enforces `--yes` on all 11
  delete/archive/revert/clear leaves, with a pinned count so renames can't
  evade it.

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
