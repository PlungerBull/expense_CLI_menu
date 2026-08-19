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
>
> **Exemption (2026-08-16, user decision).** A **docs-only** phase — one that
> changes no command, screen or output, only prose — is exempt: there is
> nothing to draw, and a before/after page of paragraphs is just the diff with
> extra steps. Phase 7 was the first to use this. The rule is unchanged for
> everything else; "docs-only" means *no* code touched, not "mostly docs".

**Why phases:** the 2026-08 engine rework (transfers deleted, read-time
currency, reconciliation de-chaining, schema slimming) removed or changed
endpoints the CLI and TUI still call. **The recovery is verified done** —
Phase 5, the gate, closed 2026-08-16: the contract suite passes 9/9 against a
real engine, which is the first real-engine check since the rework began.
**Phase 6 — the new engine capability the clients did not surface — closed
2026-08-16 as well**, so nothing the 2026-08 rework touched is outstanding.
**Phase 7 — residual doc alignment — closed 2026-08-16** as well, leaving
**Phase 8 (pre-existing polish) as the only open phase**, schedulable anytime.
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

**Baseline (2026-08-18, after the Phase 8 `pilot.pause` sweep):** 922 unit tests
green (920 + the two hygiene guards), contract suite 12/12 against the disposable
engine on `:8001`.

**Baseline (2026-08-16, after Phase 6.2):** 903 unit tests green, and the
contract suite is 12/12 against the disposable engine on `:8001`. (868 after
Phase 5; 6.1 added 14; 6.2 added 21 unit + 2 contract.) The note below still
holds and is why 6.1 and 6.2 both shipped with a live check rather than unit
tests alone — worth repeating, because
[scripts/check_fixture_drift.py](../scripts/check_fixture_drift.py) cannot help
with *additive* engine changes at all: it only detects fields the engine has
**stopped** serving, never one a fixture is missing.

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

## Phase 6 — additive engine capability — ✅ closed 2026-08-16

Both items shipped and verified against a real engine. Kept as closed-item notes
only because each records what changed beyond its plan; delete on next touch.

*(6.1 — inbox hashtags — closed 2026-08-16; deleted per the rule above, see git
history. Sketch:
[mockups/expense-world-phase6-inbox-hashtags.html](mockups/expense-world-phase6-inbox-hashtags.html),
picks A/E/H. What it changed beyond the plan: the flag is `--hashtag-ids`, not
the `--hashtags` this item wrote — three shipped surfaces already spelled it the
long way, and the option takes ids, not names. `parse_hashtag_ids` was hoisted
to `_resource.py` first, since a naive implementation would have made four
copies of one comma-split. Verified against a real engine: contract suite 10/10
on `:8001`, including a new `test_inbox_hashtags_lifecycle` that pins all three
PUT semantics and that promotion carries the tags across.)*

