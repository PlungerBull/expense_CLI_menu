# Interactive TUI — Implementation Plan

> Historical note (2026-08-06): every mention of the SQLite replica, `ensure_synced`,
> the Sync screen, or cold-start notices below describes machinery deleted with the
> engine's `/sync` — see [decisions.md](decisions.md) "Delete the local replica".
> The phase record is kept as shipped. TUI-specific observations from that deletion
> (what changed in `expense/tui/`, behavior notes, test-infra patterns) are collected
> for the TUI developer in [tui-decache-notes.md](tui-decache-notes.md).
>
> Status: **in progress (Step 10)** — Phases 0–2 shipped (Phase 2 closed 2026-07-08
> with the Monthly report screen); Phase 3 partially delivered early via the 2026-07-02 quality-review backlog §4
> (2026-07-05/06, all eight items closed: keymap contract
> ([mockups/expense-world-keymap-4.1.html](mockups/expense-world-keymap-4.1.html) —
> the `r`/`u`/`y`/`enter` rules plus the full key audit), theme-resolved semantic colors,
> form-label width ([mockups/expense-world-field-width-4.4.html](mockups/expense-world-field-width-4.4.html) —
> fixed at 14 cells, guarded by a test), q scoped to Home, unarchive prompt-free,
> Rates as a history table —
> [mockups/expense-world-rates-form-4.8.html](mockups/expense-world-rates-form-4.8.html),
> whose "parked on an engine endpoint" banner is now spent: `GET /v1/exchange-rates/history`
> shipped and `rates list` with it)
> and §5 (2026-07-06, all six dedup refactors closed: `EngineWriteMixin.run_write` behind
> every TUI write worker, one `FormScreen` base under all three bar-cycle forms, shared
> `fetch_body`/`render_record`/`items_of` and friends in `_resource.py`).
> *(Backlog § references in this doc are to that 2026-07-02 review, fully worked off and
> removed from the live file — last full copy at commit `2d42482`;
> [backlog.md](backlog.md) — renamed from `polish-backlog.md` 2026-08-15 — now carries the merged open-work queue.)*
> Entry command is **`expense world`**. This TUI
> **replaced the questionary `expense menu`**, which was **deleted at roadmap Step 10.X
> (2026-07-02)** — `expense/menu/`, its tests, the Typer command, and the `questionary`
> dep are gone (see §10). Builds a menu-driven, retained-mode terminal
> app on top of the existing engine-integration layer. Mockups: [docs/mockups/](mockups/)
> (the `expense-world-*.html` set). Expand/collapse = interactive `▼/▶` tree with
> arrow-key navigation. Theme = swappable token set, **neutral by default**.
>
> **What's wired (per [expense/tui/screens/home.py](../expense/tui/screens/home.py)):**
> Outstanding Amounts, Monthly report, Log a transaction (quick-add), Inbox,
> Transactions, Reconciliations, Accounts, Categories, Hashtags, Config, Auth & profile,
> and the System reads (Sync · Activity · Rates). **Every menu entry is wired** — the
> last `"soon"` stub (Monthly report) shipped 2026-07-08.

## 1. Goal & shape

A persistent terminal app — `expense world` — that opens to a **header + menu**,
and renders a dedicated **interface per section** (browse, create, edit, confirm),
with arrow-key navigation, an expandable category tree, and contextual key hints.

The flat commands (`expense log`, `expense dashboard`, …) keep working untouched — they
stay the canonical interface. The TUI **replaced** the questionary `expense menu`, which
was deleted at roadmap Step 10.X (2026-07-02) — the two ran in parallel only until the
decision to retire the menu. The TUI is a new *client* of the same data/command layer —
it implements **zero** business logic, per the repo's thin-wrapper rule. The engine stays
the single source of truth.

Built with **Textual** (Python, by the Rich authors — the direct analog to the Ink
stack Claude Code uses).

## 2. Why this is mostly presentation work

The hard, finance-critical layer already exists and is reused as-is:

