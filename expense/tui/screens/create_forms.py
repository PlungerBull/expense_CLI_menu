"""Create forms — new hashtag / category / account (Phase 2).

A lightweight bar-cycle form (same look as Log): cycle fields with the input
bar, pick choices from a suggestion list, `ctrl+s` (or enter on the last field)
POSTs. Reached with `n` on the Manage list screens.

New account is bank-only — the engine forbids `is_person` on POST /accounts;
person accounts need the (unshipped) People API.
"""

import io
import uuid

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Footer, Input, Label, Static

from expense.tui.widgets.header import Breadcrumb

_PALETTE = [
    ("#4a90d9", "blue"),
    ("#5ab87a", "green"),
    ("#d96a5a", "red"),
    ("#b07cd9", "purple"),
    ("#d9a93a", "amber"),
    ("#5ab8a0", "teal"),
    ("#d9744a", "orange"),
    ("#8a8f98", "grey"),
]
_CURRENCIES = [("PEN", "PEN"), ("USD", "USD")]


class Field:
    def __init__(self, key, label, kind="text", *, choices=None, required=False, hint=""):
        self.key = key
        self.label = label
        self.kind = kind  # "text" | "choice" | "color"
        self.choices = choices or []
        self.required = required
        self.hint = hint


class BarFormScreen(Screen):
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "submit", "Create"),
        ("up", "suggest(-1)", "↑"),
        ("down", "suggest(1)", "↓"),
        ("ctrl+up", "field(-1)", "Prev field"),
        ("ctrl+down", "field(1)", "Next field"),
    ]
    FIELDS: list = []
    RESOURCE = ""
    NOUN = "item"

    def __init__(self) -> None:
        super().__init__()
        self._current = 0
        self._values: dict = {}
        self._suggestions: list = []
        self._suggest_idx = 0
        self._submitting = False

    @property
    def _f(self) -> Field:
        return self.FIELDS[self._current]

    def compose(self) -> ComposeResult:
        yield Breadcrumb(self.crumb, id="crumb")
        yield Horizontal(Label("", id="field"), Input(id="bar"), id="inputbar")
        yield Static("", id="hint")
        yield Static("", id="suggest")
        yield Static("", id="summary")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_bar()
        self._refresh_view()
        self.query_one("#bar", Input).focus()

    # ---- bar / nav -------------------------------------------------------
    def _refresh_bar(self) -> None:
        f = self._f
        self.query_one("#field", Label).update(f.label)
        bar = self.query_one("#bar", Input)
        bar.value = str(self._values.get(f.key, "")) if f.kind == "text" else ""
        self._recompute(bar.value)

    def _recompute(self, text: str) -> None:
        f = self._f
        needle = text.strip().lower()
        if f.kind in ("choice", "color"):
            self._suggestions = [
                (v, d) for (v, d) in f.choices if needle in d.lower() or needle in v.lower()
            ]
        else:
            self._suggestions = []
        self._suggest_idx = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._f.kind in ("choice", "color"):
            self._recompute(event.value)
            self._refresh_view()

    def action_suggest(self, delta: int) -> None:
        if self._suggestions:
            self._suggest_idx = max(0, min(len(self._suggestions) - 1, self._suggest_idx + delta))
            self._refresh_view()

    def action_field(self, delta: int) -> None:
        self._current = max(0, min(len(self.FIELDS) - 1, self._current + delta))
        self._refresh_bar()
        self._refresh_view()

    def _advance(self) -> None:
        if self._current >= len(self.FIELDS) - 1:
            self.action_submit()
        else:
            self._current += 1
            self._refresh_bar()
            self._refresh_view()

    # ---- commit ----------------------------------------------------------
    def on_input_submitted(self, event: Input.Submitted) -> None:
        f = self._f
        text = self.query_one("#bar", Input).value.strip()
        if f.kind == "text":
            if not text:
                if f.required:
                    self.notify(f"{f.label.title()} is required.", severity="error")
                    return
                self._values.pop(f.key, None)
            else:
                self._values[f.key] = text
            self._advance()
            return
        # choice / color
        if not text and not f.required:
            self._values.pop(f.key, None)
            self._advance()
            return
        picked = self._suggestions[self._suggest_idx] if self._suggestions else None
        if picked is None:
            self.notify(f"Pick a {f.label.lower()}.", severity="error")
            return
        self._values[f.key] = picked[0]
        self._advance()

    # ---- render ----------------------------------------------------------
    def _refresh_view(self) -> None:
        self.query_one("#hint", Static).update(Text(self._f.hint, style="dim"))
        self.query_one("#suggest", Static).update(self._suggest_renderable())
        self.query_one("#summary", Static).update(self._summary_renderable())

    def _suggest_renderable(self) -> RenderableType:
        f = self._f
        if f.kind not in ("choice", "color"):
            return Text("")
        if not self._suggestions:
            return Text("  no match", style="dim")
        rows = []
        for i, (value, display) in enumerate(self._suggestions):
            if f.kind == "color":
                line = Text.assemble(("  ", ""), ("██ ", value), (display, ""))
            else:
                line = Text(f"  {display}")
            if i == self._suggest_idx:
                line.stylize("reverse")
            rows.append(line)
        return Group(*rows)

    def _summary_renderable(self) -> RenderableType:
        t = Table(box=None, pad_edge=False, show_header=False)
        t.add_column("k")
        t.add_column("v")
        for i, f in enumerate(self.FIELDS):
            if f.key in self._values:
                if f.kind == "color":
                    hex_ = self._values[f.key]
                    value = Text.assemble(("██ ", hex_), (self._color_name(hex_), ""))
                else:
                    value = Text(str(self._values[f.key]))
            else:
                value = Text("—" + ("  *" if f.required else "  (optional)"), style="dim")
            label = Text(f.label.lower())
            if i == self._current:
                label.stylize("bold")
            t.add_row(label, value)
        return t

    @staticmethod
    def _color_name(hex_: str) -> str:
        return next((d for (v, d) in _PALETTE if v == hex_), hex_)

    # ---- submit ----------------------------------------------------------
    def action_cancel(self) -> None:
        self.dismiss()

    def action_submit(self) -> None:
        if self._submitting:
            return
        for f in self.FIELDS:
            if f.required and f.key not in self._values:
                self.notify(f"{f.label.title()} is required.", severity="error")
                return
        payload = self._payload()
        self._submitting = True
        self.query_one("#hint", Static).update(Text("Creating…", style="dim"))
        self._submit(payload)

    def _payload(self) -> dict:
        raise NotImplementedError

    @work(thread=True, exclusive=True)
    def _submit(self, payload: dict) -> None:
        from expense import config as config_module
        from expense.cache import refresh_after_write
        from expense.http import ExpenseClient

        cfg = config_module.ensure_loaded()
        try:
            with ExpenseClient(cfg, verbose=self.app._verbose) as client:
                client.post(f"/{self.RESOURCE}", json_body=payload)
                refresh_after_write(
                    client,
                    cfg,
                    no_cache=self.app._no_cache,
                    no_sync_after=False,
                    notice_stream=io.StringIO(),
                )
        except Exception as exc:
            self.app.call_from_thread(self._failed, str(exc))
            return
        self.app.call_from_thread(self._done)

    def _failed(self, message: str) -> None:
        self._submitting = False
        self.notify(message, title="Failed", severity="error")
        self._refresh_view()

    def _done(self) -> None:
        self.notify(f"{self.NOUN.title()} created.")
        self.dismiss()


