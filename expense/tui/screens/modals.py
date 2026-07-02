"""Reusable modal screens."""

from rich import box
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, Static

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


class ConfirmModal(ModalScreen[bool]):
    """Yes/no confirmation. `y`/`enter` confirm, `n`/`esc` cancel. Dismisses with
    the boolean result (use `push_screen(modal, callback)` to act on it)."""

    BINDINGS = [
        ("y,enter", "confirm", "Yes"),
        ("n,escape", "cancel", "No"),
    ]

    def __init__(self, title: str, message: str) -> None:
        super().__init__()
        self._title = title
        self._message = message

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(Text(self._title), classes="modal-title"),
            Static(Text(self._message)),
            Static(Text("[y / enter] confirm    [n / esc] cancel", style="dim")),
            id="modal",
        )
        yield Footer()

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class PromptModal(ModalScreen[str | None]):
    """Single-line text prompt. `enter` submits the value, `esc` cancels (None).
    `password=True` masks input (for the token). Dismisses with the string."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self, title: str, message: str = "", *, value: str = "", password: bool = False
    ) -> None:
        super().__init__()
        self._title = title
        self._message = message
        self._value = value
        self._password = password

    def compose(self) -> ComposeResult:
        rows = [Static(Text(self._title), classes="modal-title")]
        if self._message:
            rows.append(Static(Text(self._message, style="dim")))
        rows.append(Input(value=self._value, password=self._password, id="prompt"))
        rows.append(Static(Text("[enter] save    [esc] cancel", style="dim")))
        yield Vertical(*rows, id="modal")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#prompt", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def action_cancel(self) -> None:
        self.dismiss(None)
