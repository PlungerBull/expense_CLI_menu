"""Overview — balances today over a sliding four-month grid.

The merge of two screens that overlapped on their biggest block (2026-08-29).
`OutstandingScreen`'s "Categories — spent this month" tree rendered exactly what
this grid's newest column already showed, so the merge **deleted** that tree
rather than moving it. What Outstanding uniquely carried — account and person
balances — became the band on top.

The split the screen is built on:

- **stock** (the band) — what you have *right now*. Always today's figures, even
  when `pgdn` walks the grid back a year: `GET /dashboard` is current-month only
  and there is no balances-as-of-date endpoint. The title says so permanently,
  which is the whole mitigation (owner decision, 2026-08-29).
- **flow** (the grid) — where it went, over four months.

Each band panel is **capped at `PANEL_ROWS`** and the overflow is simply not
drawn — no fold, no "n more". The owner's reasoning: accounts get archived so
the list stays short, and the Accounts screen already shows every one of them.
The cap truncates *rendering only*; nothing is filtered out of the fetch, and
the flat CLI still prints every row.

Panels are drawn **lean** (`box=None`, no header row). Measured against a real
Textual prototype: boxed panels cost 12 lines against 8 and push the grid's
`net` row below the fold on a 120x34 terminal. The names, the three-letter
currency and a right-aligned amount do not need a header to be read, and the
section labels above them already say what each block is.

Every table here is **`expand=False`** — natural width, packed against the left
margin (owner pick, 2026-08-29, option A of the mockup below). They used to be
`expand=True`, and the grid's `Category` column carried `ratio=1` on top of it,
which handed the column every spare cell in the pane: on a 200-column terminal
that stuffed ~140 blanks between the category names and the figures, and the
band did the same without a ratio. Nothing was aligning right on purpose — the
amounts are right-aligned *inside* columns that had been inflated. The content
wants 59 columns (15 for the widest label, 44 for four amounts at `467,189.17`)
and now takes exactly that. The `ratio=1` went with it: Rich only distributes by
ratio when a table expands, so leaving it would have been a dead argument that
reads like a live one.

**The accepted cost:** the grid's cursor is a `reverse` row style, so the
highlight bar is now as wide as the content rather than the pane. Two drawn
alternatives kept it full-width — a fixed label rail with a trailing spacer
column, and a capped container — and both were rejected in favour of the
tighter, smaller change (see decisions.md).

Data comes via the shared `dashboard_cmd.fetch_dashboard` + `reports_cmd.
fetch_range` / `build_range_grid` (the fetch/print split), both off the UI
thread in one worker. Either failing takes the whole screen to the standard
error card — a half-drawn report that looks complete is worse than a retry.

Mockups: docs/mockups/expense-world-reports-merge.html (§12, picked 2026-08-29)
for the merge; docs/mockups/expense-world-overview-width.html (option A, picked
2026-08-29) for the column packing.
"""

from datetime import date

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Static

from expense.commands import dashboard_cmd, reports_cmd
from expense.commands._resource import load_hashtag_name_map, settled_label, split_settled
from expense.commands.dashboard_cmd import hashtag_label
from expense.tui.screens._base import SectionScreen, screen_fetch_kwargs
from expense.tui.theme import AMOUNT_RULE, PALETTE, Palette
from expense.tui.widgets.cells import aggregate_cell, amount_cell

WINDOW_MONTHS = 4

#: Rows a band panel draws before it stops. Display-only: the fetch is
#: untouched and the flat CLI still prints everything. Five is the owner's
#: number (2026-08-29) — enough for a working set, short enough that the band
#: costs 8 lines and the grid keeps its `net` row on a 34-line terminal.
PANEL_ROWS = 5


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """(year, month) shifted by delta months; 1-based months, rolls over years."""
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def _grid_cell(value: object, palette: Palette | None, rule: str = AMOUNT_RULE) -> RenderableType:
    """A month cell in one of three states.

    A signed amount; a dim em-dash for a month with no activity; or the
    warning-colored `3 unrated` when there *was* activity the engine could not
    price. The third state used to be indistinguishable from the second, which
    is what `build_range_grid`'s cell dict exists to fix.

    `rule` exists for the totals rows: the engine returns inflow **and** outflow
    positive, so under the default sign rule a month's spending would render in
    the income colour. Those two rows pass `"plain"`; `net` keeps the default.
    """
    if reports_cmd.cell_is_empty(value):
        return Text(reports_cmd.NO_ACTIVITY_MARK, style="dim")
    assert isinstance(value, dict)
    return aggregate_cell(value.get("cents"), value.get("unconverted"), palette, rule)