*(6.2 — the People API — closed 2026-08-16; deleted per the rule above, see git
history. Sketch:
[mockups/expense-world-phase6-people.html](mockups/expense-world-phase6-people.html),
picks B/D/G/J/L. Shipped: `expense accounts create-person` → `POST /people`
(with a 409 hint explaining that people and bank accounts share one name list per
currency); the `archived_people` panel after `archived_accounts`; `split_settled`
/ `settled_label` in `_resource.py` and the `▸ 3 settled` fold on the typed
dashboard; `PeopleView` in `outstanding.py` — the same `▼/▶` fold as the
categories tree, closed by default; and a **TYPE** field (`bank`/`person`,
prefilled `bank`) on the TUI New Account form, locked read-only on edit.
What it changed beyond the plan: **two of the item's three code anchors were
stale, and one changed the work.** `home.py:101` is `_extract_stats`, and home
has **no People list at all** — only the aggregated `owed` figure, which already
vanishes when everything nets to zero, so item (c) had no home-screen half and
`home.py` was not touched. The TUI half of item (b) was likewise a no-op: the
Accounts screen already fetches `include_archived=True, include_people=True` and
has `Type`/`Status` columns, so archived people appear there with no new code
(shown as a real render in the sketch's §9). `outstanding.py:168` is inside
`CategoriesView.action_move`; the People block was at 208-211. Verified against a
real engine: contract suite on `:8001`, including a new
`tests/contract/test_people_lifecycle.py` that pins all four shape decisions plus
the settled-visibility rule — the one check that can see an additive endpoint at
all.)*

## Phase 7 — documentation alignment — ✅ closed 2026-08-16

Deleted per the rule above; kept only as a closed-item note because three of
its five items turned out to be mis-scoped, which is worth recording once.

- **7.1 was bigger than its own description.** The item named the roadmap's
  `## Status` paragraph; the file was stale throughout — Step 1's settings
  list contradicted [cli-spec.md](cli-spec.md), Steps 2 and 3 had no banner at
  all, and the Step 9.5 deletion banner sat *after* the ~200 lines it
  disclaimed, saying "below" where it meant "above". Fixed by the user's
  **banner-don't-rewrite** call: history stays, each superseded step gets a
  dated banner, only false present-tense sentences were reworded.
- **7.2 was ~80% already done.** The `client-breaking-changes.md` doc-table row
  existed and the Status paragraph already pointed here. Its parenthetical
  chased "the 2026-07-06 best-practices backlog" — a string that has never
  appeared in CLAUDE.md. Real fix was one sentence: Phase 6 had closed.
- **7.5 needed no action.** The engine had already committed the `git rm`
  (engine commit `a44237e`); both working trees were clean, so the item's
  premise was gone. Nothing was written to the engine repo.
- Beyond the plan: the `cleared` removal was dated **2026-08-17** in seven
  places — a date that had not happened (commit `02c95e8` landed 2026-08-16).
  Also corrected: roadmap documented `--limit`/`--cursor` pagination the engine
  never shipped (it is offset-based); [decisions.md](decisions.md) still listed
  exit codes 4/5 as live and carried a dead cli-runtime.md anchor;
  `cli-spec.md`'s rates heading named a command group (`exchange-rates`) that
  is registered as `rates`.

## Phase 8 — pre-existing polish (unblocked; batch opportunistically)

Survivors of the 2026-07-06 review §5 + tui-plan Phase 3 opens. None depend on
Phases 1–7. **Worked in three passes** — 2026-08-16 (deleted-rows shipped, three
items struck as already done), 2026-08-17 (the discoverability pair) and
**2026-08-18 (the `pilot.pause` sweep)**; the rest stay open.
Sketches: [mockups/expense-world-phase8-sketch.html](mockups/expense-world-phase8-sketch.html),
[mockups/expense-world-phase8-discoverability.html](mockups/expense-world-phase8-discoverability.html).

- [ ] TUI light theme + `NO_COLOR` palette (same `ansi_default` surface;
  tui-plan §4). **Approach decided 2026-08-16 — auto-detect** the terminal
  background (`OSC 11` + `COLORFGBG` fallback, dark default); see
  [decisions.md](decisions.md) "The light theme will detect the terminal".
  Textual ships **no** such detection (checked in 8.2.7), so the query is
  hand-written in `run_world` before Textual takes the tty, with a timeout so
  a silent terminal cannot hang the app. `NO_COLOR` stays a third mode
  (`Theme(ansi=True)`), not the light theme.
- [ ] Open decisions from tui-plan §9: designer's final theme tokens (#3 —
  note it names a `theme.tcss` that was never created; tokens are `Theme`
  fields in [theme.py](../expense/tui/theme.py)); minimum terminal size
  fallback (#5 — partially handled already: `PAGE_ROWS_FLOOR = 5` degrades
  rather than refuses).
- [ ] Post-Step-9 ergonomics (quick-add parser, shell completions, the
  "move between accounts" convenience, …) stay planned in
  [roadmap.md](roadmap.md) "Post-Step-9 ergonomics" — pointer only.
  **Unblocked 2026-08-16**: Phase 5's gate was their precondition and it
  passed.

### Closed 2026-08-18 (delete on next touch)

**The `pilot.pause` sweep — shipped, and armored.** Every timed pause in the TUI
suite is now either a condition wait (`wait_for`) or a bare pump-drain; the item
is closed by [tests/unit/test_suite_hygiene.py](../tests/unit/test_suite_hygiene.py),
which fails on the 32nd one. This was the *second* pass over the same problem —
commit `9d8d2c3` converted the first 25 — which is the whole argument for making
it executable rather than a convention.
What changed beyond the item's own description, which was wrong three ways:
**(1) 31 sites, not 26** — it counted only `pause(0.05)` and missed `0.1` ×3,
`0.02` ×1, `0.25` ×1; final split 21 → `wait_for`, 9 → bare pause, 1 kept.
**(2) One timed pause has to survive**: `test_tui_reconcile_detail.py`'s
`pause(0.25)  # window for the cancelled worker to (not) paint` — its fake fetch
does a real `time.sleep(0.15)` and the test exists to outlast it, so a pump-drain
would not wait long enough. It is the guard's single allowlist entry, keyed on the
whole source line so editing it re-opens the question, plus a second test that
fails if the exemption outlives the line it exempts. **(3) The "6 load-bearing"
figure was right** — confirmed site-by-site, and it stayed 6 of the 0.05 sites.
Also folded in (user decision): the `CursorList`-mounted-and-loaded predicate had
**13 copies across 8 files** in three different wrappings (and two scopings,
`app.screen` vs `screen`) → `list_ready` / `wait_for_list` in
[helpers.py](../tests/unit/helpers.py), which also killed the
file-local `_wait_loaded`/`_wait_browse` wrappers; and `wait_for_loaded` — **dead
code with zero call sites** while `test_tui_help.py` open-coded its equivalent
five times — was resurrected rather than deleted. Honest result on speed: the
suite got ~3% faster (22.4s → 21.6s), not the ~1.3s the sweep looked worth on
paper, because `wait_for` polls on a 20ms tick and most waits resolve on the
second or third one. The win is that a slow CI box can no longer fail a green
build.

