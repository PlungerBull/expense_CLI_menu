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
    overview.py     # Overview — the Accounts | People band (5 drawn rows each,
                    #   people keep their ▼/▶ settled fold) over the sliding
                    #   4-month grid, ▼/▶ hashtag rows, inflow/outflow/net
    inbox.py        transactions.py  accounts.py  categories.py  hashtags.py
    reconciliations.py               # full lifecycle
    system.py       # Config / Auth / Activity / Rates screens
    quick_log.py    # the transaction / draft EDIT form (`⏎` on a row). Its create
                    #   mode moved to the LOG bar 2026-08-25 — `record` is required now
    log_bar.py      # the LOG bar — what `+` opens. One typed line, a staged batch,
                    #   the named account's ledger below it (AccountPeek, 2026-08-29),
                    #   one save. Parses through expense/quickadd/, routes each row to
                    #   the ledger or the Inbox at stage time; ctrl+s writes the ledger
                    #   rows in ONE POST /transactions/batch (via expense/batch_write.py)
                    #   then each draft to POST /inbox. Saved rows keep a ✓ until the
                    #   next line is staged; a partial failure re-sends only the rest.
    create_forms.py # BarFormScreen + New{Account,Category,Hashtag} small forms
                    #   New account carries a TYPE field (bank/person, prefilled
                    #   bank) that picks POST /accounts vs POST /people
    modals.py       # RecordModal, SnapshotModal, ConfirmModal, PromptModal,
                    #   DiscardStagedModal (the LOG bar's one confirmation)
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
| **Capture & ledger** | Inbox · Transactions · Reconciliations |
| **Reports** | Overview |
| **Manage** | Accounts · Categories · Hashtags |
| **System** | Config · Auth & profile · Activity · Rates |

`Log a transaction` was a menu row until 2026-08-20; it is now **`+`** — see §4.

