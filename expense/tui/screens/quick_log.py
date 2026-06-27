"""Log a transaction — quick-add bar (Phase 2, replaces the Select form).

One input bar cycles through fields; a summary fills below as you go. Entity
fields (account/category/hashtags) show a live-filtered suggestion list — you
can only *pick existing* entities, never create them mid-entry.

Flow: Date (pre-filled today) › Title › Amount › Account › Category › Hashtags
(opt, multi) › Note (opt). `enter` saves & advances; `ctrl+↑/↓` jump between
fields to re-edit; `↑/↓` move the suggestion highlight; `ctrl+s` creates once
the four required fields are set. Sign is explicit (− expense / + income);
currency is derived from the account. Transfers are a future mode.
"""

import io
import uuid
from datetime import date as date_cls
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Footer, Input, Label, Static

from expense.commands import accounts_cmd, categories_cmd, hashtags_cmd
from expense.commands._resource import format_cents
from expense.dates import to_canonical_aware
from expense.tui.widgets.header import Breadcrumb

# (key, label)
_FIELDS = [
    ("date", "DATE"),
    ("title", "TITLE"),
    ("amount", "AMOUNT"),
    ("account", "ACCOUNT"),
    ("category", "CATEGORY"),
    ("hashtags", "HASHTAGS"),
    ("note", "NOTE"),
]
_ENTITY = {"account", "category", "hashtags"}
_REQUIRED = ("title", "amount", "account", "category")
_HINTS = {
    "date": "YYYY-MM-DD · enter to accept today, or type a date",
    "title": "free text · enter to save",
    "amount": "signed decimal · − expense / + income · in the account's currency",
    "account": "pick an existing account · ↑↓ highlight · enter select",
    "category": "pick an existing category · ↑↓ highlight · enter select",
    "hashtags": "pick existing tags · enter adds & stays · empty enter moves on",
    "note": "optional · enter to save · empty enter to skip",
}


def parse_amount(text: str) -> int | None:
    """`-99.92` → -9992 cents. None if unparseable. Sign is explicit."""
    text = text.strip().replace(",", "")
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return int((value * 100).to_integral_value(rounding=ROUND_HALF_UP))


def amount_to_text(cents: int) -> str:
    """Cents → an editable decimal string (no grouping): -9992 → '-99.92'."""
    return str(Decimal(cents) / 100)