def _balances_panel(rows: list[dict], palette: Palette | None = None) -> RenderableType:
    """One band panel — name, currency, right-aligned balance. Lean, capped.

    Balances are each account's **own** currency, not home-converted: the `Cur`
    column is what makes that readable, and converting would invent a number the
    engine does not return for this column.

    Pure (no event loop), so the cap and the lean shape are unit-testable.
    """
    if not rows:
        return Text("  (none)", style="dim")
    t = Table(box=None, pad_edge=False, expand=False, show_header=False)
    t.add_column("name", no_wrap=True)
    t.add_column("cur", no_wrap=True)
    t.add_column("balance", justify="right", no_wrap=True)
    for item in rows[:PANEL_ROWS]:
        t.add_row(
            item.get("name") or "(unnamed)",
            item.get("currency_code") or "?",
            amount_cell(item.get("current_balance_cents"), palette, AMOUNT_RULE),
        )
    return t


class PeopleView(Static):
    """People, with settled ones folded behind `▶ 3 settled`.

    Same three columns as the Accounts panel beside it, so the two read as one
    band; the fold is the grid's fold — same carets, same keys (`→/←`, `enter`).

    A settled person is **folded, never dropped**: the engine returns her on
    purpose and refuses to filter on a computed balance, because "she paid me
    back" and "I never recorded the loan" must not look alike. The count row is
    always drawn, and one keypress shows exactly who. That is a different thing
    from `PANEL_ROWS`, which is a display cap on the outstanding rows and draws
    nothing at all — the Accounts screen is where "all of them" lives.

    With nobody settled there is nothing to fold, so the widget drops out of the
    focus chain and behaves as the plain table it used to be. `_build` is pure —
    collapse is unit-testable without an event loop.
    """

    BINDINGS = [
        Binding("right", "expand", "Expand"),
        Binding("left", "collapse", "Collapse"),
        Binding("enter,space", "toggle", "Expand or collapse", show=False),
    ]

    def __init__(self, people: list[dict], palette: Palette | None = None) -> None:
        super().__init__()
        self._outstanding, self._settled = split_settled(people)
        self._palette = palette
        self._collapsed = True  # settled people start folded away
        # Only foldable when there is something to fold; otherwise stay out of
        # the way of the month grid in the tab order.
        self.can_focus = bool(self._settled)

    def on_mount(self) -> None:
        self._render_tree()

    def on_focus(self) -> None:
        self._render_tree()

    def on_blur(self) -> None:
        self._render_tree()

    def _render_tree(self) -> None:
        self.update(self._build())

    def _row(self, table: Table, person: dict, *, indent: str = "", style: str = "") -> None:
        table.add_row(
            indent + (person.get("name") or "(unnamed)"),
            person.get("currency_code") or "?",
            amount_cell(person.get("current_balance_cents"), self._palette, AMOUNT_RULE),
            style=style,
        )

    def _build(self) -> RenderableType:
        if not self._outstanding and not self._settled:
            return Text("  (none)", style="dim")
        t = Table(box=None, pad_edge=False, expand=False, show_header=False)
        t.add_column("name", no_wrap=True)
        t.add_column("cur", no_wrap=True)
        t.add_column("balance", justify="right", no_wrap=True)
        for person in self._outstanding[:PANEL_ROWS]:
            self._row(t, person)
        if self._settled:
            caret = "▶ " if self._collapsed else "▼ "
            label = settled_label(len(self._settled)).removeprefix("▸ ")
            t.add_row(caret + label, "", "", style="reverse" if self.has_focus else "dim")
            if not self._collapsed:
                # Deliberately uncapped: the fold's whole promise is that one
                # keypress shows *exactly who*, and a capped expansion would
                # make the count row point at a list it does not fully open.
                for person in self._settled:
                    self._row(t, person, indent="   ", style="dim")
        return t

    def action_expand(self) -> None:
        self._collapsed = False
        self._render_tree()

    def action_collapse(self) -> None:
        self._collapsed = True
        self._render_tree()

    def action_toggle(self) -> None:
        self._collapsed = not self._collapsed
        self._render_tree()


