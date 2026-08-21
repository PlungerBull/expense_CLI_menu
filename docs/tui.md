# The TUI — `expense world`

What the Textual app **is**, in present tense. The interactive front door over the
same fetch/write layer the flat commands use; it implements **zero** business logic
(repo thin-wrapper rule). It replaced the questionary `expense menu`, deleted
2026-07-02.

Companions: [cli-spec.md](cli-spec.md) (command surface) ·
[cli-runtime.md](cli-runtime.md) (read/write semantics, which apply to the TUI
unchanged) · [decisions.md](decisions.md) (why the calls below went the way they did) ·
[mockups/](mockups/) (the approval gate for every screen).

Built with **Textual** — Python, by the Rich authors; the direct analog to the Ink
stack Claude Code uses.

---

## 1. Architecture

```
expense/tui/
  app.py            # ExpenseApp(App): screen stack, global bindings, worker helper
  app.tcss          # Textual CSS — layout + the structural ANSI fills (§3)
  theme.py          # the ANSI Theme + the PALETTE constant Rich content styles with
  widgets/
    header.py       # Breadcrumb — slim section header (home banner lives in home.py)
                    #   + rate_alert() — the `!` staleness mark both headers share
    cells.py        # cell renderers: color swatch, sign-colored right-aligned amount_cell
    cursor_list.py  # CURSOR_STYLE (reverse video, app-wide) + CursorList — arrow-key
                    #   list (pickers) + CursorOptionList — the home menu
    checklist.py    # CheckList — multi-select (hashtag picker)
  screens/
    _base.py        # EngineWriteMixin.run_write + SectionScreen (fetch workers, confirm, keymap)
    _form.py        # FormScreen base — fields, validation, bar-cycle plumbing
    help.py         # HelpModal — the `?` card, derived from BINDINGS (§4)
    home.py         # banner + stat cluster + section menu
    outstanding.py  # balances + people ▼/▶ fold + category ▼/▶ tree + totals
    reports.py      # Monthly report — sliding 4-month grid, ▼/▶ hashtag rows
    inbox.py        transactions.py  accounts.py  categories.py  hashtags.py
    reconciliations.py               # full lifecycle
    system.py       # Config / Auth / Activity / Rates screens
    quick_log.py    # the transaction form (log / edit)
    create_forms.py # BarFormScreen + New{Account,Category,Hashtag} small forms
                    #   New account carries a TYPE field (bank/person, prefilled
                    #   bank) that picks POST /accounts vs POST /people
    modals.py       # RecordModal, SnapshotModal, ConfirmModal, PromptModal
```

**The fetch/print split is the anti-duplication guardrail.** Every command that
fetched *and* printed has a pure `fetch_*(cfg, …) -> dict`; the typer command and
the TUI both call it. The TUI imports `fetch_*` — it never reimplements one. Shared
read/format helpers live in [_resource.py](../expense/commands/_resource.py), write
plumbing in [_base.py](../expense/tui/screens/_base.py), form scaffolding in
[_form.py](../expense/tui/screens/_form.py).

**Async / workers.** Textual runs on asyncio; the engine client is synchronous, and
stays that way. It is called inside a Textual worker (`@work(thread=True)`) so the UI
never blocks. Read screens subclass `SectionScreen` and override `fetch()` (runs in
the worker) + `build(data)`; writes go through `EngineWriteMixin.run_write` in its own
worker group — a FIFO queue, one write in flight, and an error drops the queued
remainder ([decisions.md](decisions.md)).

**Invariant: `build()` runs on the UI thread and must never do HTTP.** Where a render
needs resolved names, resolve them in `fetch()` and hand `build()` precomputed cells —
`ActivityScreen` is the worked example (`fetch()` opens one client for the whole page,
returns `{"rows": [...], "by_id": {...}}`).

**Name resolution is live HTTP and fails silently by design.**
`load_account_name_map` / `load_category_name_map` / `load_hashtag_name_map` each open
their own client and page the reference list; on **any** failure they return `{}` and
renderers fall back to 8-char short ids. No toast, no error. If a user ever reports
"my tables show hex ids", the cause is the engine rejecting reference-list reads
(auth/config), never data loss. Every call site must be inside a worker thread.

### The header rate alert

Every header carries a `!` when today has no exchange rate of its own — meaning every
home-currency figure on screen is priced at an older day's rate. Owner decision
2026-08-13; the deliberately-sensitive trigger was chosen over a 2-day grace period,
so it also shows on an ordinary morning before the engine's fetch job has run.

