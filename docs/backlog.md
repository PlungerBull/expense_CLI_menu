# Backlog — engine-rework recovery + polish

> **The single open-work queue for this repo.** Merged 2026-08-15 from three
> sources: the per-entry CLI work items in
> [client-breaking-changes.md](client-breaking-changes.md) (the 2026-08 engine
> rework record, moved into this repo from the engine the same day), the
> surviving §5 nits of the 2026-07-06 polish backlog (this file's predecessor —
> renamed from `polish-backlog.md`; the fully-closed sections 1–4/6 live in git
> history), and the open TUI items from [tui-plan.md](tui-plan.md) Phase 3, plus
> the 2026-08-15 doc-alignment audit.
>
> Rule unchanged ([decisions.md](decisions.md) "backlog holds only open work"):
> closed items and phases get **deleted** from this file — git history is the
> archive. Items marked **[UI]** change something the user sees and need a
> mockup/proposal pass before implementation (CLAUDE.md "Mock every screen").

**Why phases:** the 2026-08 engine rework (transfers deleted, read-time
currency, reconciliation de-chaining, schema slimming) removed or changed
endpoints the CLI and TUI still call. Phases 2–4 restore a working CLI/TUI —
everything in them is **live-broken today** (422s, 404s, or unhandled `null`s).
Phase 5 verifies against the live engine; Phase 6 builds the new engine
capability the clients don't surface yet; Phase 7 closes residual doc
alignment; Phase 8 is pre-existing polish, schedulable anytime.
(Phase 1 — the mechanical deletions: exchange-rate purge, settings slimming,
categories/hashtags archive, inbox restore, tx-delete warnings — closed
2026-08-15 and deleted per the rule above; see git history.)

**Baseline at merge time (2026-08-15):** 900 unit tests, 899 green — the one
failure was the doc-link guard catching the engine's retired `TODO.md`, fixed
with the merge commit. Green is **false comfort** here: the respx fixtures pin
the *pre-rework* contract, so most Phase 2–4 breakage is invisible to
`pytest tests/unit`. Only the `PYTEST_LIVE=1` contract suite sees the real
engine.

**Working convention for every item below:** fix code + re-pin the affected
unit fixtures to the new engine shape + scrub the owning doc
([cli-spec.md](cli-spec.md) / [roadmap.md](roadmap.md) /
[tui-plan.md](tui-plan.md) / [decisions.md](decisions.md)) in the same commit.
Source entries in [client-breaking-changes.md](client-breaking-changes.md) are
cited by date — read the entry before starting the item; it has the full
contract detail and engine references.

---

## Phase 2 — transfer feature removal

[Entry 2026-08-10 "the transfer feature is removed".] No request may carry a
`transfer` object; `@Transfer`/`@Debt` are gone; `category_id` is
unconditionally required; **`transfer_transaction_id` is gone from responses**,
so the TUI's transfer-leg detection is dead code, not just unused.

- [ ] **2.1** Remove `log --transfer --to-account-id --to-amount` and the
  payload build (`log_cmd.py:101-108`).
- [ ] **2.2** Remove the TUI transfer sub-flow in `quick_log.py`: the
  conditional transfer fields, `_commit_to_amount` auto-sign, the
  opposite-sign mid-form guard, the transfer payload (`:478-489`), and the
  `transfer_transaction_id` field locks (`:171-174` — the field no longer
  arrives, so the locks never fire; the engine's field-lock 422s are the
  backstop).
- [ ] **2.3** Remove the batch "no transfers" pre-check remnants and any
  `transfer` mentions in `transactions_cmd.py` help text; always send
  `category_id` on creates (omission is now a plain "Field required" 422).
- [ ] **2.4** Sweep `@Transfer`/`@Debt` references (categories screens,
  docstrings, cli-spec.md §categories line 83 — system categories shrink to
  `@Opening` only).
- [ ] **2.5** Docs: retire cli-spec.md's "TUI transfer To-amount auto-sign"
  sanctioned exception (line 32) and the `log --transfer` line (95); add a
  superseding note to the decisions.md sign-convention/transfer entries; brief
  retirement note in tui-plan.md where the transfer sub-flow is described as
  shipped.
- [ ] **2.6 [UI]** *Optional, later:* a client-side "move between accounts"
  convenience = two ordinary `POST /transactions` calls. New UX → mockup
  first. Not needed for parity; park it.

## Phase 3 — reconciliation de-chaining (the biggest chunk)

