"""FormScreen — the shared bar-cycle form core.

One input bar cycles through a field sequence; a suggestion list under it
offers picks; a summary table mirrors progress; `ctrl+s` (or enter on the
last field) submits via `run_write`. Subclasses supply the field sequence,
labels/hints, suggestion pools, commit handlers, and the submit request:
BarFormScreen (static Field list), QuickAddLogScreen (dynamic sequence,
locked fields, edit mode), NewReconciliationScreen (dynamic sequence).
"""

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Footer, Input, Label, Static

from expense.tui.screens._base import EngineWriteMixin
from expense.tui.widgets.header import Breadcrumb


def form_bindings(submit_desc: str) -> list[tuple[str, str, str]]:
    """The shared bar-form keymap; only the ctrl+s description varies."""
    return [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "submit", submit_desc),
        ("up", "suggest(-1)", "↑"),
        ("down", "suggest(1)", "↓"),
        ("ctrl+up", "field(-1)", "Prev field"),
        ("ctrl+down", "field(1)", "Next field"),
    ]


class FormScreen(EngineWriteMixin, Screen):
    BINDINGS = form_bindings("Create")
    RESOURCE = ""  # engine collection for the default POST submit

    def __init__(self) -> None:
        super().__init__()
        self._current = 0
        self._values: dict = {}
        self._display: dict = {}
        self._suggestions: list = []
        self._suggest_idx = 0
        self._submitting = False
        self._locked: set[str] = set()

    # ---- subclass hooks ----------------------------------------------------
    def _sequence(self) -> list[str]:
        """The ordered field keys — may vary with form state."""
        raise NotImplementedError

    def _label(self, key: str) -> str:
        """The bar label for a field key (e.g. `AMOUNT`)."""
        raise NotImplementedError

    def _hint_for(self, key: str) -> str:
        return ""

    def _required(self) -> tuple[str, ...]:
        return ()

    def _suggests(self, key: str) -> bool:
        """Whether this field drives the suggestion list."""
        return False

    def _bar_value(self, key: str) -> str:
        """The bar prefill when landing on a field."""
        return str(self._values.get(key, "") or "")

    def _recompute(self, text: str) -> None:
        """Rebuild `_suggestions` for the current field from the bar text."""
        self._suggestions = []
        self._suggest_idx = 0

    def _after_mount(self) -> None:
        """Post-mount hook — e.g. kick off entity loading."""

    def _payload(self) -> dict:
        raise NotImplementedError

    def _submit_request(self) -> tuple[str, str, dict, str] | None:
        """(method, path, payload, busy-hint) for the write; None aborts."""
        return ("POST", f"/{self.RESOURCE}", self._payload(), "Creating…")

    def _done(self) -> None:
        """Success callback (UI thread) — toast + dismiss."""
        raise NotImplementedError

    # ---- layout ------------------------------------------------------------
    @property
    def _key(self) -> str:
        seq = self._sequence()
        return seq[min(self._current, len(seq) - 1)]

    def compose(self) -> ComposeResult:
        yield Breadcrumb(self.crumb, id="crumb")
        yield Horizontal(Label("", id="field"), Input(id="bar"), id="inputbar")
        yield Static("", id="hint")
        yield Static("", id="suggest")
        yield Static("", id="summary")
        yield Footer()

    def on_mount(self) -> None:
        self._current = self._first_editable()
        self._refresh_bar()
        self._refresh_view()
        self.query_one("#bar", Input).focus()
        self._after_mount()

    # ---- bar / nav -----------------------------------------------------------
    def _first_editable(self) -> int:
        for i, key in enumerate(self._sequence()):
            if key not in self._locked:
                return i
        return 0

    def _step(self, delta: int) -> int:
        """The next editable field index in `delta`'s direction, skipping locks."""
        seq = self._sequence()
        step = 1 if delta > 0 else -1
        j = self._current
        while 0 <= j + step < len(seq):
            j += step
            if seq[j] not in self._locked:
                return j
        return self._current  # no editable field that way

    def _refresh_bar(self) -> None:
        key = self._key
        self.query_one("#field", Label).update(self._label(key))
        bar = self.query_one("#bar", Input)
        bar.value = self._bar_value(key)
        self._recompute(bar.value)

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._suggests(self._key):
            self._recompute(event.value)
            self._refresh_view()

    def action_suggest(self, delta: int) -> None:
        if self._suggestions:
            self._suggest_idx = max(0, min(len(self._suggestions) - 1, self._suggest_idx + delta))
            self._refresh_view()

    def action_field(self, delta: int) -> None:
        self._current = self._step(delta)
        self._refresh_bar()
        self._refresh_view()

    def _advance(self) -> None:
        if self._current >= len(self._sequence()) - 1:
            self.action_submit()
        else:
            self._current = self._step(1)
            self._refresh_bar()
            self._refresh_view()

    # ---- render --------------------------------------------------------------
    def _refresh_view(self) -> None:
        self.query_one("#hint", Static).update(Text(self._hint_for(self._key), style="dim"))
        self.query_one("#suggest", Static).update(self._suggest_renderable())
        self.query_one("#summary", Static).update(self._summary_renderable())

    def _suggest_renderable(self) -> RenderableType:
        if not self._suggests(self._key):
            return Text("")
        if not self._suggestions:
            return Text("  no matches", style="dim")
        rows = []
        for i, ent in enumerate(self._suggestions):
            extra = f"  {ent[2]}" if len(ent) > 2 else ""
            line = Text(f"  {ent[1]}{extra}")
            if i == self._suggest_idx:
                line.stylize("reverse")
            rows.append(line)
        return Group(*rows)

    def _summary_renderable(self) -> RenderableType:
        seq = self._sequence()
        required = self._required()
        current_key = self._key
        t = Table(box=None, pad_edge=False, show_header=False, expand=False)
        t.add_column("k")
        t.add_column("v")
        for key in seq:
            shown = self._display.get(key)
            locked = key in self._locked
            if locked:
                value = Text(f"{shown or '—'}  read-only", style="dim")
            elif shown:
                value = Text(str(shown))
            else:
                tag = "  *" if key in required else "  (optional)"
                value = Text("—" + tag, style="dim")
            label = Text(self._label(key).lower(), style="dim" if locked else "")
            if key == current_key and not locked:
                label.stylize("bold")
            t.add_row(label, value)
        return t

    # ---- submit ----------------------------------------------------------------
    def action_cancel(self) -> None:
        self.dismiss()

    def action_submit(self) -> None:
        if self._submitting:
            return
        for key in self._required():
            if key not in self._values:
                self.notify(f"{self._label(key).title()} is required.", severity="error")
                return
        request = self._submit_request()
        if request is None:
            return
        method, path, payload, busy = request
        self._submitting = True
        self.query_one("#hint", Static).update(Text(busy, style="dim"))
        self.run_write(
            method, path, json_body=payload, on_success=self._done, on_error=self._failed
        )

    def _failed(self, message: str) -> None:
        self._submitting = False
        self.notify(message, title="Failed", severity="error")
        self._refresh_view()
