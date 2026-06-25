"""Reusable modal screens."""

from rich import box
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Static

from expense.commands._resource import format_field_value


class RecordModal(ModalScreen):
    """Read-only detail view of one record (its raw fields). Reused by every
    list screen's "view item" action. `esc` closes."""

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, title: str, record: dict) -> None:
        super().__init__()
        self._title = title
        self._record = record or {}

    def compose(self) -> ComposeResult:
        t = Table(box=box.SIMPLE, pad_edge=False, show_header=False)
        t.add_column("field", style="dim")
        t.add_column("value")
        for key, value in self._record.items():
            t.add_row(key, format_field_value(key, value))
        yield Vertical(
            Static(Text(self._title), classes="modal-title"),
            Static(t),
            id="modal",
        )
        yield Footer()

    def action_close(self) -> None:
        self.dismiss()
