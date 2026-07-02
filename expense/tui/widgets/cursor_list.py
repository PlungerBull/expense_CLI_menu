"""CursorList — a focusable, keyboard-navigable table list with a row cursor.

Reused by every list screen (inbox, transactions, accounts, categories...).
Rows are `(key, cells)` pairs: `key` identifies the row (e.g. a record id) and
is carried on the `Selected` message; `cells` are the column strings. `_build()`
is pure, so formatting is unit-testable without an event loop.
"""

from collections.abc import Iterable, Sequence

from rich import box
from rich.console import RenderableType
from rich.table import Table
from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Static

# A row is (key, cells) or (key, cells, base_style). `key` identifies the row;
# `cells` may be plain strings or Rich renderables (e.g. a colored swatch);
# `base_style` is an optional Rich style applied when the row is not the cursor
# (e.g. "dim" for archived rows).
Row = tuple


class CursorList(Static):
    can_focus = True
    BINDINGS = [
        Binding("down,j", "move(1)", "Navigate"),
        Binding("up,k", "move(-1)", show=False),
        Binding("enter", "select", "Open"),
    ]

    class Selected(Message):
        def __init__(self, key: object, index: int) -> None:
            super().__init__()
            self.key = key
            self.index = index

    class Highlighted(Message):
        """Posted when the row cursor moves (live), carrying the new row's key.
        Lets a parent react as you navigate (e.g. a master→detail two-pane)."""

        def __init__(self, key: object, index: int) -> None:
            super().__init__()
            self.key = key
            self.index = index

    def __init__(
        self,
        headers: Sequence[str],
        rows: Iterable[Row],
        *,
        align_right: Iterable[int] = (),
        empty: str = "(empty)",
    ) -> None:
        super().__init__()
        self._headers = list(headers)
        self._rows: list[Row] = list(rows)
        self._align = set(align_right)
        self._empty = empty
        self._cursor = 0

    def on_mount(self) -> None:
        self._refresh()
        self.focus()

    def set_rows(self, rows: Iterable[Row]) -> None:
        self._rows = list(rows)
        self._cursor = min(self._cursor, max(0, len(self._rows) - 1))
        self._refresh()

    @property
    def cursor_key(self) -> object | None:
        return self._rows[self._cursor][0] if self._rows else None

    def index_of(self, key: object) -> int:
        for i, row in enumerate(self._rows):
            if row[0] == key:
                return i
        return 0

    def set_cursor(self, index: int) -> None:
        if self._rows:
            self._cursor = max(0, min(len(self._rows) - 1, index))
            self._refresh()

    def _refresh(self) -> None:
        self.update(self._build())

    @staticmethod
    def _cell(value: object) -> object:
        # pass Rich renderables (e.g. a Text swatch) through; stringify the rest.
        return value if isinstance(value, (str, Text)) else str(value)

    def _build(self) -> RenderableType:
        if not self._rows:
            return Text("  " + self._empty, style="dim")
        t = Table(box=box.SIMPLE, expand=True, pad_edge=False)
        for i, header in enumerate(self._headers):
            t.add_column(header, justify="right" if i in self._align else "left", no_wrap=True)
        for r, row in enumerate(self._rows):
            cells = row[1]
            base = row[2] if len(row) > 2 else ""
            style = "reverse" if r == self._cursor else base
            t.add_row(*[self._cell(c) for c in cells], style=style)
        return t

    def action_move(self, delta: int) -> None:
        if not self._rows:
            return
        new = max(0, min(len(self._rows) - 1, self._cursor + delta))
        if new != self._cursor:
            self._cursor = new
            self._refresh()
            self.post_message(self.Highlighted(self.cursor_key, self._cursor))

    def action_select(self) -> None:
        if self._rows:
            self.post_message(self.Selected(self._rows[self._cursor][0], self._cursor))
