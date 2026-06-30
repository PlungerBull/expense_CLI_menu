"""Log a transaction — quick-add bar (Phase 2).

One input bar cycles through fields; a summary fills below as you go. Entity
fields (account/category/hashtags/transfer-to) show a live-filtered suggestion
list — pick existing entities only.

Normal flow: Date › Title › Amount › Account › Transfer to? › Category ›
Hashtags › Note. Filling "Transfer to?" makes it a transfer instead: the field
set becomes … Account › Transfer to › To amount › Note (no category/hashtags —
the engine assigns @Transfer / @Debt). The To amount is the opposite sign of
Amount (auto-mirrored for same-currency accounts).

`enter` saves & advances · `ctrl+↑/↓` jump fields to re-edit · `↑/↓` move the
suggestion highlight · `ctrl+s` creates. Sign is explicit (− expense / +
income); currency is derived from the account.
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

_LABELS = {
    "date": "DATE",
    "title": "TITLE",
    "amount": "AMOUNT",
    "account": "ACCOUNT",
    "transfer_to": "TRANSFER TO?",
    "to_amount": "TO AMOUNT",
    "category": "CATEGORY",
    "hashtags": "HASHTAGS",
    "note": "NOTE",
}
_ENTITY = {"account", "transfer_to", "category", "hashtags"}  # account-pool / cat / tag
_AMOUNTS = {"amount", "to_amount"}
_HINTS = {
    "date": "YYYY-MM-DD · enter to accept today, or type a date",
    "title": "free text · enter to save",
    "amount": "signed decimal · − expense / + income · in the account's currency",
    "account": "pick an existing account · ↑↓ highlight · enter select",
    "transfer_to": "optional · pick a destination account → transfer · empty enter = skip",
    "to_amount": "opposite sign of Amount · same currency is auto-filled · overwrite if needed",
    "category": "pick an existing category · ↑↓ highlight · enter select",
    "hashtags": "type a tag · ↑↓ highlight · enter adds & stays · empty enter = done (optional)",
    "note": "optional · enter creates the transaction · (ctrl+s anytime)",
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
        self._submitting = False

    # ---- field sequence (dynamic: transfer swaps the tail) ---------------
    def _is_transfer(self) -> bool:
        return bool(self._values.get("transfer_to"))

    def _sequence(self) -> list[str]:
        seq = ["date", "title", "amount", "account", "transfer_to"]
        if self._is_transfer():
            seq += ["to_amount", "note"]
        else:
            seq += ["category", "hashtags", "note"]
        return seq

    def _required(self) -> tuple[str, ...]:
        if self._is_transfer():
            return ("title", "amount", "account", "transfer_to", "to_amount")
        return ("title", "amount", "account", "category")

    @property
    def _key(self) -> str:
        seq = self._sequence()
        return seq[min(self._current, len(seq) - 1)]

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

    def _set_entities(self, accounts, categories, hashtags) -> None:
        self._accounts, self._categories, self._hashtags = accounts, categories, hashtags
        self._recompute_suggestions(self.query_one("#bar", Input).value)
        self._refresh_view()

    def _account_currency(self, account_id) -> str | None:
        return next((c for (i, n, c) in self._accounts if i == account_id), None)

    # ---- bar / nav -------------------------------------------------------
    def _refresh_bar(self) -> None:
        key = self._key
        self.query_one("#field", Label).update(_LABELS[key])
        bar = self.query_one("#bar", Input)
        if key in _AMOUNTS and key in self._values:
            bar.value = amount_to_text(self._values[key])
        elif key in ("date", "title", "note"):
            bar.value = str(self._values.get(key, "") or "")
        else:  # entity fields re-pick from scratch
            bar.value = ""
        self._recompute_suggestions(bar.value)

    def action_field(self, delta: int) -> None:
        self._current = max(0, min(len(self._sequence()) - 1, self._current + delta))
        self._refresh_bar()
        self._refresh_view()

    def _advance(self) -> None:
        self._current = min(len(self._sequence()) - 1, self._current + 1)
        self._refresh_bar()

    def action_suggest(self, delta: int) -> None:
        if self._suggestions:
            self._suggest_idx = max(0, min(len(self._suggestions) - 1, self._suggest_idx + delta))
            self._refresh_view()

    # ---- suggestions -----------------------------------------------------
    def _recompute_suggestions(self, text: str) -> None:
        key = self._key
        needle = text.strip().lower()
        if key in ("account", "transfer_to"):
            src = self._values.get("account") if key == "transfer_to" else None
            pool = [(i, n, c) for (i, n, c) in self._accounts if needle in n.lower() and i != src]
        elif key == "category":
            pool = [(i, n) for (i, n) in self._categories if needle in n.lower()]
        elif key == "hashtags":
            needle = needle.lstrip("#")
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
        elif key == "transfer_to":
            self._commit_transfer_to(text)
        elif key == "to_amount":
            self._commit_to_amount(text)
        elif key == "hashtags":
            self._commit_hashtag(text)
            return  # _commit_hashtag advances or stays itself
        elif key == "note":
            if text:
                self._values["note"] = self._display["note"] = text
            self.action_submit()  # note is last → enter creates
            return
        self._refresh_view()

    def _commit_transfer_to(self, text: str) -> None:
        if not text:  # optional → skip, stay a normal entry
            for k in ("transfer_to", "to_amount"):
                self._values.pop(k, None)
                self._display.pop(k, None)
            self._advance()
            return
        picked = self._picked()
        if picked is None:
            self.notify(f"No account matches “{text}”.", severity="error")
            return
        if picked[0] == self._values.get("account"):
            self.notify("Transfer destination must differ from the source.", severity="error")
            return
        self._values["transfer_to"] = picked[0]
        self._display["transfer_to"] = picked[1]
        # same currency → auto-mirror To amount (opposite sign); else leave to user
        from_cur = self._account_currency(self._values.get("account"))
        to_cur = picked[2] if len(picked) > 2 else None
        amount = self._values.get("amount")
        if amount is not None and from_cur and to_cur and from_cur == to_cur:
            self._values["to_amount"] = -amount
            self._display["to_amount"] = format_cents(-amount)
        else:
            self._values.pop("to_amount", None)
            self._display.pop("to_amount", None)
        self._advance()

    def _commit_to_amount(self, text: str) -> None:
        raw = parse_amount(text) if text else self._values.get("to_amount")
        if raw is None:
            self.notify("Enter the destination amount, e.g. 500 or 270.50", severity="error")
            return
        if raw == 0:
            self.notify("Amount must be non-zero.", severity="error")
            return
        amount = self._values.get("amount", 0)
        magnitude = abs(raw)
        cents = magnitude if amount < 0 else -magnitude  # opposite sign of Amount
        self._values["to_amount"] = cents
        self._display["to_amount"] = format_cents(cents)
        self._advance()

    def _commit_hashtag(self, text: str) -> None:
        if not text:
            self._advance()
            self._refresh_view()
            return
        picked = self._picked()
        if picked is None:
            self.notify(f"No hashtag matches “{text}”.", severity="error")
            return
        self._values.setdefault("hashtags", []).append(picked[0])
        self._display["hashtags"] = " ".join("#" + n for n in self._tag_names())
        self.query_one("#bar", Input).value = ""
        self._recompute_suggestions("")
        self._refresh_view()  # stay on hashtags

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
        window = 8
        total = len(self._suggestions)
        start = 0
        if total > window:
            start = max(0, min(self._suggest_idx - window // 2, total - window))
        rows: list = []
        if start > 0:
            rows.append(Text(f"  ↑ {start} more", style="dim"))
        for idx in range(start, min(start + window, total)):
            ent = self._suggestions[idx]
            extra = f"  {ent[2]}" if len(ent) > 2 else ""
            line = Text(f"  {ent[1]}{extra}")
            if idx == self._suggest_idx:
                line.stylize("reverse")
            rows.append(line)
        remaining = total - min(start + window, total)
        if remaining > 0:
            rows.append(Text(f"  ↓ {remaining} more", style="dim"))
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
            if shown:
                value = Text(str(shown))
            else:
                tag = "  *" if key in required else "  (optional)"
                value = Text("—" + tag, style="dim")
            label_text = Text(_LABELS[key].lower())
            if key == current_key:
                label_text.stylize("bold")
            t.add_row(label_text, value)
        return t

    # ---- actions ---------------------------------------------------------
    def action_cancel(self) -> None:
        self.app.pop_screen()

    def action_submit(self) -> None:
        if self._submitting:
            return
        for key in self._required():
            if key not in self._values:
                self.notify(f"{_LABELS[key].title()} is required.", severity="error")
                return
        date = to_canonical_aware(self._values.get("date") or date_cls.today().isoformat())
        if self._is_transfer():
            payload = {
                "id": str(uuid.uuid4()),
                "title": self._values["title"],
                "amount_cents": self._values["amount"],
                "account_id": self._values["account"],
                "date": date,  # no category_id — engine assigns @Transfer / @Debt
                "transfer": {
                    "id": str(uuid.uuid4()),
                    "account_id": self._values["transfer_to"],
                    "amount_cents": self._values["to_amount"],
                },
            }
        else:
            payload = {
                "id": str(uuid.uuid4()),
                "title": self._values["title"],
                "amount_cents": self._values["amount"],
                "account_id": self._values["account"],
                "category_id": self._values["category"],
                "date": date,
            }
            if self._values.get("hashtags"):
                payload["hashtag_ids"] = self._values["hashtags"]
        if self._values.get("note"):
            payload["description"] = self._values["note"]
        self._submitting = True
        verb = "transfer" if self._is_transfer() else "transaction"
        self.query_one("#hint", Static).update(Text(f"Creating {verb}…", style="dim"))
        self._submit(payload)

    @work(thread=True, exclusive=True)
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
            self.app.call_from_thread(self._failed, str(exc))
            return
        self.app.call_from_thread(self._done)

    def _failed(self, message: str) -> None:
        self._submitting = False
        self.notify(message, title="Failed", severity="error")
        self._refresh_view()

    def _done(self) -> None:
        self.notify("Transfer created." if self._is_transfer() else "Transaction created.")
        self.app.pop_screen()


def _items(body: object) -> list:
    if isinstance(body, dict):
        return body.get("items", []) or []
    return body or []