- **No new engine surface.** `GET /exchange-rates` already returns the day you asked
  about (`date`) and the day it actually used (`rate_date`); the whole signal is
  `rate_date < date` — which covers every failure mode (provider down, Mac asleep, job
  crashed, or a rate the engine refused as implausible). `rates_cmd.rate_is_stale`
  applies it; `fetch_rate_staleness` adds the `404` case (no rate at all → stale).
- **App-owned, fetched once per launch.** `ExpenseApp.rate_stale` holds `True` /
  `False` / `None`, filled by one worker on mount. It lives on the app because the
  indicator is in every header and screens come and go: a screen pushed after the fetch
  reads the value itself, one already mounted is repainted (breadcrumbs by query, home
  via its `repaint_header` hook).
- **`None` renders nothing.** Offline, unconfigured, pre-fetch, or an unexpected body
  shape all mean "don't know", and an indicator that fires when it cannot reach the
  engine is reporting on the connection, not on the rate. Warning-colored, not error:
  a carried-forward rate is the engine's designed fallback.
- Guard: [tests/unit/test_rate_alert.py](../tests/unit/test_rate_alert.py).

---

## 2. Screens

Every home-menu entry is wired — no stubs. `_SCREENS` in
[home.py](../expense/tui/screens/home.py) maps id → screen, kept in lockstep by
`test_screens_map_covers_every_wired_menu_entry`.

| Group | Entries |
|---|---|
| **Capture & ledger** | Log a transaction · Inbox · Transactions · Reconciliations |
| **Reports** | Outstanding Amounts · Monthly report |
| **Manage** | Accounts · Categories · Hashtags |
| **System** | Config · Auth & profile · Activity · Rates |

Home is a wordmark line plus a live `net · spent · owed` stat cluster (one dashboard
read on mount/resume, failure-silent), with the menu de-boxed onto the app background.
Aggregates are **nullable** — a group holding an unconvertible row reports `3 unrated`
rather than a partial total ([decisions.md](decisions.md)). Rows with nothing spent are
hidden, on the dashboard, the monthly report and the Outstanding tree alike.

The Monthly report is a sliding **4-month grid** (categories × months, `▼/▶` hashtag
rows, `[`/`]` slide the window) — deliberately not a single-month view, which would
have duplicated Outstanding Amounts.

**Every new screen starts with an HTML mockup in [mockups/](mockups/) for review before
code** — every time, including screens approved before (CLAUDE.md "Mock every screen").

---

## 3. Theming — the terminal supplies every colour

**No literal colors in the TUI, and no authored ones either.** CSS uses `$accent` /
`$secondary` / `$error`; Rich content takes the `PALETTE` constant
([theme.py](../expense/tui/theme.py)). Guarded by
`test_no_literal_color_styles_in_tui`.

Since 2026-08-19 the tokens themselves are **ANSI slots**, not hexes (`ansi_green` is
slot 2 — the terminal fills it in), so the app reads on dark, light, Solarized and
Gruvbox with **no detection at startup**, no light/dark pair and no `NO_COLOR` mode
(the flat CLI honours that variable on its own). A hex in `theme.py` would pin the app
back to one terminal — guarded by `test_theme_is_ansi_slots_not_hexes`. Rationale and
what it cost (the tuned sage-and-rose palette; louder sign colours on a stock profile):
[decisions.md](decisions.md) "The terminal supplies the palette"; picks in
[mockups/expense-world-ansi-palette.html](mockups/expense-world-ansi-palette.html).

**Theme the foreground, never the base surface.** The app runs in ANSI mode
(`ExpenseApp(ansi_color=True)`): the base fill is `ansi_default` — the terminal's *own*
background — set **structurally** in `app.tcss`, not per theme. So there is no seam
against the terminal's window padding. **The rule for any future theme:** recolor the
foreground and semantic spans only (text, accents, sign-colors, selection/diff
highlights) — **never** paint a full-screen or base-surface background. A painted
ground reintroduces the seam *and* breaks any light/dark/auto theme, because one fixed
surface cannot match every terminal. Guard:
`test_tui_theme.py::test_base_fills_are_terminal_transparent`; mockup
[mockups/tui-ansi-transparent-background.html](mockups/tui-ansi-transparent-background.html).
This is how Claude Code keeps a full theme menu while staying seamless.

Three things only rendering revealed, all load-bearing:

- `$surface` / `$panel` generate to **`transparent`** under an ANSI theme, so the
  header rule, the quiet list border and the modal card were invisible or see-through
  → structural rules take `$secondary`, the modal card a literal `ansi_default`.
- **Alpha is dropped** on `ansi_default`, so a modal scrim became an opaque fill that
  *wiped* the screen behind it while every unit test still passed → literal
  `black 60%`, now guarded by `test_modal_scrim_dims_rather_than_wipes`.
- An `ansi=True` theme must ship Textual's whole `variables` block or the app dies at
  startup on `$ansi-background`.
- **`text-style: reverse` does not survive CSS** when foreground and background are
  both `ansi_default` — Textual 8.2.7 drops it in `get_visual_style()`. This is what
  made the home menu's cursor invisible (see below).

**The cursor is reverse video, and it must be applied as a Rich style.** "You are here"
is drawn the same way everywhere: the terminal's own foreground and background, swapped
— colour-free, so it is correct on any ground by construction rather than by detection.
The shared constant is `CURSOR_STYLE` in
[cursor_list.py](../expense/tui/widgets/cursor_list.py); `CursorList` / `CheckList`
apply it to their Rich table rows, and `CursorOptionList` applies it to the finished
strip.

That last one exists because the theme gives the block cursor **no colour of its own**
(`block-cursor-foreground` and `-background` are both `ansi_default`), so all its
contrast comes from `reverse` — and the CSS path drops it. The home menu was the only
list routed through CSS, so it was the only one with an invisible cursor: the
highlighted row rendered `default on default`, byte-identical to its neighbours, and no
test noticed for a day. Reported and fixed 2026-08-20; pick A of
[mockups/expense-world-menu-cursor.html](mockups/expense-world-menu-cursor.html).

**Assert on rendered strips, not on styles.** `get_component_styles` reported
`text_style: reverse` throughout that bug — the style resolved fine and was discarded
later. Only `render_line(y)` shows what the user sees, which is what
`test_tui_menu_cursor.py` checks.

Slot 3 (yellow) is the one slot that fails on white, so the pending role carries
`bold` rather than a colour. Content cards use the **quiet border** treatment
([mockups/expense-world-panelled-dossier.html](mockups/expense-world-panelled-dossier.html));
home's menu stays deliberately boxless.

---

## 4. The keymap contract

Three cross-screen rules. No screen declares them, so no generated key list can find
them — they are hand-written into the `?` card
([help.py](../expense/tui/screens/help.py) `CONVENTIONS`):

- **`r` always refreshes**, everywhere.
- **`y` alone confirms** — scoped to delete / revert / promote, since archive is
  confirm-free (a reversible toggle, not destruction).
- **`⏎` never changes data.** On the Manage lists it is a literal no-op: no screen
  handles `CursorList.Selected` there, and the help card *drops* the row rather than
  advertise `⏎ Open` falsely.

**Standing constraint:** any future rename action on Manage screens ships as `e`,
never `r` — two older mockups showing `r rename` are superseded. Mockup:
[mockups/expense-world-keymap-4.1.html](mockups/expense-world-keymap-4.1.html).

**App-wide keys are `^q` and `?`.** `?` opens `HelpModal`, a two-column card whose
content is **derived** from BINDINGS by walking the screen's and the focused widget's
MRO and keeping only classes declared under `expense.tui` — which is what keeps
Textual's own `home`/`end`/`tab` out without a suppression list. `Binding.tooltip`
carries the card's fuller wording (`Archive / unarchive`) while `description` stays the
terse footer label (`Archive`): one declaration, two audiences. `?` is bound per screen
root via `HelpBindingMixin`, **never on the App** — letters bubble up from lists, the
same reason there is no app-level `q` (it is scoped to Home). **Forms have no help
key** by decision: a focused `Input` swallows printable keys, so `?` would type a
question mark.

**The Textual command palette is removed** (`ENABLE_COMMAND_PALETTE = False`), which
also drops the `^p palette` strip from every footer. `?` is the one discoverability
surface — [decisions.md](decisions.md).

**Mouse is off** (`run(mouse=False)`) — the TUI is keyboard-only. Corollary:
terminal-level scrolling reaches the terminal itself, and Terminal.app will scroll into
scrollback *above* the running app. Launch therefore wipes screen and scrollback
(`CSI 2J 3J H` in `run_world`) so there is nothing to reveal.

---

## 5. Pagination and terminal size