| Already built (reused) | New (the TUI) |
|---|---|
| Engine HTTP client, idempotency, error envelope (`expense/http.py`) | Textual app shell, screen stack, key bindings |
| Live reads + name maps (`expense/commands/_resource.py`; the SQLite replica this row originally named was deleted 2026-08-06 — [decisions.md](decisions.md) "Delete the local replica") | Header / breadcrumb / keybar widgets |
| Data shaping — the dicts renderers consume | List, tree, chip, and form screens |
| Business rules (engine-side) + 422 envelope | Loading / empty / error states |
| Command implementations & fetch/print split (`expense/commands/`) | Neutral theme token file |
| `format_cents`, hashtag/account/category resolution, ready-predicate | Confirm modals, navigation |

## 3. Architecture

The `expense/tui/` package (which replaced the now-deleted `expense/menu/`):

```
expense/tui/
  app.py            # ExpenseApp(App): screen stack, global bindings, worker helper
  app.tcss          # Textual CSS — layout + NEUTRAL theme tokens
  theme.py          # Palette + resolve_palette(app) — semantic colors, theme-resolved (§4.2)
  widgets/
    header.py       # Breadcrumb — slim section header (home banner lives in home.py)
                    #   + rate_alert() — the `!` staleness mark both headers share (§3.1)
    cells.py        # cell renderers: color swatch, sign-colored right-aligned amount_cell
    cursor_list.py  # CursorList — arrow-key list (home menu, pickers)
    checklist.py    # CheckList — multi-select (hashtag picker)
  screens/
    _base.py        # EngineWriteMixin.run_write + SectionScreen (fetch workers, confirm, keymap)
    _form.py        # FormScreen base — fields, validation, bar-cycle plumbing
    home.py         # banner + section menu
    outstanding.py  # balances + people ▼/▶ FOLD + category ▼/▶ TREE + totals
    reports.py      # Monthly report — sliding 4-month grid, ▼/▶ hashtag rows
    inbox.py        transactions.py  accounts.py  categories.py  hashtags.py
    reconciliations.py               # full lifecycle (reorder retired 2026-08-16)
    system.py       # Config / Auth / Activity / Rates screens
                    #   (Sync went with the local replica, 2026-08-06)
    quick_log.py    # the transaction form (log / edit)
    create_forms.py # BarFormScreen + New{Account,Category,Hashtag} small forms
                    #   New account carries a TYPE field (bank/person, prefilled
                    #   bank) that picks POST /accounts vs /people (§Phase 2)
    modals.py       # RecordModal, SnapshotModal, ConfirmModal, PromptModal
```

**The one enabling refactor — "fetch / print" split.** Some commands fetched *and*
printed in one function; each grew a pure `fetch_*(cfg, …) -> dict`, leaving the typer
command and the TUI both calling it (`reports_cmd` was the last holdout —
`fetch_single_month`/`fetch_range` landed 2026-07-08 with the Monthly report screen).
`--json` mode already proved the data separates cleanly; this just formalized it.
**No logic is duplicated** — the TUI imports `fetch_*`, never reimplements it.

**Async / workers.** Textual runs on asyncio; the engine client is synchronous. We
keep the client as-is and call it inside a Textual worker (`@work(thread=True)`) so
the UI never blocks. The shipped pattern: read screens subclass `SectionScreen`
([_base.py](../expense/tui/screens/_base.py)) and override `fetch()` (runs in the
worker, e.g. calls `reports_cmd.fetch_range(...)`) + `build(data)`; writes go through
`EngineWriteMixin.run_write` in its own worker group.

### 3.1 The header rate alert (2026-08-13)

Every header carries a `!` when today has no exchange rate of its own — meaning every
home-currency figure on screen is priced at an older day's rate. Owner decision
2026-08-13; the deliberately-sensitive trigger was chosen over a 2-day grace period,
so it also shows on an ordinary morning before the engine's fetch job has run.

- **No new engine surface.** `GET /exchange-rates` already returns the day you asked
  about (`date`) and the day it actually used (`rate_date`); the whole signal is
  `rate_date < date`. That one comparison covers every failure mode — provider down,
  Mac asleep, job crashed, or a rate the engine refused as implausible. Contract:
  engine-spec.md "Staleness: `rate_date` is the signal". `rates_cmd.rate_is_stale`
  applies it; `fetch_rate_staleness` adds the `404` case (no rate at all → stale).
- **App-owned, fetched once per launch.** `ExpenseApp.rate_stale` holds `True` /
  `False` / `None`, filled by one worker on mount. It lives on the app because the
  indicator is in every header and screens come and go: a screen pushed after the
  fetch reads the value itself, while one already mounted is repainted (breadcrumbs
  by query, home via its `repaint_header` hook — home builds its own header).
