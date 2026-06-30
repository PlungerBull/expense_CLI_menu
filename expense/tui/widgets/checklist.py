"""CheckList — a focusable two-line transaction list with membership toggles.

Used by the reconciliation working screen: each transaction renders as two lines
(checkbox + title + amount + date, then a dim category · #tags · note line). A
checked row belongs to the batch; `space` toggles it and posts `Toggled(key)`.
In `read_only` mode (completed batch) there's no checkbox and no toggle.

Rows are pure `(key, title, amount_cents, date, sub)` tuples so formatting is
unit-testable without an event loop.
"""

from collections.abc import Iterable, Sequence

from rich import box
from rich.console import RenderableType
from rich.table import Table
from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Static

from expense.commands._resource import format_cents

Row = tuple  # (key, title, amount_cents, date, sub)


class CheckList(Static):
    can_focus = True
    BINDINGS = [
        Binding("down,j", "move(1)", "Navigate"),
        Binding("up,k", "move(-1)", show=False),
        Binding("space", "toggle", "Toggle"),
    ]

    class Toggled(Message):
        def __init__(self, key: object, checked: bool) -> None:
            super().__init__()
            self.key = key
            self.checked = checked

    def __init__(
        self,
        rows: Iterable[Row],
        checked: Sequence[object] = (),
        *,
        read_only: bool = False,
        empty: str = "(no transactions)",
    ) -> None:
        super().__init__()
        self._rows: list[Row] = list(rows)
        self._checked: set = set(checked)
        self._read_only = read_only
        self._empty = empty
        self._cursor = 0

    def on_mount(self) -> None:
        self._refresh()
        if not self._read_only:
            self.focus()

    @property
    def cursor_key(self) -> object | None:
        return self._rows[self._cursor][0] if self._rows else None

    @property
    def checked(self) -> set:
        return set(self._checked)

    def set_rows(self, rows: Iterable[Row], checked: Sequence[object]) -> None:
        self._rows = list(rows)
        self._checked = set(checked)
        self._cursor = min(self._cursor, max(0, len(self._rows) - 1))
        self._refresh()

    def _refresh(self) -> None:
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
        for i, (key, title, amount, date, sub) in enumerate(self._rows):
            cursor = i == self._cursor
            amt = Text(
                format_cents(amount),
                style="" if amount is None else ("green" if amount >= 0 else "red"),
            )
            line1 = [str(title or "(untitled)"), amt, (date or "")[:10]]
            line2 = [Text(sub or "", style="dim"), "", ""]
            if not self._read_only:
                mark = "[x]" if key in self._checked else "[ ]"
                line1 = [Text(mark, style="green" if key in self._checked else "dim"), *line1]
                line2 = ["", *line2]
            t.add_row(*line1, style="reverse" if cursor else "")
            t.add_row(*line2, style="reverse" if cursor else "")
        return t

    def action_move(self, delta: int) -> None:
        if not self._rows:
            return
        self._cursor = max(0, min(len(self._rows) - 1, self._cursor + delta))
        self._refresh()

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