Every `CursorList` / `CheckList` renders one window of **min(20, what fits the
terminal)** rows — the page IS the screenful, so the panel border/subtitle/footer never
clip and no dead scrollbar appears. A resize re-measures
(`SectionScreen.measure_list_rows`, floor 5) and keeps the first visible row.
`DEFAULT_PAGE_ROWS` (20, one copy shared with the CLI) is the cap and the pre-layout
fallback. Page keys: `pgdn`/`.` next, `pgup`/`,` previous — hidden when one page holds
it all.

Transactions / Inbox / Activity / Rates fetch real `limit`/`offset` pages sized to the
window via `PagedListMixin` (`j`/`k` clamp at the fetched edge; a resize refetches with
the offset re-anchored). Full-data screens window locally — Manage, the two
Reconciliations panes splitting the space equally, the recon checklist at fit÷2 items —
where `j`/`k` walk through and cursor-restore lands on its page. Lists are quiet-border
panels: border title carries the screen title, border subtitle the page status
(`rows 21-40 of 133 · page 2 of 7`). Exempt: the Outstanding tree, static tables, the
Monthly grid, System kv-tables. Picks:
[mockups/expense-world-pagination.html](mockups/expense-world-pagination.html),
[mockups/expense-world-adaptive-rows.html](mockups/expense-world-adaptive-rows.html).

**Minimum terminal size: there is no guard, and that is the decision** (2026-08-20).
The app degrades and says nothing; the terminal is the user's to size. Two reference
sizes, both **measured**:

- **80×24 — everything correct.** No truncation anywhere, panel closes, full footer.
  The size the screens were designed at, and the classic terminal default.
- **60×20 — still workable, already lossy.** Every row draws, but columns are
  ellipsised (`R…`, `-1…`). Fine for navigating, poor for reading.

| dimension | measured behaviour |
|---|---|
| w ≥ 80 | no ellipsis in any cell |
| **w ≈ 75** | **truncation begins** — the first cells start eliding |
| w ≈ 50 | title column is a bare `…`, amount `-…`; every row still drawn |
| w ≤ 40 | date goes too — rows of pure ellipsis |
| height | **the panel clips when content exceeds the viewport, so the threshold moves with the page size**: a 4-row page closes down to h=18, a full 8-row page already clips at h=20. Rows are cut off, never reflowed. |
| h ≤ 10 | no data rows at all, while the footer still offers to page through them |

`PAGE_ROWS_FLOOR = 5` floors the *requested page size*, not the viewport — it cannot
make rows fit that do not. Width has **no** floor of any kind. Captures and the four
rejected shapes (launch refusal, notice screen, warning banner, size in the footer):
[mockups/expense-world-min-terminal-size.html](mockups/expense-world-min-terminal-size.html);
rationale: [decisions.md](decisions.md) "A terminal too small is the user's to fix".

---

## 6. Test conventions

- **A pilot test waits on a condition, never on the clock.** Use `wait_for(pilot,
  predicate)` / `wait_for_list` / `wait_for_loaded` in
  [tests/unit/helpers.py](../tests/unit/helpers.py). A **bare** `pilot.pause()` is the
  pump-drain for asserting a *non-event* (an inert key, a confirm that must not fire),
  where no predicate can be written. Timed `pilot.pause(<n>)` is rejected by
  [tests/unit/test_suite_hygiene.py](../tests/unit/test_suite_hygiene.py), which carries
  exactly one documented exemption (the cancelled-worker window in
  `test_tui_reconcile_detail.py`, keyed on the whole source line so editing it re-opens
  the question).
- **Patch `load_*_name_map` at the screen module** (`expense.tui.screens.X.load_…`),
  not at `_resource` — when the test's point is name display. Use the short-id fallback
  when it isn't.
- **`fake_client` (conftest) patches the lazy-import seams only** —
  `expense.http.ExpenseClient` and `expense.config.ensure_loaded`. Assert on
  `client.calls` / `.posts` / `.puts` ordering.
- **`test_command_surface.py` gives no signal when a command disappears.** The Typer
  walker only checks commands it finds. The backstops are the total-count floor and the
  destructive count — adjust them deliberately when adding or removing commands.

**Known, accepted, not worth fixing at this scale:** a screen load may open several
short-lived clients (inbox: 2 fetches + 2 name maps = 4) — harmless on loopback; and
the inbox ready-probe is **unpaged**, fetching every ready item to badge the visible
page. If inbox rows ever number in the thousands, badging from the paged body would be
an engine ask (`ready` is a filter, not a per-row field).
