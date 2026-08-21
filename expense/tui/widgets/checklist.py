"""CheckList — a focusable two-line transaction list with membership toggles.

Used by the reconciliation working screen: each transaction renders as two lines
(checkbox + title + amount + date, then a dim category · #tags · note line). A
checked row belongs to the batch; `space` toggles it and posts `Toggled(key)`.
In `read_only` mode (completed batch) there's no checkbox and no toggle.

Rows are pure `(key, title, amount_cents, date, sub)` tuples so formatting is
unit-testable without an event loop.

Renders at most `page_size` items — min(20, what fits the pane) since
2026-07-13 (adaptive rows; an item is two physical lines, so the screen passes
`fit ÷ 2` and calls `set_page_size` on resize) — always window mode: the full
batch stays in memory,
the visible window follows the cursor, and `pgdn`/`.` / `pgup`/`,` jump a page.
Membership is window-proof: `_checked` is a key-set over the whole batch, so
`c Complete` counts every checked row across all pages. Page status renders in
the border subtitle (`items 21-40 of 47 · page 2 of 3`, mockup pick B).
"""

from collections.abc import Iterable, Sequence
from typing import NamedTuple

from rich import box
from rich.console import RenderableType
from rich.table import Table
from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Static

from expense.commands._resource import DEFAULT_PAGE_ROWS
from expense.tui.theme import AMOUNT_RULE, PALETTE, Palette
from expense.tui.widgets.cells import amount_cell
from expense.tui.widgets.cursor_list import page_indicator


class Row(NamedTuple):
    """One transaction row. ``key`` identifies it (carried on ``Toggled``); the
    rest are display fields for the two-line render."""

    key: object
    title: object
    amount_cents: object
    date: object
    sub: object

    @classmethod
    def coerce(cls, row: "RowInput") -> "Row":
        """Accept a plain ``(key, title, amount_cents, date, sub)`` tuple — what
        the pure row builders return — or an existing Row; always return a Row."""
        return row if isinstance(row, cls) else cls(*row)


# Row builders return plain tuples; the widget coerces them at its boundary.
RowInput = Row | tuple


class CheckList(Static):
    can_focus = True
    BINDINGS = [
        # Not shown in the footer: "the arrow keys move the cursor" is not worth a
        # footer slot (user, 2026-08-20 — "its obvious and it just occupies space
        # unnecessarily"). The keys are unchanged and the `?` card still lists them,
        # which is where a key that needs explaining belongs.
        Binding("down,j", "move(1)", "Navigate", tooltip="Down", show=False),
        Binding("up,k", "move(-1)", "Up", show=False),
        Binding("space", "toggle", "Toggle"),
        Binding("pagedown,full_stop", "page(1)", "Next", key_display="pgdn/.", tooltip="Next page"),
        Binding("pageup,comma", "page(-1)", "Prev", key_display="pgup/,", tooltip="Previous page"),
    ]

    class Toggled(Message):
        def __init__(self, key: object, checked: bool) -> None:
            super().__init__()
            self.key = key
            self.checked = checked

    def __init__(
        self,
        rows: Iterable[RowInput],
        checked: Sequence[object] = (),
        *,
        read_only: bool = False,
        empty: str = "(no transactions)",
        palette: Palette = PALETTE,  # value object: _build must stay app-less
        page_size: int = DEFAULT_PAGE_ROWS,
    ) -> None:
        super().__init__()
        self._rows: list[Row] = [Row.coerce(r) for r in rows]
        self._checked: set = set(checked)
        self._read_only = read_only
        self._empty = empty
        self._palette = palette
        self._page_size = page_size
        self._cursor = 0

    def on_mount(self) -> None:
        self._refresh()
        if not self._read_only:
            self.focus()

    @property
    def cursor_key(self) -> object | None:
        return self._rows[self._cursor].key if self._rows else None

    @property
    def checked(self) -> set:
        return set(self._checked)

    def set_rows(self, rows: Iterable[Row], checked: Sequence[object]) -> None:
        self._rows = list(rows)
        self._checked = set(checked)
        self._cursor = min(self._cursor, max(0, len(self._rows) - 1))
        self._refresh()

    def set_page_size(self, page_size: int) -> None:
        """Adaptive rows (2026-07-13): the screen re-measures on terminal resize
        and re-slices the window around the cursor. Membership (`_checked`) is a
        key-set over the whole batch, so a re-slice can't drop checks."""
        if page_size < 1 or page_size == self._page_size:
            return
        self._page_size = page_size
        self._refresh()

    @property
    def _window_start(self) -> int:
        return (self._cursor // self._page_size) * self._page_size

    @property
    def page_status(self) -> str | None:
        """The border-subtitle string, or None when everything fits one page."""
        start = self._window_start
        shown = min(self._page_size, len(self._rows) - start)
        return page_indicator(start, shown, len(self._rows), self._page_size, unit="items")

    def _refresh(self) -> None:
        self.border_subtitle = self.page_status or ""
        self.update(self._build())

    def _build(self) -> RenderableType:
        if not self._rows:
            return Text("  " + self._empty, style="dim")
        t = Table(box=box.SIMPLE_HEAD, expand=True, pad_edge=False, show_header=True)
        if not self._read_only:
            t.add_column("", width=3, no_wrap=True)
        t.add_column("Title")
        t.add_column("Amount", justify="right", no_wrap=True)
        t.add_column("Date", justify="right", width=12, no_wrap=True)
        start = self._window_start
        window = self._rows[start : start + self._page_size]
        for i, (key, title, amount, date, sub) in enumerate(window, start=start):
            cursor = i == self._cursor
            amt = amount_cell(amount, self._palette, AMOUNT_RULE)
            line1 = [str(title or "(untitled)"), amt, (date or "")[:10]]
            line2 = [Text(sub or "", style="dim"), "", ""]
            if not self._read_only:
                mark = "[x]" if key in self._checked else "[ ]"
                checked = key in self._checked
                line1 = [Text(mark, style=self._palette.success if checked else "dim"), *line1]
                line2 = ["", *line2]
            t.add_row(*line1, style="reverse" if cursor else "")
            t.add_row(*line2, style="reverse" if cursor else "")
        return t

    def action_move(self, delta: int) -> None:
        if not self._rows:
            return
        self._cursor = max(0, min(len(self._rows) - 1, self._cursor + delta))
        self._refresh()

    def action_page(self, delta: int) -> None:
        if not self._rows:
            return
        self._cursor = max(0, min(len(self._rows) - 1, self._cursor + delta * self._page_size))
        self._refresh()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "page":  # hide the page keys when one page holds it all
            return len(self._rows) > self._page_size
        return True

    def action_toggle(self) -> None:
        if self._read_only or not self._rows:
            return
        key = self.cursor_key
        now_checked = key not in self._checked
        if now_checked:
            self._checked.add(key)
        else:
            self._checked.discard(key)
        self._refresh()
        self.post_message(self.Toggled(key, now_checked))
