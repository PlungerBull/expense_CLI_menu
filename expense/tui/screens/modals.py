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


class SnapshotModal(ModalScreen):
    """Before/after detail for one activity-log entry. Renders the union of the
    two snapshots' fields as a 3-column table (field · before · after), bolding
    the rows that changed. `esc` closes.

    A CREATED entry has no before; a DELETED entry has no after — the missing
    side shows blanks, which reads correctly (fields appeared / disappeared).
    """

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, title: str, before: dict | None, after: dict | None) -> None:
        super().__init__()
        self._title = title
        self._before = before or {}
        self._after = after or {}

    def compose(self) -> ComposeResult:
        before, after = self._before, self._after
        keys = list(dict.fromkeys([*before.keys(), *after.keys()]))
        t = Table(box=box.SIMPLE, pad_edge=False)
        t.add_column("field", style="dim")
        t.add_column("before")
        t.add_column("after")
        for key in keys:
            b_present, a_present = key in before, key in after
            changed = (not b_present) or (not a_present) or before[key] != after[key]
            b_cell = format_field_value(key, before[key]) if b_present else Text("—", style="dim")
            a_cell = format_field_value(key, after[key]) if a_present else Text("—", style="dim")
            if changed:
                a_cell = Text(str(a_cell), style="bold")
            t.add_row(key, b_cell, a_cell)
        yield Vertical(
            Static(Text(self._title), classes="modal-title"),
            Static(t),
            id="modal",
        )
        yield Footer()

    def action_close(self) -> None:
        self.dismiss()


class ConfirmModal(ModalScreen[bool]):
    """Yes/no confirmation. Only `y` confirms; `enter`/`n`/`esc` cancel — enter is
    the safe default so a reflexive keypress can never apply a write. Dismisses
    with the boolean result (use `push_screen(modal, callback)` to act on it)."""

    BINDINGS = [
        ("y", "confirm", "Yes"),
        ("n,escape,enter", "cancel", "No"),
    ]

    def __init__(self, title: str, message: str) -> None:
        super().__init__()
        self._title = title
        self._message = message

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(Text(self._title), classes="modal-title"),
            Static(Text(self._message)),
            Static(Text("[y] confirm    [enter / n / esc] cancel", style="dim")),
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


class DiscardStagedModal(ModalScreen[str]):
    """`esc` with rows staged — the one confirmation on the LOG bar.

    `d` discards, `enter` (and `esc`) keep editing: the safe answer is the
    reflexive one, the same call `ConfirmModal` makes. It is **not** a y/n card,
    because "yes" to "5 rows are staged and not written" reads both ways.

    `ctrl+s save first` is the third answer, live since phase 4 shipped the save
    it names. It writes the rows and then leaves — you pressed `esc`, so the
    intent was to go — but only if every row lands; a failed save keeps you on
    the screen where the error is readable.

    Returns the answer by name rather than a bool: three outcomes do not fit
    one, and `"keep"`/`"discard"`/`"save"` read at the call site.
    """

    BINDINGS = [
        ("d", "discard", "Discard"),
        ("ctrl+s", "save_first", "Save first"),
        ("enter,escape", "keep", "Keep editing"),
    ]

    def __init__(self, count: int) -> None:
        super().__init__()
        self._count = count

    def compose(self) -> ComposeResult:
        rows = "row is" if self._count == 1 else "rows are"
        yield Vertical(
            Static(
                Text(f"{self._count} {rows} staged and not written.", style="bold"),
                classes="modal-title",
            ),
            Static(Text("[enter] keep editing    [d] discard    [^s] save first", style="dim")),
            id="modal",
        )
        yield Footer()

    def action_discard(self) -> None:
        self.dismiss("discard")

    def action_save_first(self) -> None:
        self.dismiss("save")

    def action_keep(self) -> None:
        self.dismiss("keep")
