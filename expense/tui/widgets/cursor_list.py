"""CursorList — a focusable, keyboard-navigable table list with a row cursor.

Reused by every list screen (inbox, transactions, accounts, categories...).
Rows are `(key, cells)` pairs: `key` identifies the row (e.g. a record id) and
is carried on the `Selected` message; `cells` are the column strings. `_build()`
is pure, so formatting is unit-testable without an event loop.
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


class Row(NamedTuple):
    """One list row.

    ``key`` identifies the row (carried on ``Selected``/``Highlighted``);
    ``cells`` are the column values — plain strings or Rich renderables like a
    colored swatch; ``base_style`` is the Rich style applied when the row is not
    the cursor (e.g. ``"dim"`` for archived rows).
    """

    key: object
    cells: Sequence[object]
    base_style: str = ""

    @classmethod
    def coerce(cls, row: "RowInput") -> "Row":
        """Accept a plain ``(key, cells[, base_style])`` tuple — what the pure row
        builders return — or an existing Row; always return a Row."""
        return row if isinstance(row, cls) else cls(*row)


# Row builders return plain tuples; the widget coerces them at its boundary.
RowInput = Row | tuple


class CursorList(Static):
    can_focus = True
    BINDINGS = [
        Binding("down,j", "move(1)", "Navigate"),
        Binding("up,k", "move(-1)", show=False),
        Binding("enter", "select", "Open"),
    ]

    class Selected(Message):
        def __init__(self, control: "CursorList", key: object, index: int) -> None:
            super().__init__()
            self._control = control
            self.key = key
            self.index = index

        @property
        def control(self) -> "CursorList":
            """The list that posted this — handlers on screens with several
            CursorLists must filter by source (backlog 6.2c)."""
            return self._control

    class Highlighted(Message):
        """Posted when the row cursor moves (live), carrying the new row's key.
        Lets a parent react as you navigate (e.g. a master→detail two-pane)."""

        def __init__(self, control: "CursorList", key: object, index: int) -> None:
            super().__init__()
            self._control = control
            self.key = key
            self.index = index

        @property
        def control(self) -> "CursorList":
            """The list that posted this — handlers on screens with several
            CursorLists must filter by source (backlog 6.2c)."""
            return self._control

    def __init__(
        self,
        headers: Sequence[str],
        rows: Iterable[RowInput],
        *,
        align_right: Iterable[int] = (),
        empty: str = "(empty)",
    ) -> None:
        super().__init__()
        self._headers = list(headers)
        self._rows: list[Row] = [Row.coerce(r) for r in rows]
        self._align = set(align_right)
        self._empty = empty
        self._cursor = 0

    def on_mount(self) -> None:
        self._refresh()
        self.focus()

    def set_rows(self, rows: Iterable[RowInput]) -> None:
        self._rows = [Row.coerce(r) for r in rows]
        self._cursor = min(self._cursor, max(0, len(self._rows) - 1))
        self._refresh()

    @property
    def cursor_key(self) -> object | None:
        return self._rows[self._cursor].key if self._rows else None

    def index_of(self, key: object) -> int:
        for i, row in enumerate(self._rows):
            if row.key == key:
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
            style = "reverse" if r == self._cursor else row.base_style
            t.add_row(*[self._cell(c) for c in row.cells], style=style)
        return t

    def action_move(self, delta: int) -> None:
        if not self._rows:
            return
        new = max(0, min(len(self._rows) - 1, self._cursor + delta))
        if new != self._cursor:
            self._cursor = new
            self._refresh()
            self.post_message(self.Highlighted(self, self.cursor_key, self._cursor))

    def action_select(self) -> None:
        if self._rows:
            self.post_message(self.Selected(self, self._rows[self._cursor].key, self._cursor))