Home is a wordmark line plus a live `net · spent · owed` stat cluster (one dashboard
read on mount/resume, failure-silent), with the menu de-boxed onto the app background.
**net** is `totals.net_home_cents` (this calendar month's inflow − outflow, signed);
**spent** is `totals.outflow_home_cents` (the same month's outflow, drawn positive);
**owed** nets every person's home-converted balance and is dropped entirely at zero.
Opening balances are excluded engine-side — an `@Opening` seed is where tracking
starts, not money that moved.
Aggregates are **nullable** — a group holding an unconvertible row reports `3 unrated`
rather than a partial total ([decisions.md](decisions.md)). Rows with nothing spent are
hidden, on the dashboard and in the Overview grid alike.

**Overview** is one screen (2026-08-29). A two-panel band — **Accounts** left, **People**
right, each drawing at most `PANEL_ROWS` (5) rows — sits above a sliding **4-month grid**
(categories × months, `▼/▶` hashtag rows, `pgdn`/`pgup` slide the window), which closes
with `inflow` / `outflow` / `net` from the same `build_range_grid` the flat range table
renders. It absorbed Outstanding Amounts: that screen's category tree *was* this grid's
newest column, so the merge deleted the duplicate rather than moving it, and what
Outstanding uniquely held — the balances — became the band.

Four things about the band are deliberate and measured, not stylistic. It is **always
today's balances**, whatever month the window shows — there is no balances-as-of-date
endpoint, and the permanent `balances today` in the title is the whole mitigation. The
panels are drawn **lean** (`box=None`, no header row): boxed they cost 12 lines instead
of 8 and push `net` below the fold at 120×34. And the 5-row cap truncates **drawing
only** — the fetch is untouched, `expense dashboard` still prints every row, and the
Accounts screen is where "all of them" lives. Fits whole at 120×34; **100×31** is the
minimum for the entire report at once. Because `#content` scrolls, the screen's
`pgdn`/`pgup` are `priority=True` — without that the scroll container eats them on any
terminal short enough for the card to overflow.

And **every table on the screen is `expand=False`** (2026-08-29, mockup [expense-world-overview-width.html](mockups/expense-world-overview-width.html), option A): natural width, packed against the left margin, identical at 80 columns and at 200. They used to expand, with `ratio=1` on the grid's label column on top of that, which handed the label every spare cell — on a 200-column terminal that is ~140 blanks between the names and the amounts. The knock-on is the grid cursor: it is a `reverse` row style, so the highlight bar is now content-wide, not pane-wide. That trade was the substance of the choice — decisions.md holds the two rejected options that would have kept the bar full-width.

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

**`+` logs a transaction** — Home, Transactions and Inbox (`LogTransactionMixin` in
[_base.py](../expense/tui/screens/_base.py), splatted into each host's BINDINGS like
`HelpBindingMixin`). It always opens the same capture screen — the **LOG bar**, since
quick-add phase 4 (2026-08-25) — including inside the Inbox: one key, one meaning.
Where a row lands is decided by *the line you typed* and shown in the `goes to` column
before you press `ctrl+s`, never by which screen you were standing on; that is what
keeps this from being the trap of one key writing to two endpoints depending on where
you stand ([todo.md](todo.md), "The TUI cannot create an inbox draft"). Plain `+`,
no modifier — `shift`+`+` is not
bindable at all, and the numpad and main-row keys send the same byte, so one binding
catches both ([decisions.md](decisions.md)).

**The LOG bar's own keys** ([log_bar.py](../expense/tui/screens/log_bar.py)): `↵`
stages the line — or completes the open token, or puts a lifted row back; `↑↓` drive
the completion picker while a token is open and move through staged rows when the bar
is empty; `ctrl+s` writes everything not already written; `ctrl+x` drops the picked
row; `esc` unpicks, then leaves (confirming if rows are staged and unwritten). The bar
always holds focus, which is why no bare letter is a command there and why the screen
has no `?` — a focused `Input` swallows printable keys.

**The legend row** ([log_bar.py](../expense/tui/screens/log_bar.py), 2026-08-29). One
fixed row under the bar carrying the whole grammar and what `↵` does:
`$account · @category · #tag · ±amount · //note · when     ↵ stages the line`. It never
changes — it describes the grammar, not the moment — so nothing below it moves; everything
that *does* change (the amount echo, the resolved date in words, how many names a token
matches, loading/writing) is the `#hint` row above it, which no longer repeats the grammar.
Pick A of
[mockups/expense-world-log-legend-and-picker.html](mockups/expense-world-log-legend-and-picker.html).

**The account peek** ([log_bar.py](../expense/tui/screens/log_bar.py), 2026-08-29). The
moment the typed line names an account, that account's posted ledger fills the room under
the staged list — `AccountPeek`, a quiet-border panel with the same treatment as
`CursorList`, five columns (date, title, amount, category, tags; no account column, every
row names the same one). Three properties are the whole design, and each was a pick:

* **Elastic.** `#peek` is `height: 1fr` and everything above it is `height: auto`, so the
  panel gets exactly the rows the staged list leaves and draws that many; it re-renders on
  its own `Resize`. The empty-state invitation stands down while it is up.
* **The account is the bar's**, never a staged row's — the highlighted candidate while a
  picker is open, nothing at all when the token resolves to nothing.
* **It stays put.** `↵` clears the bar; the panel keeps the last account the bar named.

Read-only: no cursor, no keys, `↑↓` stay with the staged list. One debounced
`GET /transactions?account_id=…` per account, cached for the life of the screen, and a
save invalidates what it wrote to. Mockup:
[mockups/expense-world-log-account-peek.html](mockups/expense-world-log-account-peek.html);
why, with the rejected shapes: [decisions.md](decisions.md).

**The footer never advertises the arrow keys.** `Navigate` is declared `show=False` on
`CursorList`, `CheckList` and `MonthGridView` (user, 2026-08-20 —
*"its obvious and it just occupies space unnecessarily"*). The keys work unchanged and
the `?` card still lists them. `pgdn`/`pgup` paging and `→ ←` expand/collapse **stay** in
the footer: they are not obvious. New bindings inherit this rule — if a key only says
"the cursor moves", it does not get a footer slot.

**One key per job — the vim aliases and the brackets are gone (2026-08-27).** `j k h l`
and `,` `.` were deleted: every one was a second name for a key that was already bound
and already in the footer, so removing them cost no capability and handed `j k h l` back
as *command* letters (a widget alias silently outranks a screen binding, which is what
made them unusable before). `[`/`]` went too — the month window rides `pgdn`/`pgup`,
which were unbound on that screen and already meant "the next window of data": 4 more
months instead of 20 more rows. Both are guarded by
[test_tui_help.py](../tests/unit/test_tui_help.py)
(`test_no_duplicate_movement_key_aliases`, `test_square_brackets_are_not_bound_anywhere`).
Inventory that drove it, with the delete test per key family:
[mockups/expense-world-movement-keys.html](mockups/expense-world-movement-keys.html).

**A screen key that a focused `Input` also claims needs `priority=True`.** Textual
resolves the focused widget's bindings before the screen's, and `Input` binds more
chords than it looks like — `ctrl+x` is `cut`, `ctrl+k`/`ctrl+u`/`ctrl+w` are line
edits, `ctrl+a`/`ctrl+e` are home/end. The LOG bar's `ctrl+x drop row`
([log_bar.py](../expense/tui/screens/log_bar.py)) would otherwise edit the line
instead of dropping the staged row. Plain `↑`/`↓` and `escape` need nothing — `Input`
does not bind them — and `⏎` arrives as `Input.Submitted`, not as a binding at all.

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

Every `CursorList` / `CheckList` renders one window of **min(`PAGE_ROWS_CAP`, what fits
the terminal)** rows — the page IS the screenful, so the panel border/subtitle/footer
never clip and no dead scrollbar appears. A resize re-measures
(`SectionScreen.measure_list_rows`, floor 5) and keeps the first visible row.
`DEFAULT_PAGE_ROWS` (20, one copy shared with the CLI) is the app-wide cap and the
pre-layout fallback everywhere except **Transactions and Inbox, which fill the window**
(2026-08-29): they set `PAGE_ROWS_CAP = ENGINE_PAGE_CAP` (200, the engine's own `limit`
ceiling) and `CARD_WIDTH = None`, so their card spans the full width too — the two
screens you sit in take the terminal you gave them. Every other screen keeps its
20-row cap and its tidy `CARD_WIDTH`. Page keys: `pgdn` next, `pgup` previous — hidden when one page holds it all.
They carry the Overview's month window too (`pgdn` older, `pgup` newer): one
meaning, "the next window of data", whether the window is rows or months.

Transactions / Inbox / Activity / Rates fetch real `limit`/`offset` pages sized to the
window via `PagedListMixin` (`↑`/`↓` clamp at the fetched edge; a resize refetches with
the offset re-anchored). Full-data screens window locally — Manage, the two
Reconciliations panes splitting the space equally, the recon checklist at fit÷2 items —
where `↑`/`↓` walk through and cursor-restore lands on its page. Lists are quiet-border
panels: border title carries the screen title, border subtitle the page status
(`rows 21-40 of 133 · page 2 of 7`). Exempt: the Overview band, static tables, the
month grid, System kv-tables. Picks:
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
| height | **the panel clips when content exceeds the viewport, so the threshold moves with the page size**: a 4-row page closes down to h=18, a full 8-row page already clips at h=20. Rows are cut off, never reflowed. Above the floor the page is measured to fit exactly — `LIST_FRAME_LINES` counts 6 (border 2, header, rule, and the two blank edge lines `box.SIMPLE` draws); it read 4 until 2026-08-29, which overflowed every fitted list by those two lines. |
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