class QuickAddLogScreen(Screen):
    crumb = ("Capture & ledger", "Log a transaction")
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "submit", "Create"),
        ("up", "suggest(-1)", "↑"),
        ("down", "suggest(1)", "↓"),
        ("ctrl+up", "field(-1)", "Prev field"),
        ("ctrl+down", "field(1)", "Next field"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._current = 0
        self._values: dict = {"date": date_cls.today().isoformat()}
        self._display: dict = {"date": self._values["date"]}
        self._accounts: list = []  # (id, name, currency)
        self._categories: list = []  # (id, name)
        self._hashtags: list = []  # (id, name)
        self._suggestions: list = []
        self._suggest_idx = 0

    # ---- layout ----------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Breadcrumb(self.crumb, id="crumb")
        yield Horizontal(Label("DATE", id="field"), Input(id="bar"), id="inputbar")
        yield Static("", id="hint")
        yield Static("", id="suggest")
        yield Static("", id="summary")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_bar()
        self._refresh_view()
        self.query_one("#bar", Input).focus()
        self._load_entities()

    @work(thread=True)
    def _load_entities(self) -> None:
        from expense import config as config_module

        cfg = config_module.ensure_loaded()
        kw = dict(
            no_cache=self.app._no_cache,
            verbose=self.app._verbose,
            cold_start_notice=False,
            notice_stream=io.StringIO(),
        )
        accts = _items(accounts_cmd.fetch_accounts(cfg, include_people=True, **kw))
        cats = _items(categories_cmd.fetch_categories(cfg, **kw))
        tags = _items(hashtags_cmd.fetch_hashtags(cfg, **kw))
        accounts = [
            (a["id"], a.get("name") or "(unnamed)", a.get("currency_code") or "?")
            for a in accts
            if a.get("id")
        ]
        categories = [
            (c["id"], c.get("name") or "(unnamed)")
            for c in cats
            if c.get("id") and not c.get("is_system")
        ]
        hashtags = [(t["id"], t.get("name") or "(unnamed)") for t in tags if t.get("id")]
        self.app.call_from_thread(self._set_entities, accounts, categories, hashtags)

    def _set_entities(self, accounts: list, categories: list, hashtags: list) -> None:
        self._accounts, self._categories, self._hashtags = accounts, categories, hashtags
        self._recompute_suggestions(self.query_one("#bar", Input).value)
        self._refresh_view()

    # ---- field state -----------------------------------------------------
    @property
    def _key(self) -> str:
        return _FIELDS[self._current][0]

    def _refresh_bar(self) -> None:
        key = self._key
        self.query_one("#field", Label).update(_FIELDS[self._current][1])
        bar = self.query_one("#bar", Input)
        if key == "amount" and "amount" in self._values:
            bar.value = amount_to_text(self._values["amount"])
        elif key in ("date", "title", "note"):
            bar.value = str(self._values.get(key, "") or "")
        else:  # entity fields re-pick from scratch
            bar.value = ""
        self._recompute_suggestions(bar.value)

    def action_field(self, delta: int) -> None:
        self._current = max(0, min(len(_FIELDS) - 1, self._current + delta))
        self._refresh_bar()
        self._refresh_view()

    def action_suggest(self, delta: int) -> None:
        if self._suggestions:
            self._suggest_idx = max(0, min(len(self._suggestions) - 1, self._suggest_idx + delta))
            self._refresh_view()

    # ---- suggestions -----------------------------------------------------
    def _recompute_suggestions(self, text: str) -> None:
        key = self._key
        needle = text.strip().lower()
        if key == "account":
            pool = [(i, n, c) for (i, n, c) in self._accounts if needle in n.lower()]
        elif key == "category":
            pool = [(i, n) for (i, n) in self._categories if needle in n.lower()]
        elif key == "hashtags":
            chosen = set(self._values.get("hashtags", []))
            pool = [(i, n) for (i, n) in self._hashtags if needle in n.lower() and i not in chosen]
        else:
            pool = []
        self._suggestions = pool
        self._suggest_idx = 0

    def _picked(self):
        return self._suggestions[self._suggest_idx] if self._suggestions else None

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._key in _ENTITY:
            self._recompute_suggestions(event.value)
            self._refresh_view()

    # ---- commit ----------------------------------------------------------
    def on_input_submitted(self, event: Input.Submitted) -> None:
        key = self._key
        text = self.query_one("#bar", Input).value.strip()

        if key == "date":
            self._values["date"] = text or date_cls.today().isoformat()
            self._display["date"] = self._values["date"]
            self._advance()
        elif key == "title":
            if not text:
                self.notify("Title is required.", severity="error")
                return
            self._values["title"] = self._display["title"] = text
            self._advance()
        elif key == "amount":
            cents = parse_amount(text)
            if cents is None:
                self.notify("Amount: a signed decimal, e.g. -99.92", severity="error")
                return
            if cents == 0:
                self.notify("Amount must be non-zero.", severity="error")
                return
            self._values["amount"] = cents
            self._display["amount"] = format_cents(cents)
            self._advance()
        elif key in ("account", "category"):
            picked = self._picked()
            if picked is None:
                self.notify(f"No {key} matches “{text}”.", severity="error")
                return
            self._values[key] = picked[0]
            self._display[key] = picked[1]
            self._advance()
        elif key == "hashtags":
            if not text:
                self._advance()
            else:
                picked = self._picked()
                if picked is None:
                    self.notify(f"No hashtag matches “{text}”.", severity="error")
                    return
                self._values.setdefault("hashtags", []).append(picked[0])
                self._display["hashtags"] = " ".join("#" + n for n in self._tag_names())
                self.query_one("#bar", Input).value = ""
                self._recompute_suggestions("")
                self._refresh_view()
                return  # stay on hashtags
        elif key == "note":
            if text:
                self._values["note"] = self._display["note"] = text
            self._advance()
        self._refresh_view()

    def _advance(self) -> None:
        self._current = min(len(_FIELDS) - 1, self._current + 1)
        self._refresh_bar()

    def _tag_names(self) -> list[str]:
        by_id = dict((i, n) for (i, n) in self._hashtags)
        return [by_id.get(i, i[:8]) for i in self._values.get("hashtags", [])]

    # ---- render ----------------------------------------------------------
    def _refresh_view(self) -> None:
        self.query_one("#hint", Static).update(Text(_HINTS.get(self._key, ""), style="dim"))
        self.query_one("#suggest", Static).update(self._suggest_renderable())
        self.query_one("#summary", Static).update(self._summary_renderable())

    def _suggest_renderable(self) -> RenderableType:
        if self._key not in _ENTITY:
            return Text("")
        if not self._suggestions:
            return Text("  no matches — pick something that exists", style="dim")
        rows = []
        for idx, ent in enumerate(self._suggestions[:8]):
            name = ent[1]
            extra = f"  {ent[2]}" if len(ent) > 2 else ""
            line = Text(f"  {name}{extra}")
            if idx == self._suggest_idx:
                line.stylize("reverse")
            rows.append(line)
        return Group(*rows)

    def _summary_renderable(self) -> RenderableType:
        t = Table(box=None, pad_edge=False, show_header=False, expand=False)
        t.add_column("k")
        t.add_column("v")
        for i, (key, label) in enumerate(_FIELDS):
            shown = self._display.get(key)
            required = key in _REQUIRED
            if shown:
                value = Text(str(shown))
            else:
                value = Text("—" + ("  *" if required else "  (optional)"), style="dim")
            label_text = Text(label.lower())
            if i == self._current:
                label_text.stylize("bold")
            t.add_row(label_text, value)
        return t

    # ---- actions ---------------------------------------------------------
    def action_cancel(self) -> None:
        self.app.pop_screen()

    def action_submit(self) -> None:
        for key in _REQUIRED:
            if key not in self._values:
                self.notify(f"{key.capitalize()} is required.", severity="error")
                return
        payload: dict = {
            "id": str(uuid.uuid4()),
            "title": self._values["title"],
            "amount_cents": self._values["amount"],
            "account_id": self._values["account"],
            "category_id": self._values["category"],
            "date": to_canonical_aware(self._values.get("date") or date_cls.today().isoformat()),
        }
        if self._values.get("note"):
            payload["description"] = self._values["note"]
        if self._values.get("hashtags"):
            payload["hashtag_ids"] = self._values["hashtags"]
        self._submit(payload)

    @work(thread=True)
    def _submit(self, payload: dict) -> None:
        from expense import config as config_module
        from expense.cache import refresh_after_write
        from expense.http import ExpenseClient

        cfg = config_module.ensure_loaded()
        try:
            with ExpenseClient(cfg, verbose=self.app._verbose) as client:
                client.post("/transactions", json_body=payload)
                refresh_after_write(
                    client,
                    cfg,
                    no_cache=self.app._no_cache,
                    no_sync_after=False,
                    notice_stream=io.StringIO(),
                )
        except Exception as exc:
            self.app.call_from_thread(self.notify, str(exc), title="Failed", severity="error")
            return
        self.app.call_from_thread(self._done)

    def _done(self) -> None:
        self.notify("Transaction created.")
        self.app.pop_screen()


def _items(body: object) -> list:
    if isinstance(body, dict):
        return body.get("items", []) or []
    return body or []
