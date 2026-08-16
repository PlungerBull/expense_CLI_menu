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
>
> **Phase-opening sketch (rule added 2026-08-16, user decision).** Before any
> work starts on a phase, produce a **sketch** — an HTML page in
> [mockups/](mockups/) — showing what the phase will change and how the
> affected screens/commands will look after it, and present it for review
> together with the phase's decision questions (each explained in plain user
> terms, never assumed). This applies to every phase, not only ones with
> **[UI]** items: even a pure-removal phase changes what the user sees.
> (Phase 2's sketch was produced retroactively the same day:
> [mockups/expense-world-phase2-sketch.html](mockups/expense-world-phase2-sketch.html).)

**Why phases:** the 2026-08 engine rework (transfers deleted, read-time
currency, reconciliation de-chaining, schema slimming) removed or changed
endpoints the CLI and TUI still call. **The recovery is verified done** —
Phase 5, the gate, closed 2026-08-16: the contract suite passes 9/9 against a
real engine, which is the first real-engine check since the rework began.
Phase 6 builds the new engine capability the clients don't surface yet;
Phase 7 closes residual doc alignment; Phase 8 is pre-existing polish,
schedulable anytime.
(Phase 1 — the mechanical deletions: exchange-rate purge, settings slimming,
categories/hashtags archive, inbox restore, tx-delete warnings — closed
2026-08-15; Phase 2 — the transfer-feature removal, items 2.1–2.5 — closed
2026-08-16, with the optional 2.6 convenience re-parked under Phase 8 below;
Phase 3 — reconciliation de-chaining, items 3.1–3.6 — closed 2026-08-16
(sketch: [mockups/expense-world-phase3-sketch.html](mockups/expense-world-phase3-sketch.html));
Phase 4 — nullable home aggregates + the archived category/hashtag panel
removal, items 4.1–4.2 — closed 2026-08-16
(sketch: [mockups/expense-world-phase4-sketch.html](mockups/expense-world-phase4-sketch.html),
picks C/F/J; the "hide rows with nothing spent" rule was added there by user
decision and applies to the dashboard, the monthly report and the TUI
Outstanding tree alike; rationale in [decisions.md](decisions.md));
Phase 5 — the contract re-verification gate, items 5.1–5.2 — closed
2026-08-16
(sketch: [mockups/expense-world-phase5-sketch.html](mockups/expense-world-phase5-sketch.html),
pick C; rationale in [decisions.md](decisions.md) "Contract tests verify
against a disposable database"). What it changed beyond the plan: the suite
now runs against `expense_world_test` through a second engine on `:8001` and
**refuses** to write to the real ledger; three contract files were broken, not
one; and the gate found a genuine client bug — `--cleared` on `inbox
add`/`update` and the TUI draft-edit form, a field the engine has never
accepted there, which 422'd and lost the whole write (removed; sketch:
[mockups/expense-world-phase5-inbox-cleared.html](mockups/expense-world-phase5-inbox-cleared.html)).
All five deleted per the rule above, see git history.)

**Baseline (2026-08-16, after Phase 5):** 868 unit tests green — fewer than the
900 at merge time because Phases 1–4 deleted features and their tests with them.
Unit green was **false comfort** for Phases 1–4: the respx fixtures pinned the
*pre-rework* contract, so breakage was invisible to `pytest tests/unit`. Phase 5
closed that hole two ways — the fixtures now match the engine's published
schemas, and [scripts/check_fixture_drift.py](../scripts/check_fixture_drift.py)
re-checks that mechanically — but the principle stands for future engine
changes: only the contract suite sees a real engine.

**Working convention for every item below:** fix code + re-pin the affected
unit fixtures to the new engine shape + scrub the owning doc
([cli-spec.md](cli-spec.md) / [roadmap.md](roadmap.md) /
[tui-plan.md](tui-plan.md) / [decisions.md](decisions.md)) in the same commit.
Source entries in [client-breaking-changes.md](client-breaking-changes.md) are
cited by date — read the entry before starting the item; it has the full
contract detail and engine references.

---

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
  for [client-breaking-changes.md](client-breaking-changes.md). *(The
  `_editor.py` bullet was pruned with Phase 3.3, 2026-08-16.)*
- [x] **7.3** decisions.md entries for the big engine deletions as they land
  client-side — transfer removal + de-chaining both written 2026-08-16, each
  pointing at its client-breaking-changes entry rather than duplicating it.
  Any later deletion gets the same treatment.
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
- [ ] **[UI]** *Optional (re-parked from Phase 2.6, 2026-08-16):* a
  client-side "move between accounts" convenience = two ordinary
  `POST /transactions` calls. New UX → mockup first. Not needed for parity.
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
  only. **Unblocked 2026-08-16**: Phase 5's gate was their precondition and
  it passed.

### Dropped as moot (recorded once, then delete on next touch)

Three 2026-07-06 §5 nits died with the engine rework rather than being fixed:
the `reconcile move --json` empty-output nit and the `_validate_source_choice`
Enum nit (both commands/flags were deleted outright in Phase 3), and the
`--include-deleted` item's dependency on the old cache decision (the flag's
[UI] half survives above).
