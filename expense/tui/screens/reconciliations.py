"""Reconciliations — list + new batch (Phase 2, pass 1).

Per-account bank-statement batches. The list shows every batch (Account column;
`a` filters to one account, `n` opens the new-batch form). Detail + assign +
complete/revert land in pass 2 (enter opens a read-only record for now).

New batch: name › account › date range › source (chained|manual) › [begin if
manual] › end. Begin balance is chained by default (the engine derives it from
the previous batch's end); manual lets you set it — you can't supply a value
while chained (engine 422). POST /reconciliations.
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
from textual.widget import Widget
from textual.widgets import Footer, Input, Label, Static

from expense.commands import accounts_cmd, reconcile_cmd
from expense.commands._resource import format_cents, load_account_name_map
from expense.dates import to_canonical_aware
from expense.tui.screens._base import SectionScreen
from expense.tui.screens.modals import RecordModal
from expense.tui.screens.quick_log import amount_to_text, parse_amount
from expense.tui.widgets.cursor_list import CursorList
from expense.tui.widgets.header import Breadcrumb

_STATUS = {1: "draft", 2: "completed"}
_LIST_HEADERS = ["Account", "Name", "Period", "Begin", "End", "Source", "Status"]


def _period(item: dict) -> str:
    ds = (item.get("date_start") or "")[:10]
    de = (item.get("date_end") or "")[:10]
    if ds and de:
        return f"{ds} → {de}"
    if ds:
        return f"{ds} → …"
    if de:
        return f"… → {de}"
    return "—"


def reconciliation_rows(items: list[dict], account_names: dict) -> list:
    """Pure (id, cells, base_style) rows for a CursorList. Unit-testable."""
    rows = []
    for it in items:
        status = it.get("status")
        cells = [
            account_names.get(it.get("account_id"), (it.get("account_id") or "?")[:8]),
            it.get("name") or "(unnamed)",
            _period(it),
            format_cents(it.get("beginning_balance_cents")),
            format_cents(it.get("ending_balance_cents")),
            it.get("beginning_balance_source") or "—",
            _STATUS.get(status, str(status) if status is not None else "—"),
        ]
        rows.append((it.get("id"), cells, "dim" if status == 2 else ""))
    return rows


class ReconciliationsScreen(SectionScreen):
    crumb = ("Capture & ledger", "Reconciliations")
    CARD_WIDTH = 100
    BINDINGS = [("a", "account", "Account"), ("n", "new", "New")]

    def __init__(self) -> None:
        super().__init__()
        self._by_id: dict = {}
        self._filter_idx = 0
        self._filter_ids: list = [None]

    def fetch(self) -> list:
        from expense import config as config_module

        cfg = config_module.ensure_loaded()
        body = reconcile_cmd.fetch_reconciliations(
            cfg,
            no_cache=self.app._no_cache,
            verbose=self.app._verbose,
            cold_start_notice=False,
            notice_stream=io.StringIO(),
        )
        return body.get("items", body) if isinstance(body, dict) else (body or [])

    def build(self, items: list) -> list[Widget]:
        names = load_account_name_map()
        present = sorted(
            {it.get("account_id") for it in items if it.get("account_id")},
            key=lambda a: names.get(a, a),
        )
        self._filter_ids = [None, *present]
        self._filter_idx = min(self._filter_idx, len(self._filter_ids) - 1)
        current = self._filter_ids[self._filter_idx]
        shown = [it for it in items if current is None or it.get("account_id") == current]
        self._by_id = {it.get("id"): it for it in shown}
        label = "All accounts" if current is None else names.get(current, current[:8])
        return [
            Static(Text("Reconciliations — bank-statement batches"), classes="section-title"),
            Static(Text(f"account: {label}   ·   a switch · n new", style="dim")),
            CursorList(
                _LIST_HEADERS,
                reconciliation_rows(shown, names),
                align_right={3, 4},
                empty="(no reconciliations — press n to create one)",
            ),
        ]

    def action_account(self) -> None:
        if len(self._filter_ids) > 1:
            self._filter_idx = (self._filter_idx + 1) % len(self._filter_ids)
            self._load()

    def action_new(self) -> None:
        self.app.push_screen(NewReconciliationScreen(), lambda _result: self._load())

    def on_cursor_list_selected(self, event: CursorList.Selected) -> None:
        item = self._by_id.get(event.key)
        if item:  # pass-1 placeholder; the real detail + assign land in pass 2
            self.app.push_screen(RecordModal(f"Reconciliation · {item.get('name') or '—'}", item))


# --------------------------------------------------------------------------- #
# New batch form
# --------------------------------------------------------------------------- #
_R_LABELS = {
    "name": "NAME",
    "account": "ACCOUNT",
    "date_start": "DATE START",
    "date_end": "DATE END",
    "source": "SOURCE",
    "begin": "BEGIN BALANCE",
    "end": "END BALANCE",
}
_R_HINTS = {
    "name": "e.g. “April 2026” · enter to save",
    "account": "pick a bank account · ↑↓ highlight · enter select",
    "date_start": "YYYY-MM-DD · optional · empty enter to skip",
    "date_end": "YYYY-MM-DD · optional · empty enter to skip",
    "source": "chained = begin from the previous batch · manual = set it yourself · ↑↓ · enter",
    "begin": "signed decimal · your statement's opening balance",
    "end": "signed decimal · statement's closing balance · optional · enter saves",
}
_SOURCES = [
    ("chained", "chained — begin carried from the previous batch"),
    ("manual", "manual — set the begin balance yourself"),
]
_AMOUNTS = {"begin", "end"}
_DATES = {"date_start", "date_end"}


class NewReconciliationScreen(Screen):
    crumb = ("Reconciliations", "New")
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
        self._values: dict = {"source": "chained"}
        self._display: dict = {"source": "chained"}
        self._accounts: list = []
        self._suggestions: list = []
        self._suggest_idx = 0
        self._submitting = False

    def _is_manual(self) -> bool:
        return self._values.get("source") == "manual"

    def _sequence(self) -> list[str]:
        seq = ["name", "account", "date_start", "date_end", "source"]
        return seq + (["begin", "end"] if self._is_manual() else ["end"])

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
        self._refresh_bar()
        self._refresh_view()
        self.query_one("#bar", Input).focus()
        self._load_accounts()

    @work(thread=True)
    def _load_accounts(self) -> None:
        from expense import config as config_module

        cfg = config_module.ensure_loaded()
        body = accounts_cmd.fetch_accounts(
            cfg,
            no_cache=self.app._no_cache,
            verbose=self.app._verbose,
            cold_start_notice=False,
            notice_stream=io.StringIO(),
        )
        items = body.get("items", body) if isinstance(body, dict) else (body or [])
        accounts = [
            (a["id"], a.get("name") or "(unnamed)", a.get("currency_code") or "?")
            for a in items
            if a.get("id") and not a.get("is_person")
        ]
        self.app.call_from_thread(self._set_accounts, accounts)

    def _set_accounts(self, accounts: list) -> None:
        self._accounts = accounts
        self._recompute(self.query_one("#bar", Input).value)
        self._refresh_view()

    # ---- bar / nav -------------------------------------------------------
    def _refresh_bar(self) -> None:
        key = self._key
        self.query_one("#field", Label).update(_R_LABELS[key])
        bar = self.query_one("#bar", Input)
        if key in _AMOUNTS and key in self._values:
            bar.value = amount_to_text(self._values[key])
        elif key in ("name", *_DATES):
            bar.value = str(self._values.get(key, "") or "")
        else:  # account / source re-pick
            bar.value = ""
        self._recompute(bar.value)

    def _recompute(self, text: str) -> None:
        key = self._key
        needle = text.strip().lower()
        if key == "account":
            self._suggestions = [(i, n, c) for (i, n, c) in self._accounts if needle in n.lower()]
        elif key == "source":
            self._suggestions = [
                (v, d) for (v, d) in _SOURCES if needle in v.lower() or needle in d.lower()
            ]
        else:
            self._suggestions = []
        self._suggest_idx = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._key in ("account", "source"):
            self._recompute(event.value)
            self._refresh_view()

    def action_suggest(self, delta: int) -> None:
        if self._suggestions:
            self._suggest_idx = max(0, min(len(self._suggestions) - 1, self._suggest_idx + delta))
            self._refresh_view()

    def action_field(self, delta: int) -> None:
        self._current = max(0, min(len(self._sequence()) - 1, self._current + delta))
        self._refresh_bar()
        self._refresh_view()

    def _advance(self) -> None:
        if self._current >= len(self._sequence()) - 1:
            self.action_submit()
        else:
            self._current += 1
            self._refresh_bar()
            self._refresh_view()

    # ---- commit ----------------------------------------------------------
    def on_input_submitted(self, event: Input.Submitted) -> None:
        key = self._key
        text = self.query_one("#bar", Input).value.strip()
        if key == "name":
            if not text:
                self.notify("Name is required.", severity="error")
                return
            self._values["name"] = self._display["name"] = text
            self._advance()
        elif key == "account":
            picked = self._suggestions[self._suggest_idx] if self._suggestions else None
            if picked is None:
                self.notify(f"No account matches “{text}”.", severity="error")
                return
            self._values["account"] = picked[0]
            self._display["account"] = picked[1]
            self._advance()
        elif key in _DATES:
            if text:
                try:
                    to_canonical_aware(text)
                except Exception:
                    self.notify(f"{_R_LABELS[key].title()}: use YYYY-MM-DD.", severity="error")
                    return
                self._values[key] = self._display[key] = text
            else:
                self._values.pop(key, None)
                self._display.pop(key, None)
            self._advance()
        elif key == "source":
            picked = self._suggestions[self._suggest_idx] if self._suggestions else None
            if picked is None:
                self.notify("Pick chained or manual.", severity="error")
                return
            self._values["source"] = self._display["source"] = picked[0]
            if picked[0] == "chained":  # chained has no begin slot
                self._values.pop("begin", None)
                self._display.pop("begin", None)
            self._advance()
        elif key == "begin":
            cents = parse_amount(text)
            if cents is None:
                self.notify("Begin balance: a signed decimal, e.g. 9580.00", severity="error")
                return
            self._values["begin"] = cents
            self._display["begin"] = format_cents(cents)
            self._advance()
        elif key == "end":
            if text:
                cents = parse_amount(text)
                if cents is None:
                    self.notify("End balance: a signed decimal, e.g. 9460.00", severity="error")
                    return
                self._values["end"] = cents
                self._display["end"] = format_cents(cents)
            else:
                self._values.pop("end", None)
                self._display.pop("end", None)
            self.action_submit()
            return
        self._refresh_view()

    # ---- render ----------------------------------------------------------
    def _refresh_view(self) -> None:
        self.query_one("#hint", Static).update(Text(_R_HINTS.get(self._key, ""), style="dim"))
        self.query_one("#suggest", Static).update(self._suggest_renderable())
        self.query_one("#summary", Static).update(self._summary_renderable())

    def _suggest_renderable(self) -> RenderableType:
        if self._key not in ("account", "source"):
            return Text("")
        if not self._suggestions:
            return Text("  no matches", style="dim")
        rows = []
        for i, ent in enumerate(self._suggestions):
            extra = f"  {ent[2]}" if self._key == "account" and len(ent) > 2 else ""
            line = Text(f"  {ent[1]}{extra}")
            if i == self._suggest_idx:
                line.stylize("reverse")
            rows.append(line)
        return Group(*rows)

    def _summary_renderable(self) -> RenderableType:
        seq = self._sequence()
        required = ("name", "account") + (("begin",) if self._is_manual() else ())
        t = Table(box=None, pad_edge=False, show_header=False)
        t.add_column("k")
        t.add_column("v")
        for key in seq:
            shown = self._display.get(key)
            if shown:
                value = Text(str(shown))
            else:
                tag = "  *" if key in required else "  (optional)"
                value = Text("—" + tag, style="dim")
            label = Text(_R_LABELS[key].lower())
            if key == self._key:
                label.stylize("bold")
            t.add_row(label, value)
        return t

    # ---- submit ----------------------------------------------------------
    def action_cancel(self) -> None:
        self.dismiss()

    def action_submit(self) -> None:
        if self._submitting:
            return
        required = ("name", "account") + (("begin",) if self._is_manual() else ())
        for key in required:
            if key not in self._values:
                self.notify(f"{_R_LABELS[key].title()} is required.", severity="error")
                return
        payload = self._payload()
        self._submitting = True
        self.query_one("#hint", Static).update(Text("Creating…", style="dim"))
        self._submit(payload)

    def _payload(self) -> dict:
        payload = {
            "id": str(uuid.uuid4()),
            "account_id": self._values["account"],
            "name": self._values["name"],
        }
        if self._values.get("date_start"):
            payload["date_start"] = to_canonical_aware(self._values["date_start"])
        if self._values.get("date_end"):
            payload["date_end"] = to_canonical_aware(self._values["date_end"])
        if self._is_manual():
            payload["beginning_balance_cents"] = self._values["begin"]
            payload["beginning_balance_source"] = "manual"
        else:
            payload["beginning_balance_source"] = "chained"
        if self._values.get("end") is not None:
            payload["ending_balance_cents"] = self._values["end"]
        return payload

    @work(thread=True, exclusive=True)
    def _submit(self, payload: dict) -> None:
        from expense import config as config_module
        from expense.cache import refresh_after_write
        from expense.http import ExpenseClient

        cfg = config_module.ensure_loaded()
        try:
            with ExpenseClient(cfg, verbose=self.app._verbose) as client:
                client.post("/reconciliations", json_body=payload)
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
        self.notify("Reconciliation created.")
        self.dismiss()