- **`None` renders nothing.** Offline, unconfigured, pre-fetch, or an unexpected body
  shape all mean "don't know", and an indicator that fires when it cannot reach the
  engine is reporting on the connection, not on the rate. Warning-colored, not error:
  a carried-forward rate is the engine's designed fallback.
- Guards: [tests/unit/test_rate_alert.py](../tests/unit/test_rate_alert.py) — the
  comparison, the error handling, both header hosts, and the app wiring end to end.

## 4. Theming — neutral, swappable

All color lives in `theme.tcss` as Textual CSS variables; **no hardcoded colors in
widgets**. Default is a **neutral** palette (greyscale surfaces + one restrained
accent for focus/selection, plus a positive/negative pair for amounts). Retheming
(amber, a brand palette, light mode) is a one-file swap the designer can own. Textual
auto-degrades on `NO_COLOR` / non-truecolor terminals.

Tokens: `$surface $panel $text $text-muted $accent $selection $border $positive $negative`.

**Theming principle — theme the foreground, never the base surface (2026-07-11).**
The app runs in ANSI mode (`ExpenseApp(ansi_color=True)`): the base fill is
`ansi_default` — the terminal's *own* background — set **structurally** in
`app.tcss` (`Screen`, `#menu`), **not** per theme. So there's no seam against the
terminal's window padding and it follows whatever terminal it runs in. **The rule
for every present and future theme:** recolor the **foreground and semantic spans
only** (text, accents, sign-colors, and deliberately-filled highlights like the
selection bar or a future diff/badge span) — **never** paint a full-screen or
base-surface background. A painted ground reintroduces the seam *and* breaks
dark/light/auto themes, because one fixed surface can't match every terminal.

This is exactly how Claude Code keeps a full theme menu (dark / light / ANSI-only /
"auto — match terminal") while staying seamless: the surface is always the
terminal's own; only the **foreground** palette changes with the theme, and "auto"
detects the terminal's background (via the `OSC 11` query / `COLORFGBG`) to pick the
palette that reads on it. Ink apps (like Claude Code) get the transparent surface by
default; Textual paints opaque cells, so we opt in via `ansi_color=True`.

**Current state:** one *dark-tuned* foreground palette → correct on any *dark*
terminal, identical to before on a near-black one, but not legible on a *light*
terminal (the muted/semantic hexes assume a dark ground). The seam work is the
foundation, not the finish: a real **light + auto** theme = add a light-tuned
`Theme` object (widgets already read tokens via `resolve_palette`, so no widget
changes) + terminal-background detection, all on the same `ansi_default` surface —
tracked as the light/`NO_COLOR` item in Phase 3 below. Guard:
`tests/unit/test_tui_theme.py::test_base_fills_are_terminal_transparent`. Decision +
rejected alternatives: [decisions.md](decisions.md); mockup
`mockups/tui-ansi-transparent-background.html`.

**What sits on that ground.** Content cards use the **quiet border** treatment —
picked 2026-07-11 alongside the wrapping-panel layout (L2), on the same transparent
base: [mockups/expense-world-panelled-dossier.html](mockups/expense-world-panelled-dossier.html),
which carries both picks. Home's menu stays deliberately boxless.

## 5. Phased delivery

Estimates assume one dev comfortable with Python; **add ~1 week if new to Textual**.

### Phase 0 — Walking skeleton · **3–5 days** · ✅ shipped
- `expense world` launches the Textual app; neutral theme loads.
- Header banner + **home menu** (real section list), arrow-key nav, footer keybar, quit.
  *(The old hardcoded status line was **removed by decision** at polish-backlog §4.3,
  2026-07-06 — it reflected nothing; the designed local/live variants live on in
  `mockups/expense-world-home-status-4.3.html`. The header was then **redesigned
  2026-07-10** into a single-line wordmark + live `net · spent · owed` stat cluster
  (one dashboard read on mount/resume, failure-silent) with the menu de-boxed onto the
  app background — mockup `mockups/expense-world-home-header.html`. Partially answers the
  §4.3 "useful home header" itch with stats, not engine status. The intermediate
  step — collapsing the original ~4-row header to a single line — is
  `mockups/home-header-singleline.html`, which carries its own forward-pointing
  banner to the Phase 4 sketch that later replaced the stat cluster's failure
  state with `4 UNRATED`.)*