class MonthGridView(Static):
    """Interactive month grid: `↑↓` move, `→/←` expand/collapse, `enter` toggle.

    The cursor moves over categories; a category with a hashtag breakdown shows
    a `▼/▶` caret and reveals its (indented, dimmed) combo sub-rows across every
    month column when expanded. Collapsed by default — the grid reads like the
    CLI range table until a row is opened. `_build` is pure (no event loop), so
    formatting + expand state are unit-testable directly.

    Under the categories sit the three `TOTALS_KEYS` rows. They were Outstanding
    Amounts' totals block until the merge; the figures were always in the same
    range payload, so drawing them costs no extra call.
    """

    can_focus = True
    BINDINGS = [
        # Not shown in the footer: "the arrow keys move the cursor" is not worth a
        # footer slot (user, 2026-08-20 — "its obvious and it just occupies space
        # unnecessarily"). The keys are unchanged and the `?` card still lists them,
        # which is where a key that needs explaining belongs.
        Binding("down", "move(1)", "Navigate", tooltip="Down", show=False),
        Binding("up", "move(-1)", "Up", show=False),
        Binding("right", "expand", "Expand"),
        Binding("left", "collapse", "Collapse"),
        Binding("enter,space", "toggle", "Expand or collapse", show=False),
    ]

    def __init__(
        self,
        grid: dict,
        name_map: dict[str, str],
        palette: Palette | None = None,
    ) -> None:
        super().__init__()
        self._grid = grid
        self._name_map = name_map
        self._palette = palette
        self._expanded: set[int] = set()
        self._cursor = 0

    def on_mount(self) -> None:
        self._render_grid()
        self.focus()

    def _render_grid(self) -> None:
        self.update(self._build())

    def _build(self) -> RenderableType:
        labels: list[str] = self._grid["labels"]
        rows: list[dict] = self._grid["rows"]
        t = Table(box=None, expand=False, pad_edge=False, header_style="dim")
        t.add_column("Category", no_wrap=True)
        for label in labels:
            t.add_column(label, justify="right", no_wrap=True)
        if not rows:
            t.add_row(Text("(no activity in this window)", style="dim"), *[""] * len(labels))
        for i, row in enumerate(rows):
            kids = bool(row["breakdown"])
            caret = ("▼ " if i in self._expanded else "▶ ") if kids else "  "
            row_style = "reverse" if i == self._cursor else ""
            t.add_row(
                caret + (row["name"] or "(unnamed)"),
                *(_grid_cell(row["cells"].get(label), self._palette) for label in labels),
                style=row_style,
            )
            if kids and i in self._expanded:
                for sub in row["breakdown"]:
                    t.add_row(
                        "    " + hashtag_label(sub["hashtag_ids"], self._name_map),
                        *(_grid_cell(sub["cells"].get(label), self._palette) for label in labels),
                        style="dim",
                    )
        t.add_section()
        totals: dict[str, dict] = self._grid["totals"]
        for key in reports_cmd.TOTALS_KEYS:
            signed = key == "net"
            t.add_row(
                Text(key, style="bold" if signed else "dim"),
                *(
                    _grid_cell(
                        totals[key].get(label),
                        self._palette,
                        AMOUNT_RULE if signed else "plain",
                    )
                    for label in labels
                ),
            )
        return t

    def action_move(self, delta: int) -> None:
        rows = self._grid["rows"]
        if not rows:
            return
        self._cursor = max(0, min(len(rows) - 1, self._cursor + delta))
        self._render_grid()

    def action_expand(self) -> None:
        self._expanded.add(self._cursor)
        self._render_grid()

    def action_collapse(self) -> None:
        self._expanded.discard(self._cursor)
        self._render_grid()

    def action_toggle(self) -> None:
        self._expanded.symmetric_difference_update({self._cursor})
        self._render_grid()