[Entry 2026-08-06 "reconciliation simplification" — **its CLI work table is
the authoritative checklist**; line refs verified 2026-08-15.] Chaining,
`sort_order`, `beginning_balance_source`, and the bulk-reorder route are gone;
`beginning_balance_cents` is required on create; `difference_cents` is new.
**The TUI's default create path 422s today** (form starts at
`source: "chained"`).

- [ ] **3.1** TUI new-batch form: `begin` always required, drop the source
  picker (`tui/screens/reconciliations.py:311-348,433-480`).
- [ ] **3.2** TUI: delete `_sort_key` client-side sort and the `ctrl+↑/↓`
  reorder actions (`:71-74,265-287`); rely on server order
  (`date_start ASC NULLS LAST, created_at ASC` when account-scoped); fix the
  chain-model docstring (`:1-22`).
- [ ] **3.3** Delete `reconcile move` and `reconcile reorder` whole
  (`reconcile_cmd.py:646-770,807-891`) — both end at the deleted route. Their
  only helper consumer is `expense/_editor.py` → **delete it too** and its
  cli-runtime.md mention; note in CLAUDE.md that the `_editor.py`
  CLI-specific bullet dies with it.
- [ ] **3.4** `reconcile_cmd.py` flag/render sweep: drop `--source` /
  `--sort-order`, the mutual-exclusion guards, the `Source` column +
  `_format_source_marker`, the chained-ambiguity 422 sniffer,
  `ReconciliationSource`, `_render_reorder_response`; make
  `--beginning-balance` required on `create` (line refs in the entry's table).
- [ ] **3.5 [UI]** Surface the new `difference_cents` on reconcile
  list/detail (CLI table + TUI) — it is the add-up check the feature exists
  for. Column change → propose + mockup first.
- [ ] **3.6** Tests: `test_cmd_reconcile.py`, `test_tui_reconciliations.py`,
  `test_tui_reconcile_detail.py`. Docs: cli-spec.md:105-114 (sort contract,
  `move`/`reorder`, `--source`), roadmap.md Step 6 gets a retirement banner
  like Step 7's, tui-plan.md chain references, decisions.md superseding note.

## Phase 4 — nullable home aggregates + dashboard panel removals

[Entry 2026-08-05 "currency converts at read time", items 5–7.] Native
cross-currency aggregates are deleted; every remaining home aggregate is
nullable with an `unconverted_count`; `/dashboard` lost
`archived_categories`/`archived_hashtags`. `unconverted_count` appears **zero
times** in this repo today — an unconvertible month crashes or misrenders.

- [ ] **4.1 [UI]** Decide + mock the "unavailable" rendering once (a `null`
  is *not* zero and *not* missing — render as unavailable **with the count**,
  never `0`, never a native-figure fallback), then apply everywhere:
  `reports_cmd.py:42,53,112,121,126`, TUI `home.py:105-111` stat cluster,
  `outstanding.py:54` totals, `_resource.py:453,461` (the native-key
  derivation — those keys are gone; read the home keys directly).
- [ ] **4.2** `dashboard` command: remove the archived-categories and
  archived-hashtags panels (`dashboard_cmd.py:134-147`); `archived_accounts`
  stays. Same in any TUI surface that mirrors them. Doc scrub: cli-spec.md
  §dashboard `--include-archived` (line 118), roadmap Step 5 note.

## Phase 5 — contract re-verification gate

- [ ] **5.1** Fixture audit: sweep `tests/unit` fixtures for retired fields
  (`transfer_*`, `exchange_rate`, `amount_home_cents`, `is_archived` on
  cats/hashtags, `beginning_balance_source`, `sort_order`, settings fields,
  `warnings` on tx delete) so the mocks pin the *new* contract — Phases 1–4
  each re-pin their own; this is the closing sweep for stragglers.
- [ ] **5.2** Supervised `PYTEST_LIVE=1` contract run against the loopback
  engine (per [cli-runtime.md](cli-runtime.md) "Working against the live
  engine"); fix `test_freshman_flow.py` drift found there. This is the gate
  that declares the TUI/CLI *working again*.

## Phase 6 — additive engine capability (unusable until built)

- [ ] **6.1 [UI] Inbox hashtags.** [Entry 2026-08-14 "inbox drafts carry
  hashtags".] Add `--hashtags` to `inbox add`/`update` (same comma-separated
  shape as transactions; PUT semantics are replacement — omit = leave, `[]` =
  clear); render `hashtag_ids` on inbox rows (CLI table column + TUI — the
  TUI form can reuse the transaction form's hashtag multi-select). No
  post-promote re-tagging exists in this repo, so nothing to remove. Column
  additions → mockup first.
- [ ] **6.2 [UI] People API.** [Entry 2026-08-14 "the People API ships".]
  (a) a create-person command (`POST /people` — the only `/people` route ever;
  everything else goes through `/accounts/{id}`, which already accepts person
  rows — **never** build list/edit paths against `/people`); (b) render
  `archived_people` beside `archived_accounts` (`dashboard_cmd.py:134`, TUI
  accounts archived view); (c) **collapse settled people, never hide them**
  (`home.py:101`, `outstanding.py:168`) — the entry's design rule + suggested
  `▸ 3 settled` shape. All three are user-visible → mockups + naming proposal
  (e.g. `expense people create` vs `accounts create-person`) before code.

## Phase 7 — documentation alignment (residual sweep)

Per-item doc scrubs ride Phases 1–6; this phase is what's left plus the final
check.

- [ ] **7.1** Rewrite the roadmap.md `## Status` paragraph — it still
  describes the pre-rework engine (categories/hashtags archive, the
  `archived_categories`/`archived_hashtags` dashboard panels, "currencies
  locked at the schema to USD/PEN", Render-era framing); refresh the footer
  "Last updated" line.
- [ ] **7.2** CLAUDE.md refresh: Status section (point at this backlog's
  phases instead of "the 2026-07-06 best-practices backlog"); doc-table row
  for [client-breaking-changes.md](client-breaking-changes.md); prune retired
  CLI-specific bullets (`_editor.py` after 3.3).
- [ ] **7.3** decisions.md entries for the big engine deletions as they land
  client-side (transfer removal, de-chaining) — each points at its
  client-breaking-changes entry rather than duplicating it.
- [ ] **7.4** Final pass: `pytest tests/unit/test_docs_links.py` green, plus a
  stale-term grep over `docs/` (`chained`, `--source`, `transfer`,
  `exchange-rate`, `main-currency`, `include_archived` on cats/hashtags) with
  every survivor either historical-and-bannered or deleted.
- [ ] **7.5** Decide whether the engine-side uncommitted `git rm` of
  `docs/client-breaking-changes.md` + `TODO.md` should be committed in the
  engine repo (this repo now carries the file; two working trees currently
  disagree with their HEADs).

## Phase 8 — pre-existing polish (unblocked; batch opportunistically)

Survivors of the 2026-07-06 review §5 + tui-plan Phase 3 opens. None depend on
Phases 1–7.

- [ ] Connection errors exit with code 2 (`errors.py:85-86`), colliding with
  Click's usage-error 2 — move to an unused code.
- [ ] Reports: `_render_range_table` hand-rolls the width/format loop the
  shared `render_table` covers (`reports_cmd.py:131-186`).
- [ ] `reconcile complete` inlines the hint-haystack scan that
  `transactions_cmd.py:104-117` wraps in `_update_hint_for` — hoist to
  `_resource.py`. (`complete` survives de-chaining.)
- [ ] **[UI]** Inbox and transactions lists accept `--include-deleted` but
  render no Deleted column (accounts/reconcile have one) — proposed-columns
  mockup first. *(No longer rides any cache decision — the replica is gone;
  reads are live, so the flag is honest everywhere.)*
- [ ] Import: the `.xlsx` reader materializes all rows (`reader.py:61`)
  rather than streaming — **recorded deferral**, fine at personal scale;
  documented at the materialization site.
- [ ] Tests: ~37 remaining `pilot.pause(0.05)` sites across the TUI suite →
  `wait_for` or bare `pilot.pause()` — mechanical, time-boxable sweep.
- [ ] TUI light theme + `NO_COLOR` palette (same `ansi_default` surface;
  tui-plan §4) — needs the terminal-background detection piece.
- [ ] TUI `?` help overlay; Textual command palette (tui-plan Phase 3).
- [ ] Open decisions from tui-plan §9: designer's final theme tokens (#3);
  minimum terminal size fallback (#5).
- [ ] Post-Step-9 ergonomics (quick-add parser, shell completions, …) stay
  planned in [roadmap.md](roadmap.md) "Post-Step-9 ergonomics" — pointer
  only; they start after Phase 5's gate at the earliest.

### Dropped as moot (recorded once, then delete on next touch)

Three 2026-07-06 §5 nits died with the engine rework rather than being fixed:
the `reconcile move --json` empty-output nit and the `_validate_source_choice`
Enum nit (both commands/flags are deleted outright in Phase 3), and the
`--include-deleted` item's dependency on the old cache decision (the flag's
[UI] half survives above).