- **One real read view wired to live data: Outstanding Amounts** (start flat, then add
  the tree) via the worker helper, reusing `ensure_synced`.
- **Exit criteria:** launch → navigate the menu → see real current-month data in your
  terminal. De-risks Textual + async + the data-reuse architecture.

### Phase 1 — Read views · **1–2 weeks** · ✅ shipped
> Note: Reports, Activity log, and Exchange rates list screens slipped from Phase 1 to
> Phase 2. Activity log and Exchange rates shipped there (as the System reads); the
> **Monthly report** screen closed Phase 2 on 2026-07-08.
- Apply the fetch/print split to the resources in scope.
- List screens (Textual `DataTable`): **Inbox, Transactions, Accounts, Categories,
  Hashtags (chips), Reports (monthly), Activity log, Exchange rates** — filters,
  pagination, glyph columns, name resolution (all reused).
- **Outstanding Amounts: interactive `▼/▶` tree** with arrow-key navigation (the
  preferred expand/collapse), fed by the existing category→`hashtag_breakdown` data.
  > **People fold (2026-08-16, backlog 6.2 · sketch pick J).** The People panel is a
  > second `▼/▶` fold on the same screen — `PeopleView`, same carets and same keys
  > (`→/←`, `enter`) as the categories tree, so there is one collapse idiom, not two.
  > Settled people (balance **exactly zero in their own currency**) start folded
  > behind `▶ 3 settled`; one keypress names them. They are **folded, never
  > dropped** — the engine returns them deliberately and refuses to filter on a
  > computed balance, so hiding them client-side would make "she paid me back" and
  > "I never recorded the loan" identical. With nobody settled there is nothing to
  > fold, and the widget leaves the focus chain so it never competes with the tree
  > for the arrow keys. `_build()` stays pure — the fold unit-tests without an
  > event loop.
- Record **detail modal** (view one row). Loading / empty / error states; status bar.
- **Exit criteria:** every read surface is browsable in the TUI.

