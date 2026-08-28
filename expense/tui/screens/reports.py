"""Monthly report screen — a sliding four-month grid (categories × months).

Data comes via the shared `reports_cmd.fetch_range` / `build_range_grid`
(the fetch/print split), off the UI thread in a worker. The grid itself is
`MonthGridView`: the same ▼/▶ expand/collapse interaction as Outstanding's
`CategoriesView`, but with one home-currency amount column per month —
expanding a category reveals its hashtag combos across the whole window.
`[`/`]` slide the window one month older/newer (no clamp — future months
just render empty). Mockup: docs/mockups/expense-world-monthly-report.html
(Option A, picked 2026-07-08).
"""

from datetime import date

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import Static

from expense.commands import reports_cmd
from expense.commands._resource import load_hashtag_name_map
from expense.commands.dashboard_cmd import hashtag_label
from expense.tui.screens._base import SectionScreen, screen_fetch_kwargs
from expense.tui.theme import AMOUNT_RULE, PALETTE, Palette
from expense.tui.widgets.cells import aggregate_cell

WINDOW_MONTHS = 4


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """(year, month) shifted by delta months; 1-based months, rolls over years."""
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def _grid_cell(value: object, palette: Palette | None) -> RenderableType:
    """A month cell in one of three states.

    A signed amount; a dim em-dash for a month with no activity; or the
    warning-colored `3 unrated` when there *was* activity the engine could not
    price. The third state used to be indistinguishable from the second, which
    is what `build_range_grid`'s cell dict exists to fix.
    """
    if reports_cmd.cell_is_empty(value):
        return Text(reports_cmd.NO_ACTIVITY_MARK, style="dim")
    assert isinstance(value, dict)
    return aggregate_cell(value.get("cents"), value.get("unconverted"), palette, AMOUNT_RULE)


class MonthGridView(Static):
    """Interactive month grid: `↑↓` move, `→/←` expand/collapse, `enter` toggle.

    The cursor moves over categories; a category with a hashtag breakdown shows
    a `▼/▶` caret and reveals its (indented, dimmed) combo sub-rows across every
    month column when expanded. Collapsed by default — the grid reads like the
    CLI range table until a row is opened. `_build` is pure (no event loop), so
    formatting + expand state are unit-testable directly.
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
        t = Table(box=None, expand=True, pad_edge=False, header_style="dim")
        t.add_column("Category", ratio=1, no_wrap=True)
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
        t.add_row(
            Text("Totals (net)", style="bold"),
            *(_grid_cell(self._grid["net"].get(label), self._palette) for label in labels),
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


class MonthlyReportScreen(SectionScreen):
    """Four months of category spend, ending at `_end` (default: this month).
    Only supplies the window state, the fetch, and the widgets; SectionScreen
    owns the worker/card/loading/error/refresh."""

    crumb = ("Reports", "Monthly report")
    CARD_WIDTH = 92
    # The month window rides the page keys (2026-08-27, mockup
    # expense-world-movement-keys.html option C). `[`/`]` were a one-screen,
    # one-job pair that existed only because this grid had already spent
    # `←`/`→` on expand/collapse. `pgdn`/`pgup` are unbound here — the grid is
    # not a paged list — and they already mean "the next window of data"
    # everywhere else, which is exactly what a month slide is: 4 more months
    # instead of 20 more rows. `pgdn` goes OLDER, matching a newest-first
    # ledger where paging down walks back in time.
    BINDINGS = [
        Binding("pagedown", "older", "Older", key_display="pgdn"),
        Binding("pageup", "newer", "Newer", key_display="pgup"),
    ]

    def __init__(self, end: tuple[int, int] | None = None) -> None:
        super().__init__()
        today = date.today()
        self._end: tuple[int, int] = end or (today.year, today.month)

    def fetch(self) -> dict:
        from expense import config as config_module

        cfg = config_module.ensure_loaded()
        body = reports_cmd.fetch_range(
            cfg,
            from_ym=shift_month(*self._end, -(WINDOW_MONTHS - 1)),
            to_ym=self._end,
            **screen_fetch_kwargs(self.app),
        )
        return {
            "grid": reports_cmd.build_range_grid(body.get("months") or []),
            "names": load_hashtag_name_map(),
        }

    def build(self, data: dict) -> list[Widget]:
        palette = PALETTE
        labels: list[str] = data["grid"]["labels"]
        span = f"{labels[0]} → {labels[-1]}" if labels else "(no months)"
        return [
            Static(Text(f"Monthly report  ·  {span}  (home currency)"), classes="section-title"),
            MonthGridView(data["grid"], data["names"], palette=palette),
            Static(
                Text("amounts are home-currency · — = no activity · unrated = no exchange rate"),
                classes="legend",
            ),
        ]

    async def action_older(self) -> None:
        self._end = shift_month(*self._end, -1)
        await self.action_reload()

    async def action_newer(self) -> None:
        self._end = shift_month(*self._end, 1)
        await self.action_reload()
