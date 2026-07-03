"""Reconciliations — list, new batch, and the working/detail screen (Phase 2).

Per-account bank-statement batches. The browse is account-first (two panes):
the account selector on top, the selected account's batches below in chain
order. `↑↓` in account focus swaps the account (the batch list follows); `enter`
drops into batch focus, where `enter` opens the working screen, `ctrl+↑/↓`
reorders the chain, and `esc` returns to the accounts. `n` creates a batch for
the selected account.

New batch: name › account › date range › source (chained|manual) › [begin if
manual] › end. Begin balance is chained by default (the engine derives it from
the previous batch's end); manual lets you set it — you can't supply a value
while chained (engine 422). POST /reconciliations.

Working screen (ReconciliationDetailScreen): a checklist of the account's
unassigned + already-in-batch transactions (draft) or a read-only list of the
batch's transactions (completed). `space` toggles membership (PUT the
transaction's reconciliation_id); `c`/`r`/`d` complete/revert/delete. Complete
needs ≥1 transaction and locks amount/account/title/date on them; delete is
draft-only and just detaches the transactions.
"""

import io
import uuid

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer, Input, Label, Static

from expense.commands import accounts_cmd, reconcile_cmd, transactions_cmd
from expense.commands._resource import (
    format_cents,
    load_account_name_map,
    load_category_name_map,
)
from expense.commands.dashboard_cmd import load_hashtag_name_map
from expense.dates import to_canonical_aware
from expense.tui.screens._base import SectionScreen
from expense.tui.screens.modals import ConfirmModal
from expense.tui.screens.quick_log import amount_to_text, parse_amount
from expense.tui.widgets.checklist import CheckList
from expense.tui.widgets.cursor_list import CursorList
from expense.tui.widgets.header import Breadcrumb

_STATUS = {1: "draft", 2: "completed"}
_LIST_HEADERS = ["Account", "Name", "Period", "Begin", "End", "Source", "Status"]


def _items(body: object) -> list:
    if isinstance(body, dict):
        return body.get("items", []) or []
    return body or []


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


_BATCH_HEADERS = ["Name", "Period", "Begin", "End", "Source", "Status"]


def _sort_key(r: dict):
    so = r.get("sort_order")
    return (so if so is not None else 10**9, r.get("id") or "")