class OverviewScreen(SectionScreen):
    """Balances today over four months of category spend, ending at `_end`.

    Only supplies the window state, the fetch, and the widgets; SectionScreen
    owns the worker/card/loading/error/refresh.
    """

    crumb = ("Reports", "Overview")
    # Fill the terminal: the band is two panels wide and the grid carries four
    # month columns beside them. The old caps (64 on Outstanding, 92 here) were
    # sized for one column of figures.
    CARD_WIDTH = None
    # The month window rides the page keys (2026-08-27, mockup
    # expense-world-movement-keys.html option C). `[`/`]` were a one-screen,
    # one-job pair that existed only because this grid had already spent
    # `←`/`→` on expand/collapse. `pgdn`/`pgup` are unbound here — the grid is
    # not a paged list — and they already mean "the next window of data"
    # everywhere else, which is exactly what a month slide is: 4 more months
    # instead of 20 more rows. `pgdn` goes OLDER, matching a newest-first
    # ledger where paging down walks back in time. The band does NOT move with
    # them — it is today's balances whatever the window says.
    #
    # `priority=True` is load-bearing and new with the merge: `#content` is a
    # `VerticalScroll`, and once the band made the card taller than a short
    # terminal, the scroll container started *handling* pgdn/pgup itself — so
    # the keys scrolled the card by a page instead of sliding the window, and
    # silently, on exactly the terminals where the card overflows. A priority
    # binding is checked before the focused widget and its ancestors, which is
    # the behaviour the 2026-08-27 decision assumed these keys already had.
    BINDINGS = [
        Binding("pagedown", "older", "Older", key_display="pgdn", priority=True),
        Binding("pageup", "newer", "Newer", key_display="pgup", priority=True),
    ]

    def __init__(self, end: tuple[int, int] | None = None) -> None:
        super().__init__()
        today = date.today()
        self._end: tuple[int, int] = end or (today.year, today.month)

    def fetch(self) -> dict:
        from expense import config as config_module

        cfg = config_module.ensure_loaded()
        kwargs = screen_fetch_kwargs(self.app)
        # Two *failable* reads in one worker — the first screen to do so.
        # Sequential and unguarded on purpose: either raising takes the whole
        # screen to the error card, because a report missing half of itself
        # still looks like a report (owner decision, 2026-08-29). The third
        # call below (`load_hashtag_name_map`) cannot fail the screen — it
        # swallows everything into `{}` by design and degrades to short ids.
        # Dashboard first: it is the cheaper call and its failure (no config,
        # engine down) is the more diagnostic one to surface.
        dashboard = dashboard_cmd.fetch_dashboard(cfg, **kwargs)
        body = reports_cmd.fetch_range(
            cfg,
            from_ym=shift_month(*self._end, -(WINDOW_MONTHS - 1)),
            to_ym=self._end,
            **kwargs,
        )
        return {
            "dashboard": dashboard,
            "grid": reports_cmd.build_range_grid(body.get("months") or []),
            # name map resolved worker-side — a full-table read on the render
            # path blocked first paint (backlog 6.5c)
            "names": load_hashtag_name_map(),
        }

    def build(self, data: dict) -> list[Widget]:
        palette = PALETTE
        dashboard: dict = data["dashboard"]
        labels: list[str] = data["grid"]["labels"]
        span = f"{labels[0]} → {labels[-1]}" if labels else "(no months)"
        people = dashboard.get("people") or []

        left: list[Widget] = [
            Static(Text("Accounts"), classes="sect"),
            Static(_balances_panel(dashboard.get("bank_accounts") or [], palette)),
        ]
        # People only earn their half when there are any — the panel would
        # otherwise spend a column saying "(none)" (carried over from the
        # Outstanding screen, which drew People conditionally too).
        right: list[Widget] = (
            [Static(Text("People"), classes="sect"), PeopleView(people, palette)] if people else []
        )

        return [
            Static(
                Text(f"Overview  ·  balances today  ·  flow {span}"),
                classes="section-title",
            ),
            Horizontal(
                Vertical(*left, id="band-left"),
                Vertical(*right, id="band-right"),
                id="band",
            ),
            Static(Text("Spent by category"), classes="sect"),
            MonthGridView(data["grid"], data["names"], palette=palette),
            Static(
                # The band and the grid are in different currencies and the
                # legend has to say so: balances are each account's own
                # (there is a `Cur` column), grid cells are home-converted.
                Text(
                    "grid is home-currency · balances are each account's own · "
                    "— = no activity · unrated = no exchange rate"
                ),
                classes="legend",
            ),
        ]

    async def action_older(self) -> None:
        self._end = shift_month(*self._end, -1)
        await self.action_reload()

    async def action_newer(self) -> None:
        self._end = shift_month(*self._end, 1)
        await self.action_reload()