### Phase 2 — Write flows · **1–2 weeks** · ✅ shipped (closed 2026-07-08)
> **Retired 2026-08-16:** the quick-add **transfer sub-flow** (and its To-amount
> auto-sign) was removed — the engine deleted the transfer feature 2026-08-10
> ([client-breaking-changes.md](client-breaking-changes.md)). A move between
> accounts is now two ordinary transactions.
>
> **Shipped:** Log/quick-add + transfer, edit transactions + inbox drafts, create forms
> (account/category/hashtag), the **Manage edit flow** (Option B — see below), full
> Reconciliations screen (assign/complete/revert/delete + account-first browse; the
> reorder shipped here was *retired 2026-08-16* with the engine's de-chaining),
> Config, Auth & profile, the **Sync · Activity · Rates** system-read screens, and the
> **Monthly report** screen (below) — nothing remains before parity.
>
> **Monthly report — shipped 2026-07-08 (mockup Option A).** A sliding **4-month grid**
> (categories × months, home-currency cells, net-only footer) in
> [reports.py](../expense/tui/screens/reports.py), not a single-month view — one month
> would duplicate Outstanding Amounts; why + rejected alternatives in
> [decisions.md](decisions.md). `MonthGridView` reuses the Outstanding tree keymap
> (`↑↓` move, `→/←` expand a category into its hashtag combos, collapsed by default);
> **`[`/`]` slide the window one month older/newer** (no clamp — empty months render
> `—` cells), an addition to the keymap contract scoped to this screen. Data via the
> shared `reports_cmd.fetch_range` + `build_range_grid` (fetch/print split); the flat
> `reports monthly --from/--to` table consumes the same grid merge. Mockup:
> [mockups/expense-world-monthly-report.html](mockups/expense-world-monthly-report.html).
>
> **Manage edit flow — reworked 2026-07-11 (list-only).** The 2026-07-07 record detail
> (Option B, `manage_detail.py`) was **deleted**: it only repeated the list's columns. The
> Accounts/Categories/Hashtags lists are now the whole surface (`ResourceListScreen` in
> `_base.py`): `e` on the cursor row pushes the prefilled edit bar-form (`Edit*Screen` in
> `create_forms.py`, PUT); `n` pushes the create bar-form — on Accounts that form's
first field is **TYPE** (`bank` / `person`, prefilled `bank`), and picking `person`
sends the same three fields to `POST /people` instead of `POST /accounts`
(2026-08-16, backlog 6.2 · sketch pick L; `is_person` is a 422 on both routes, so
the endpoint *is* the flag). The default is what keeps adding an ordinary account
to `n`, `enter`, name…; and because `is_person` is settable only at creation, the
edit form locks TYPE read-only exactly as it already locks `currency`. `a`
archives/unarchives **immediately — no confirm modal**
> (archive is a reversible toggle; a second `a` undoes, and the cursor is preserved on the
> acted-on row across the reload); `enter` is a no-op. **System categories:** `e` is offered
> (engine keys them by `system_key`, so rename/recolor is pipeline-safe — engine-spec
> §Categories), `a` is hidden (`ResourceListScreen.check_action` + `refresh_bindings` on
> cursor move → archive/delete `403` them). Delete is not surfaced (archive-only): the
> engine `409`s deletion of any category with transactions. Rationale + rejected
> alternatives in [decisions.md](decisions.md); chosen sketch:
> [mockups/expense-world-manage-merge.html](mockups/expense-world-manage-merge.html)
> (Alt A minus the confirm; supersedes
> [mockups/expense-world-manage-edit.html](mockups/expense-world-manage-edit.html)).
- **Confirm modal** (one component) for promote / delete / restore /
  complete / revert / sync — reuses idempotency + error envelope. (Archive is
  deliberately **not** confirm-gated — reversible toggle, 2026-07-11.)
- **The transaction form** (Log / Transaction-edit / Draft-edit): required fields,
  signed-amount validation, hashtag multi-select, inline 422 surfacing. (The
  conditional transfer sub-flow was retired 2026-08-16 — see the banner above. The
  **tri-state cleared** field went 2026-08-17 with the engine's deletion of the
  column, `sql/035`. Both edit modes share one field set again as of 2026-08-16:
  Draft-edit offers the same hashtag multi-select as Transaction-edit — the
  resource gate that excluded drafts was the whole of backlog 6.1's TUI half,
  and the tags survive promotion, so a draft tagged here needs no re-tagging.)
- **Small forms** (reuse the form component): account, category, hashtag create ✅ /
  edit ✅ (`e` on the list row, the Manage edit flow above).
- **Reconciliation** create/edit form. *(Reorder — originally an `$EDITOR` shell-out —
  was deleted 2026-08-16: the engine dropped manual ordering, so a batch's position is
  its statement start date. See [backlog.md](backlog.md) Phase 3.)*
- **Config / Auth & profile** forms. Post-write refresh reuses `refresh_after_write`.
- **Exit criteria:** create/edit/act parity with the flat command surface.

### Phase 3 — Polish & hardening · **~1 week** · ◐ slices shipped (backlog §4 2026-07-05/06, §5 2026-07-06)
- Designer's theme tokens dropped in; light/dark; `NO_COLOR` paths.
  *(Semantic colors now theme-resolve via `resolve_palette`/`amount_cell` — §4.2;
  the background is now terminal-transparent (ANSI mode, 2026-07-11 — see §4);
  a true light theme + NO_COLOR palette still open.)*
- Keybinding consistency ✅ (§4.1/§4.5 keymap contract: r always refreshes, y alone
  confirms — scoped to delete/revert/promote since archive is confirm-free (2026-07-11),
  enter never mutates — on the Manage lists it's a literal no-op; **standing constraint:**
  any future rename action on Manage screens ships as `e`, never `r` — two older mockups
  showing `r rename` are superseded), `?` help overlay ⬜, Textual command palette ⬜.
- Adaptive pagination ✅ (2026-07-11, rows adaptive since 2026-07-13): every
  `CursorList`/`CheckList` renders one window of **min(20, what fits the
  terminal)** rows — the page IS the screenful (pick A + cap 20), so the panel
  border/subtitle/footer never clip and no dead scrollbar appears; a resize
  re-measures (`SectionScreen.measure_list_rows`, floor 5) and keeps the first
  visible row. `DEFAULT_PAGE_ROWS` (20, one copy with the CLI) is the cap and
  the pre-layout fallback. Keymap-contract page keys `pgdn`/`.` next and
  `pgup`/`,` previous, hidden when one page holds it all.
  Transactions/Inbox/Activity/Rates fetch real `limit/offset` pages sized to
  the window via `PagedListMixin` (`j`/`k` clamp at the fetched edge; resize
  refetches, offset re-anchored); full-data screens (Manage, the two
  Reconciliations panes splitting the space equally, recon checklist at
  fit÷2 items) window locally (`j`/`k` walk through, cursor-restore lands on
  its page). Lists are quiet-border panels: border title carries the screen
  title, border subtitle the page status (`rows 21-40 of 133 · page 2 of 7`).
  Exempt: Outstanding tree + static tables (static-table pick still open),
  Monthly grid, System kv-tables. Picks:
  [mockups/expense-world-pagination.html](mockups/expense-world-pagination.html),
  [mockups/expense-world-adaptive-rows.html](mockups/expense-world-adaptive-rows.html);
  rationale: [decisions.md](decisions.md) (2026-07-11, amended 2026-07-13).
- Async edge cases (slow net, offline, cold-start notice shown in-app), spinners.
- Skeleton/empty/error states everywhere.
- **Textual pilot tests** for navigation + key flows ◐ (binding-level pilot tests for
  keymap/confirm/status flows landed with §4); existing CLI suite stays green.
- Update `docs/roadmap.md`, `CLAUDE.md`; user-facing TUI notes.
- **Exit criteria:** shippable; feature-complete vs the flat command surface.

### Phase 4 (optional, later) — Live niceties
Auto-refresh / watch mode, search-as-you-type, richer dashboards. (Mouse is
deliberately **off** — the TUI is keyboard-only; see [decisions.md](decisions.md)
"TUI is keyboard-only". Corollary: terminal-level scrolling reaches the
terminal itself, and Terminal.app will scroll into scrollback *above* the
running app — any keypress snaps back. Launch therefore wipes the screen and
scrollback (`CSI 2J 3J H` in `run_world`, picked 2026-07-13) so there is
nothing to reveal; see decisions.md "Launch clears the terminal scrollback".)

## 6. Effort summary

| | Scope | Effort |
|---|---|---|
| **MVP** | Phase 0 + most read views + the transaction form | **~2 weeks** |
| **Complete & polished** | Phases 0–3 | **~6–8 weeks** |

Per-section difficulty: menus & lists *easy*; the tree & the transaction form
*moderate*. *(Reconciliation reorder — the one `$EDITOR` outlier — is gone as of
2026-08-16.)*

## 7. Risks & mitigations

- **Textual learning curve** → start with the skeleton; lean on built-in widgets.
- **Async correctness** → one `run_engine` worker helper; never touch the engine on the
  UI thread.
- **Logic duplication** → the fetch/print split is the guardrail; TUI imports `fetch_*`.
- **Scope creep (live features)** → deferred to Phase 4.
- **Theming churn** → tokens file, neutral default, zero hardcoded colors.

## 8. Definition of done

- Parity checklist vs the flat command surface (every engine endpoint reachable in the TUI).
- Pilot smoke tests + the full existing suite green.
- Degrades gracefully on `NO_COLOR` / non-TTY / tiny terminals.
- **`expense menu` (`expense/menu/`) removed** — done at Step 10.X (2026-07-02): its
  screens, tests, the Typer command, and the now-unused `questionary` dep are all gone.

## 9. Decisions

**Resolved:**

1. **Entry command** — ✅ **`expense world`**. (Wired in [expense/tui/app.py](../expense/tui/app.py) / `__main__.py`.)
2. **Coexistence** — ✅ **The TUI replaced `expense menu`, now deleted** (roadmap Step 10.X,
   2026-07-02). They shipped in parallel only until the menu was retired. The flat
   commands (`expense log`, …) stay permanently as the canonical contract-validator interface.
4. **Reconcile reorder** — ✅ shipped as an `$EDITOR` shell-out for v1, then **superseded
   2026-08-16**: the engine deleted manual ordering, so both the TUI chord and
   `expense/_editor.py` are gone. Batches order by statement start date.

**Still open:**

3. **Neutral theme** — monochrome + single accent, dark default? Designer to finalize the
   `theme.tcss` tokens; plan assumes dark-neutral.
5. **Minimum terminal size** — fallback/refuse below e.g. 80×24?