### Closed 2026-08-17 (delete on next touch)

**The `?` help overlay + the command palette — both closed, one by building and
one by deleting.** The two items were worked as one because they render the same
inventory. Auditing first changed both premises: the palette was **already
advertised** (Textual's `Footer` prints `^p palette` by default), and a keys
panel **already existed** (`HelpPanel` via `ctrl+p → Keys`, captured against our
own bindings in the sketch §1.2) — so the choice was curate or accept Textual's,
not build-from-nothing. Shipped: `?` → `HelpModal`, the two-column card of sketch
pick C, in [expense/tui/screens/help.py](../expense/tui/screens/help.py); the
palette **removed** (`ENABLE_COMMAND_PALETTE = False`), which also drops the
`^p palette` strip from every footer for free.
What changed beyond the plan: **the item's own description was wrong twice.**
It said no mockup existed *and* that the palette's open work was populating it —
the audit inverted the second. Three things the drawing did not anticipate:
`Binding.tooltip` had to carry the card's fuller wording so the footer could stay
terse from one declaration; `enter` is a **literal no-op on the Manage lists**
(no screen handles `CursorList.Selected` there), so the card had to learn to drop
a key the screen cannot service rather than advertise `⏎ Open` falsely; and `?`
could not be bound on the App — letters bubble up from lists, the same reason
there is no app-level `q` — so it is a per-screen-root mixin. Forms deliberately
have **no** help key. Rationale, and the four rejected shapes:
[decisions.md](decisions.md) "The command palette is removed, not populated".

### Closed 2026-08-16 (delete on next touch)

**Deleted rows — shipped.** The item was "inbox and transactions accept
`--include-deleted` but render no Deleted column". Reviewing it found the
sharper question: the flag exists to feed `restore`, and **the inbox has no
restore route** (removed engine-side 2026-08-14). So the two lists got
different answers — `transactions list` gained a `Deleted` column (rendered
only when the flag is passed, placed last), and `inbox list` **lost the flag
entirely**. Also settled in the same pass: the tag column was labelled `Tags`
on one list and `Hashtags` on the other while cli-spec claimed both said
`Tags` — all four surfaces (both CLI tables, both TUI screens) now say
`Hashtags`, following the engine's vocabulary. Both have [decisions.md](decisions.md)
entries; the second reverses the *label* half of 6.1's sketch pick E, position
untouched.

### Struck as already done (recorded once, then delete on next touch)

Three Phase 8 items were **fixed on 2026-07-10 in commit `fb47937`** and never
ticked — verified at HEAD 2026-08-16:

- *Reports `_render_range_table` hand-rolls the width loop* — it is 22 lines
  and already calls the shared `render_table`, whose `footer=` parameter was
  added in that same commit for this call site. No hand-rolled table loops
  remain outside `_resource.py`.
- *`reconcile complete` inlines the hint-haystack scan* — the duplicated half
  was hoisted to `error_haystack` ([errors.py](../expense/errors.py)), whose
  docstring names both call sites. What remains genuinely differs (different
  anchor, alternates and hint constant), and a shared kwargs predicate would
  trade a readable boolean for a worse one — **struck, not done**.
- *Import reader materializes all rows* — the deferral is already documented
  at the materialization site ([reader.py](../expense/import_/reader.py)),
  with the reason (handle lifetime vs. error paths) and the scale judgement.
  The backlog's `reader.py:61` and its `polish-backlog §5` cross-reference
  were both stale.

Phase 7 struck a **fourth** item from that very same commit (connection errors
→ exit code 6). These three were its neighbours and were missed; that is the
whole reason this section exists rather than a silent tick.

### Dropped as moot (recorded once, then delete on next touch)

Three 2026-07-06 §5 nits died with the engine rework rather than being fixed:
the `reconcile move --json` empty-output nit and the `_validate_source_choice`
Enum nit (both commands/flags were deleted outright in Phase 3), and the
`--include-deleted` item's dependency on the old cache decision (its [UI] half
shipped 2026-08-16, above).