def batch_rows(items: list[dict]) -> list:
    """Per-account batch rows (no Account column) for the browse's lower pane."""
    rows = []
    for it in items:
        status = it.get("status")
        cells = [
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
    """Account-first two-pane browse. Top: bank accounts. Bottom: the selected
    account's batches in chain order. `↑↓` in account focus swaps the account
    (the batch list follows); `enter` drops into batch focus; there `enter`
    opens a batch, `ctrl+↑/↓` reorders the chain, `esc` returns to accounts."""

    crumb = ("Capture & ledger", "Reconciliations")
    CARD_WIDTH = 100
    BINDINGS = [
        ("escape", "back", "Back"),
        ("r", "reload", "Refresh"),
        ("n", "new", "New"),
        ("ctrl+up", "reorder(-1)", "Move up"),
        ("ctrl+down", "reorder(1)", "Move down"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._recons: list = []
        self._accounts: list = []  # (id, name, currency, balance_cents)
        self._acct_idx = 0
        self._mode = "accts"  # "accts" | "batches"
        self._batches: list = []  # recon dicts for the selected account (sorted)
        self._by_id: dict = {}
        self._resume_batch = False
        self._resume_key: object | None = None

    def fetch(self) -> dict:
        from expense import config as config_module

        cfg = config_module.ensure_loaded()
        kw = dict(
            no_cache=self.app._no_cache,
            verbose=self.app._verbose,
            cold_start_notice=False,
            notice_stream=io.StringIO(),
        )
        recons = _items(reconcile_cmd.fetch_reconciliations(cfg, **kw))
        accts = _items(accounts_cmd.fetch_accounts(cfg, **kw))
        accounts = [
            (
                a["id"],
                a.get("name") or "(unnamed)",
                a.get("currency_code") or "?",
                a.get("current_balance_cents"),
            )
            for a in accts
            if a.get("id") and not a.get("is_person")
        ]
        return {"recons": recons, "accounts": accounts}

    def _selected_account(self):
        return self._accounts[self._acct_idx] if self._accounts else None

    def _rebuild_batches(self) -> None:
        acct = self._selected_account()
        aid = acct[0] if acct else None
        self._batches = sorted(
            (r for r in self._recons if r.get("account_id") == aid), key=_sort_key
        )
        self._by_id = {r.get("id"): r for r in self._batches}

    def _batch_caption(self) -> str:
        acct = self._selected_account()
        label = acct[1] if acct else "—"
        return f"Reconciliations · {label}   ·   chain order (oldest → newest)"

    def build(self, data: dict) -> list[Widget]:
        self._recons = data["recons"]
        self._accounts = data["accounts"]
        self._acct_idx = min(self._acct_idx, max(0, len(self._accounts) - 1))
        self._rebuild_batches()
        acct_rows = [
            (aid, [name, cur, format_cents(bal)]) for (aid, name, cur, bal) in self._accounts
        ]
        self._accts_list = CursorList(
            ["Account", "Cur", "Balance"], acct_rows, align_right={2}, empty="(no bank accounts)"
        )
        self._accts_list.id = "accts"
        self._batch_list = CursorList(
            _BATCH_HEADERS,
            batch_rows(self._batches),
            align_right={2, 3},
            empty="(no batches — press n to create one)",
        )
        self._batch_list.id = "batches"
        title = "Reconciliations — pick an account, then a batch"
        return [
            Static(Text(title), classes="section-title"),
            Static(Text("Account", style="dim")),
            self._accts_list,
            Static(Text(self._batch_caption(), style="dim"), id="batchcap"),
            self._batch_list,
        ]

    async def _show(self, data: object) -> None:
        await super()._show(data)
        if not self._accounts:
            return
        self._accts_list.set_cursor(self._acct_idx)
        if self._resume_batch:
            self._resume_batch = False
            self._mode = "batches"
            self._batch_list.set_cursor(self._batch_list.index_of(self._resume_key))
            self._batch_list.focus()
        else:
            self._mode = "accts"
            self._accts_list.focus()

    # ---- interaction -----------------------------------------------------
    def on_cursor_list_highlighted(self, event: CursorList.Highlighted) -> None:
        if self._mode != "accts":
            return
        self._acct_idx = event.index
        self._rebuild_batches()
        self._batch_list.set_rows(batch_rows(self._batches))
        self.query_one("#batchcap", Static).update(Text(self._batch_caption(), style="dim"))

    def on_cursor_list_selected(self, event: CursorList.Selected) -> None:
        if self._mode == "accts":
            if not self._batches:
                self.notify("No batches for this account — press n to create one.")
                return
            self._mode = "batches"
            self._batch_list.focus()
            return
        item = self._by_id.get(event.key)
        if item:
            self._resume_batch = True
            self._resume_key = event.key
            self.app.push_screen(ReconciliationDetailScreen(item), lambda _result: self._load())

    def action_back(self) -> None:
        if self._mode == "batches":
            self._mode = "accts"
            self._accts_list.focus()
        else:
            self.app.pop_screen()

    def action_new(self) -> None:
        acct = self._selected_account()
        if not acct:
            self.notify("No account selected.", severity="error")
            return
        self._resume_batch = True
        self._resume_key = None
        self.app.push_screen(
            NewReconciliationScreen(account_id=acct[0], account_name=acct[1]),
            lambda _result: self._load(),
        )

    def action_reorder(self, delta: int) -> None:
        if self._mode != "batches" or len(self._batches) < 2:
            return
        key = self._batch_list.cursor_key
        ids = [r.get("id") for r in self._batches]
        i = ids.index(key)
        j = i + delta
        if j < 0 or j >= len(ids):
            return
        ids[i], ids[j] = ids[j], ids[i]
        acct = self._selected_account()
        self._resume_batch = True
        self._resume_key = key
        self._reorder(acct[0], ids)

    @work(thread=True, exclusive=True)
    def _reorder(self, account_id: str, ordered_ids: list) -> None:
        from expense import config as config_module
        from expense.cache import refresh_after_write
        from expense.http import ExpenseClient

        cfg = config_module.ensure_loaded()
        try:
            with ExpenseClient(cfg, verbose=self.app._verbose) as client:
                client.put(
                    f"/accounts/{account_id}/reconciliations/order",
                    json_body={"ordered_ids": ordered_ids},
                )
                refresh_after_write(
                    client,
                    cfg,
                    no_cache=self.app._no_cache,
                    no_sync_after=False,
                    notice_stream=io.StringIO(),
                )
        except Exception as exc:
            self.app.call_from_thread(
                self.notify, str(exc), title="Couldn't reorder", severity="error"
            )
            return
        self.app.call_from_thread(self._reordered)

    def _reordered(self) -> None:
        self.notify("Reordered.")
        self._load()


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
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "submit", "Create"),
        ("up", "suggest(-1)", "↑"),
        ("down", "suggest(1)", "↓"),
        ("ctrl+up", "field(-1)", "Prev field"),
        ("ctrl+down", "field(1)", "Next field"),
    ]

    def __init__(self, account_id: str | None = None, account_name: str | None = None) -> None:
        super().__init__()
        self._current = 0
        self._values: dict = {"source": "chained"}
        self._display: dict = {"source": "chained"}
        self._accounts: list = []
        self._suggestions: list = []
        self._suggest_idx = 0
        self._submitting = False
        self._preset_account = account_id
        if account_id:  # created from within an account — don't ask for it again
            self._values["account"] = account_id
            self._display["account"] = account_name or account_id[:8]
            self.crumb = ("Reconciliations", account_name or "—", "New")
        else:
            self.crumb = ("Reconciliations", "New")

    def _is_manual(self) -> bool:
        return self._values.get("source") == "manual"

    def _sequence(self) -> list[str]:
        seq = ["name"] if self._preset_account else ["name", "account"]
        seq += ["date_start", "date_end", "source"]
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
        if not self._preset_account:  # only need the account picker for standalone create
            self._load_accounts()

    @work(thread=True, exclusive=True)
    def _load_accounts(self) -> None:
        from expense import config as config_module

        try:
            cfg = config_module.ensure_loaded()
            body = accounts_cmd.fetch_accounts(
                cfg,
                no_cache=self.app._no_cache,
                verbose=self.app._verbose,
                cold_start_notice=False,
                notice_stream=io.StringIO(),
            )
        except Exception as exc:  # surface engine/config errors in-app, don't crash
            self.app.call_from_thread(self.notify, str(exc), severity="error")
            return
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


# --------------------------------------------------------------------------- #
# Working / detail screen — assign transactions, complete / revert / delete
# --------------------------------------------------------------------------- #
def _txn_sub(it: dict, cat_names: dict, tag_names: dict) -> str:
    """The dim category · #tags · note sub-line for a transaction row."""
    parts = []
    cat = cat_names.get(it.get("category_id"))
    if cat:
        parts.append(cat)
    tags = it.get("hashtag_ids") or []
    if tags:
        parts.append(" ".join("#" + tag_names.get(t, t[:6]) for t in tags))
    note = it.get("description")
    if note:
        parts.append(f'"{note}"')
    return "  ·  ".join(parts)


class ReconciliationDetailScreen(Screen):
    """One batch: header + a transaction checklist (draft) or read-only list
    (completed). `space` toggles membership; `c`/`r`/`d` complete/revert/delete."""

    BINDINGS = [
        ("escape", "back", "Back"),
        ("c", "complete", "Complete"),
        ("r", "revert", "Revert"),
        ("d", "delete", "Delete"),
    ]

    def __init__(self, record: dict) -> None:
        super().__init__()
        self._record = record
        self._id = record.get("id")
        self._account_id = record.get("account_id")
        self._busy = False
        self._list: CheckList | None = None

    @property
    def _completed(self) -> bool:
        return self._record.get("status") == 2

    def compose(self) -> ComposeResult:
        yield Breadcrumb(("Reconciliations", self._record.get("name") or "—"), id="crumb")
        yield Static("", id="rhead")
        yield Container(id="rlist")
        yield Static("", id="rhint")
        yield Footer()

    def on_mount(self) -> None:
        self._render_header()
        self._load_txns()

    def _render_header(self) -> None:
        r = self._record
        acct = load_account_name_map().get(self._account_id, (self._account_id or "?")[:8])
        status = _STATUS.get(r.get("status"), "—")
        text = Text.assemble(
            (r.get("name") or "—", "bold"),
            ("  ·  ", "dim"),
            (acct, ""),
            ("  ·  ", "dim"),
            (_period(r), "dim"),
            ("\n", ""),
            ("begin ", "dim"),
            (format_cents(r.get("beginning_balance_cents")), ""),
            (f"  ({r.get('beginning_balance_source') or '—'})", "dim"),
            ("    end ", "dim"),
            (format_cents(r.get("ending_balance_cents")), ""),
            ("    status ", "dim"),
            (status, "green" if status == "completed" else "yellow"),
        )
        self.query_one("#rhead", Static).update(text)
        hint = (
            "read-only while completed · r revert to edit · esc back"
            if self._completed
            else "space toggle in/out of this batch · c complete · r revert · d delete · esc back"
        )
        self.query_one("#rhint", Static).update(Text(hint, style="dim"))

    @work(thread=True, exclusive=True)
    def _load_txns(self) -> None:
        from expense import config as config_module

        try:
            cfg = config_module.ensure_loaded()
            kw = dict(
                no_cache=self.app._no_cache,
                verbose=self.app._verbose,
                cold_start_notice=False,
                notice_stream=io.StringIO(),
            )
            # assigned-to-this-batch transactions (always; any date)
            assigned = _items(
                transactions_cmd.fetch_transactions(cfg, reconciliation=self._id, limit=500, **kw)
            )
            available = []
            if not self._completed:  # draft also offers the account's unassigned txns in range
                available = [
                    it
                    for it in _items(
                        transactions_cmd.fetch_transactions(
                            cfg,
                            account=self._account_id,
                            date_from=self._record.get("date_start") or None,
                            date_to=self._record.get("date_end") or None,
                            limit=500,
                            **kw,
                        )
                    )
                    if it.get("reconciliation_id") is None
                ]
            cat_names = load_category_name_map()
            tag_names = load_hashtag_name_map()
        except Exception as exc:  # surface engine/config errors in-app, don't crash
            self.app.call_from_thread(self.notify, str(exc), severity="error")
            return
        rows, checked, seen = [], [], set()
        for it in [*assigned, *available]:
            key = it.get("id")
            if key in seen:
                continue
            seen.add(key)
            if it.get("reconciliation_id") == self._id:
                checked.append(key)
            rows.append(
                (
                    key,
                    it.get("title"),
                    it.get("amount_cents"),
                    (it.get("date") or "")[:10],
                    _txn_sub(it, cat_names, tag_names),
                )
            )
        self.app.call_from_thread(self._populate, rows, checked)

    async def _populate(self, rows: list, checked: list) -> None:
        container = self.query_one("#rlist", Container)
        await container.remove_children()
        empty = (
            "(no transactions in this batch)"
            if self._completed
            else "(no transactions for this account in range)"
        )
        self._list = CheckList(rows, checked, read_only=self._completed, empty=empty)
        await container.mount(self._list)
        if not self._completed:
            self._list.focus()

    # ---- assign / unassign ----------------------------------------------
    def on_check_list_toggled(self, event: CheckList.Toggled) -> None:
        self._assign(event.key, self._id if event.checked else None)

    @work(thread=True)
    def _assign(self, tx_id: object, recon_id: object) -> None:
        from expense import config as config_module
        from expense.cache import refresh_after_write
        from expense.http import ExpenseClient

        cfg = config_module.ensure_loaded()
        try:
            with ExpenseClient(cfg, verbose=self.app._verbose) as client:
                client.put(f"/transactions/{tx_id}", json_body={"reconciliation_id": recon_id})
                refresh_after_write(
                    client,
                    cfg,
                    no_cache=self.app._no_cache,
                    no_sync_after=False,
                    notice_stream=io.StringIO(),
                )
        except Exception as exc:
            self.app.call_from_thread(self._assign_failed, str(exc))

    def _assign_failed(self, message: str) -> None:
        self.notify(message, title="Couldn't update", severity="error")
        self._load_txns()  # resync the checklist to the engine's truth

    # ---- status actions --------------------------------------------------
    def action_back(self) -> None:
        self.dismiss()

    def action_complete(self) -> None:
        if self._completed:
            self.notify("Already completed.")
            return
        if not (self._list and self._list.checked):
            self.notify("Assign at least one transaction first.", severity="error")
            return
        n = len(self._list.checked)
        self._confirm(
            "Complete reconciliation?",
            f"Locks amount/account/title/date on the {n} assigned transaction(s).",
            lambda: self._status_action(
                "POST", f"/reconciliations/{self._id}/complete", 2, "completed"
            ),
        )

    def action_revert(self) -> None:
        if not self._completed:
            self.notify("Only completed reconciliations can be reverted.")
            return
        self._confirm(
            "Revert to draft?",
            "Unlocks the assigned transactions and this batch's balances.",
            lambda: self._status_action(
                "POST", f"/reconciliations/{self._id}/revert", 1, "reverted to draft"
            ),
        )

    def action_delete(self) -> None:
        if self._completed:
            self.notify("Revert before deleting a completed reconciliation.", severity="error")
            return
        self._confirm(
            "Delete reconciliation?",
            "Detaches its transactions (they are not deleted) and removes the batch.",
            lambda: self._status_action("DELETE", f"/reconciliations/{self._id}", None, "deleted"),
        )

    def _confirm(self, title: str, message: str, action) -> None:
        def cb(ok: bool) -> None:
            if ok:
                action()

        self.app.push_screen(ConfirmModal(title, message), cb)

    @work(thread=True, exclusive=True)
    def _status_action(self, method: str, path: str, new_status, verb: str) -> None:
        if self._busy:
            return
        self._busy = True
        from expense import config as config_module
        from expense.cache import refresh_after_write
        from expense.http import ExpenseClient

        cfg = config_module.ensure_loaded()
        try:
            with ExpenseClient(cfg, verbose=self.app._verbose) as client:
                if method == "DELETE":
                    client.delete(path)
                else:
                    client.post(path)
                refresh_after_write(
                    client,
                    cfg,
                    no_cache=self.app._no_cache,
                    no_sync_after=False,
                    notice_stream=io.StringIO(),
                )
        except Exception as exc:
            self.app.call_from_thread(self._action_failed, str(exc), verb)
            return
        self.app.call_from_thread(self._action_done, new_status, verb)

    def _action_failed(self, message: str, verb: str) -> None:
        self._busy = False
        self.notify(message, title=f"Couldn't {verb.split()[0]}", severity="error")

    def _action_done(self, new_status, verb: str) -> None:
        self._busy = False
        self.notify(f"Reconciliation {verb}.")
        if verb == "deleted":
            self.dismiss()
            return
        self._record["status"] = new_status
        self._render_header()
        self._load_txns()
