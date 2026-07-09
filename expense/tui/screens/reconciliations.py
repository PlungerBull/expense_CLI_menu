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
transaction's reconciliation_id); `c`/`u`/`d` complete/revert/delete; `r`
refetches the batch + checklist. Complete
needs ≥1 transaction and locks amount/account/title/date on them; delete is
draft-only and just detaches the transactions.
"""

import io
import uuid

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer, Input, Static
from textual.worker import get_current_worker

from expense.commands import accounts_cmd, reconcile_cmd, transactions_cmd
from expense.commands._resource import (
    format_cents,
    items_of,
    load_account_name_map,
    load_category_name_map,
    load_hashtag_name_map,
)
from expense.dates import to_canonical_aware
from expense.errors import EngineError, format_error
from expense.tui.screens._base import ContentSwapLockMixin, EngineWriteMixin, SectionScreen
from expense.tui.screens._form import FormScreen
from expense.tui.screens.modals import ConfirmModal
from expense.tui.screens.quick_log import amount_to_text, parse_amount
from expense.tui.theme import AMOUNT_RULE, BALANCE_RULE, Palette, resolve_palette
from expense.tui.widgets.cells import amount_cell
from expense.tui.widgets.checklist import CheckList
from expense.tui.widgets.cursor_list import CursorList
from expense.tui.widgets.header import Breadcrumb

# Status labels + period formatting are owned by the commands layer
# (reconcile_cmd.format_status / format_period) — one copy, per the §5 rule.
_period = reconcile_cmd.format_period
_LIST_HEADERS = ["Account", "Name", "Period", "Begin", "End", "Source", "Status"]


def reconciliation_rows(
    items: list[dict], account_names: dict, palette: Palette | None = None
) -> list:
    """Pure (id, cells, base_style) rows for a CursorList. Unit-testable."""
    rows = []
    for it in items:
        status = it.get("status")
        cells = [
            account_names.get(it.get("account_id"), (it.get("account_id") or "?")[:8]),
            it.get("name") or "(unnamed)",
            _period(it),
            amount_cell(it.get("beginning_balance_cents"), palette, BALANCE_RULE),
            amount_cell(it.get("ending_balance_cents"), palette, BALANCE_RULE),
            it.get("beginning_balance_source") or "—",
            reconcile_cmd.format_status(status),
        ]
        rows.append((it.get("id"), cells, "dim" if status == 2 else ""))
    return rows


_BATCH_HEADERS = ["Name", "Period", "Begin", "End", "Source", "Status"]


def _sort_key(r: dict):
    so = r.get("sort_order")
    return (so if so is not None else 10**9, r.get("id") or "")


def batch_rows(items: list[dict], palette: Palette | None = None) -> list:
    """Per-account batch rows (no Account column) for the browse's lower pane."""
    rows = []
    for it in items:
        status = it.get("status")
        cells = [
            it.get("name") or "(unnamed)",
            _period(it),
            amount_cell(it.get("beginning_balance_cents"), palette, BALANCE_RULE),
            amount_cell(it.get("ending_balance_cents"), palette, BALANCE_RULE),
            it.get("beginning_balance_source") or "—",
            reconcile_cmd.format_status(status),
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
        ("escape", "back", "Back"),  # not the inherited pop: two-stage batches → accounts → home
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
        recons = items_of(reconcile_cmd.fetch_reconciliations(cfg, **kw))
        accts = items_of(accounts_cmd.fetch_accounts(cfg, **kw))
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
        palette = resolve_palette(self.app)
        acct_rows = [
            (aid, [name, cur, amount_cell(bal, palette, AMOUNT_RULE)])
            for (aid, name, cur, bal) in self._accounts
        ]
        self._accts_list = CursorList(
            ["Account", "Cur", "Balance"], acct_rows, align_right={2}, empty="(no bank accounts)"
        )
        self._accts_list.id = "accts"
        self._batch_list = CursorList(
            _BATCH_HEADERS,
            batch_rows(self._batches, palette=palette),
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
        # Source guard (backlog 6.2c): a Highlighted from the batches pane
        # (reachable by Tab/click focus without a select) must not overwrite
        # the selected account — `n` would then create under the wrong one.
        if self._mode != "accts" or event.control is not getattr(self, "_accts_list", None):
            return
        self._acct_idx = event.index
        self._rebuild_batches()
        self._batch_list.set_rows(batch_rows(self._batches, palette=resolve_palette(self.app)))
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

    def _reorder(self, account_id: str, ordered_ids: list) -> None:
        self.run_write(
            "PUT",
            f"/accounts/{account_id}/reconciliations/order",
            json_body={"ordered_ids": ordered_ids},
            on_success=self._reordered,
            on_error=lambda m: self.notify(m, title="Couldn't reorder", severity="error"),
        )

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


class NewReconciliationScreen(FormScreen):
    RESOURCE = "reconciliations"

    def __init__(self, account_id: str | None = None, account_name: str | None = None) -> None:
        super().__init__()
        self._values = {"source": "chained"}
        self._display = {"source": "chained"}
        self._accounts: list = []
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

    def _required(self) -> tuple[str, ...]:
        return ("name", "account") + (("begin",) if self._is_manual() else ())

    def _label(self, key: str) -> str:
        return _R_LABELS[key]

    def _hint_for(self, key: str) -> str:
        return _R_HINTS.get(key, "")

    def _suggests(self, key: str) -> bool:
        return key in ("account", "source")

    def _bar_value(self, key: str) -> str:
        if key in _AMOUNTS and key in self._values:
            return amount_to_text(self._values[key])
        if key in ("name", *_DATES):
            return str(self._values.get(key, "") or "")
        return ""  # account / source re-pick

    def _after_mount(self) -> None:
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
            self.app.call_from_thread(self.notify, format_error(exc), severity="error")
            return
        items = items_of(body)
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

    # ---- suggestions -----------------------------------------------------
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

    # ---- submit ----------------------------------------------------------
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

    def _done(self) -> None:
        self.notify("Reconciliation created.")
        self.dismiss()


# --------------------------------------------------------------------------- #
# Working / detail screen — assign transactions, complete / revert / delete
# --------------------------------------------------------------------------- #
_TXN_PAGE = 200  # engine hard cap on `limit` — page instead of one oversized request


def _fetch_all_txns(cfg, **kw) -> list[dict]:
    """Every matching transaction, paged at the engine cap.

    A single limit=500 request 422s live (cap is 200) and silently truncates
    the checklist even cached; loop until a short page instead.
    """
    out: list[dict] = []
    offset = 0
    while True:
        page = items_of(
            transactions_cmd.fetch_transactions(cfg, limit=_TXN_PAGE, offset=offset, **kw)
        )
        out.extend(page)
        if len(page) < _TXN_PAGE:
            return out
        offset += _TXN_PAGE


def _status_span(status: str, palette: Palette) -> tuple[str, str]:
    """(text, style) for the header's status word — completed→success, draft→warning."""
    return status, palette.success if status == "completed" else palette.warning


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


class ReconciliationDetailScreen(EngineWriteMixin, ContentSwapLockMixin, Screen):
    """One batch: header + a transaction checklist (draft) or read-only list
    (completed). `space` toggles membership; `c`/`u`/`d` complete/revert/delete;
    `r` refetches the batch + checklist (r = refresh everywhere, never a write)."""

    BINDINGS = [
        ("escape", "back", "Back"),
        ("r", "reload", "Refresh"),
        ("c", "complete", "Complete"),
        ("u", "revert", "Revert"),
        ("d", "delete", "Delete"),
    ]

    def __init__(self, record: dict) -> None:
        super().__init__()
        self._record = record
        self._id = record.get("id")
        self._account_id = record.get("account_id")
        self._busy = False
        self._list: CheckList | None = None
        # toggle serialization (backlog 3.2): pending (tx_id, recon_id) intents
        self._toggle_queue: list[tuple[object, object]] = []
        self._toggle_inflight = False

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
        self.app.theme_changed_signal.subscribe(self, self._on_theme_change)
        self._render_header()
        self._load_txns()

    def _on_theme_change(self, _theme: object) -> None:
        self._render_header()
        self._load_txns()

    def _render_header(self) -> None:
        r = self._record
        palette = resolve_palette(self.app)
        acct = load_account_name_map().get(self._account_id, (self._account_id or "?")[:8])
        status = reconcile_cmd.format_status(r.get("status"))
        begin = amount_cell(r.get("beginning_balance_cents"), palette, BALANCE_RULE)
        end = amount_cell(r.get("ending_balance_cents"), palette, BALANCE_RULE)
        text = Text.assemble(
            (r.get("name") or "—", "bold"),
            ("  ·  ", "dim"),
            (acct, ""),
            ("  ·  ", "dim"),
            (_period(r), "dim"),
            ("\n", ""),
            ("begin ", "dim"),
            begin if isinstance(begin, Text) else (begin, ""),
            (f"  ({r.get('beginning_balance_source') or '—'})", "dim"),
            ("    end ", "dim"),
            end if isinstance(end, Text) else (end, ""),
            ("    status ", "dim"),
            _status_span(status, palette),
        )
        self.query_one("#rhead", Static).update(text)
        hint = (
            "read-only while completed · u revert to edit · r refresh · esc back"
            if self._completed
            else "space toggle in/out of this batch · c complete · u revert · d delete"
            " · r refresh · esc back"
        )
        self.query_one("#rhint", Static).update(Text(hint, style="dim"))

    # own load group (mirrors SectionScreen._load's "section-load"): a refresh
    # cancels stale refreshes only, never a run_write ("engine-write") worker
    @work(thread=True, exclusive=True, group="recon-detail-load")
    def _load_txns(self, refresh_record: bool = False) -> None:
        from expense import config as config_module

        # Exclusive cancellation is cooperative: a superseded load keeps
        # running, so it must stop painting or two _populate swaps interleave
        # and stack duplicate checklists (backlog 6.2a).
        worker = get_current_worker()
        try:
            cfg = config_module.ensure_loaded()
            kw = dict(
                no_cache=self.app._no_cache,
                verbose=self.app._verbose,
                cold_start_notice=False,
                notice_stream=io.StringIO(),
            )
            if refresh_record:
                # refetch the batch itself too — a stale header/status would
                # misrepresent balances and the read-only gate. By id: scanning
                # the collection stops at one page and falsely reported later
                # records as deleted (backlog 6.2b).
                try:
                    fresh = reconcile_cmd.fetch_reconciliation(cfg, self._id, limit=1, **kw)
                except EngineError as err:
                    if err.status == 404:
                        if not worker.is_cancelled:
                            self.app.call_from_thread(self._record_gone)
                        return
                    raise
                if worker.is_cancelled:
                    return
                # keep _record list-row-shaped: drop the embedded window keys
                self._record = {k: v for k, v in fresh.items() if not k.startswith("transactions")}
                self.app.call_from_thread(self._render_header)
            # assigned-to-this-batch transactions (always; any date)
            assigned = _fetch_all_txns(cfg, reconciliation=self._id, **kw)
            available = []
            if not self._completed:  # draft also offers the account's unassigned txns in range
                available = [
                    it
                    for it in _fetch_all_txns(
                        cfg,
                        account=self._account_id,
                        date_from=self._record.get("date_start") or None,
                        date_to=self._record.get("date_end") or None,
                        **kw,
                    )
                    if it.get("reconciliation_id") is None
                ]
            cat_names = load_category_name_map()
            tag_names = load_hashtag_name_map()
        except Exception as exc:  # surface engine/config errors in-app, don't crash
            if not worker.is_cancelled:
                self.app.call_from_thread(self.notify, format_error(exc), severity="error")
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
        if worker.is_cancelled:
            return
        self.app.call_from_thread(self._populate, rows, checked)

    async def _populate(self, rows: list, checked: list) -> None:
        async with self._content_lock():
            container = self.query_one("#rlist", Container)
            await container.remove_children()
            empty = (
                "(no transactions in this batch)"
                if self._completed
                else "(no transactions for this account in range)"
            )
            self._list = CheckList(
                rows,
                checked,
                read_only=self._completed,
                empty=empty,
                palette=resolve_palette(self.app),
            )
            await container.mount(self._list)
            if not self._completed:
                self._list.focus()

    # ---- assign / unassign ----------------------------------------------
    def on_check_list_toggled(self, event: CheckList.Toggled) -> None:
        # Queued, one PUT in flight at a time: rapid `space` presses would
        # otherwise race overlapping writes with no ordering guarantee (thread
        # cancellation is cooperative, so exclusive workers don't serialize).
        self._toggle_queue.append((event.key, self._id if event.checked else None))
        self._pump_toggles()

    def _pump_toggles(self) -> None:
        if self._toggle_inflight or not self._toggle_queue:
            return
        tx_id, recon_id = self._toggle_queue.pop(0)
        self._toggle_inflight = True
        # Success is silent — the checklist toggle already shows the new state.
        self.run_write(
            "PUT",
            f"/transactions/{tx_id}",
            json_body={"reconciliation_id": recon_id},
            on_success=self._toggle_done,
            on_error=self._assign_failed,
        )

    def _toggle_done(self) -> None:
        self._toggle_inflight = False
        self._pump_toggles()

    def _assign_failed(self, message: str) -> None:
        # Queued intents were made against a checklist state the engine just
        # contradicted — drop them and resync to the engine's truth.
        self._toggle_inflight = False
        self._toggle_queue.clear()
        self.notify(message, title="Couldn't update", severity="error")
        self._load_txns()  # resync the checklist to the engine's truth

    # ---- status actions --------------------------------------------------
    def action_back(self) -> None:
        self.dismiss()

    def action_reload(self) -> None:
        self._load_txns(refresh_record=True)

    def _record_gone(self) -> None:
        self.notify("This reconciliation no longer exists.", severity="error")
        self.dismiss()

    def action_complete(self) -> None:
        if self._completed:
            self.notify("Already completed.")
            return
        # No ≥1-assigned pre-guard: the engine 422s an empty complete and
        # run_write toasts its message (thin wrapper, backlog 2.5).
        n = len(self._list.checked) if self._list else 0
        self._confirm(
            "Complete reconciliation?",
            f"Locks amount/account/title/date on the {n} assigned transaction(s).",
            lambda: self._status_action(
                "POST", f"/reconciliations/{self._id}/complete", 2, "completed"
            ),
        )

    def action_revert(self) -> None:
        # No completed-only pre-guard: the engine treats revert-on-draft as
        # an idempotent 200 no-op (thin wrapper, backlog 2.5).
        self._confirm(
            "Revert to draft?",
            "Unlocks the assigned transactions and this batch's balances.",
            lambda: self._status_action(
                "POST", f"/reconciliations/{self._id}/revert", 1, "reverted to draft"
            ),
        )

    def action_delete(self) -> None:
        # No draft-only pre-guard: deleting a completed reconciliation 409s
        # engine-side ("… Revert to draft first.") and run_write toasts that
        # message (thin wrapper, backlog 2.5).
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

    def _status_action(self, method: str, path: str, new_status, verb: str) -> None:
        if self._busy:
            return
        self._busy = True
        self.run_write(
            method,
            path,
            on_success=lambda: self._action_done(new_status, verb),
            on_error=lambda m: self._action_failed(m, verb),
        )

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