class NewHashtagScreen(BarFormScreen):
    crumb = ("Manage", "Hashtags", "New")
    RESOURCE = "hashtags"
    NOUN = "hashtag"
    FIELDS = [Field("name", "NAME", required=True, hint="lowercase, no “#” · enter creates")]

    def _payload(self) -> dict:
        return {"id": str(uuid.uuid4()), "name": self._values["name"].lstrip("#")}


class NewCategoryScreen(BarFormScreen):
    crumb = ("Manage", "Categories", "New")
    RESOURCE = "categories"
    NOUN = "category"
    FIELDS = [
        Field("name", "NAME", required=True, hint="enter to save"),
        Field("color", "COLOR", "color", choices=_PALETTE, required=True, hint="pick a swatch"),
    ]

    def _payload(self) -> dict:
        return {
            "id": str(uuid.uuid4()),
            "name": self._values["name"],
            "color": self._values["color"],
        }


class NewAccountScreen(BarFormScreen):
    crumb = ("Manage", "Accounts", "New")
    RESOURCE = "accounts"
    NOUN = "account"
    FIELDS = [
        Field("name", "NAME", required=True, hint="enter to save"),
        Field(
            "currency", "CURRENCY", "choice", choices=_CURRENCIES, required=True, hint="PEN or USD"
        ),
        Field("color", "COLOR", "color", choices=_PALETTE, hint="optional · empty enter to skip"),
    ]

    def _payload(self) -> dict:
        payload = {
            "id": str(uuid.uuid4()),
            "name": self._values["name"],
            "currency_code": self._values["currency"],
        }
        if self._values.get("color"):
            payload["color"] = self._values["color"]
        return payload
