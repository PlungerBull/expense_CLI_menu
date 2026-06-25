"""Log a transaction — create a ledger entry directly (Phase 2 form).

Required: title, signed-cents amount (non-zero), account, category (date
defaults to now). Optional here: description, tri-state cleared. Hashtags and
the transfer sub-flow are deferred — use `expense log` for those until a later
pass. Submits POST /v1/transactions, refreshes the replica, pops back on success.
"""

import io
import uuid

from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Label, Select

from expense.commands._resource import load_account_name_map, load_category_name_map
from expense.dates import now_local_iso
from expense.tui.widgets.header import Breadcrumb

_CLEARED = [("unset", "unset"), ("cleared", "yes"), ("not cleared", "no")]


class LogTransactionScreen(Screen):
    crumb = ("Capture & ledger", "Log a transaction")
    BINDINGS = [
        ("escape", "app.pop_screen", "Cancel"),
        ("ctrl+s", "submit", "Save"),
    ]

    def compose(self) -> ComposeResult:
        yield Breadcrumb(self.crumb, id="crumb")
        yield Vertical(
            Label("Title *"),
            Input(placeholder="e.g. Almuerzo con cliente", id="f-title"),
            Label("Amount — signed cents, negative = expense *"),
            Input(placeholder="-1500", id="f-amount"),
            Label("Account *"),
            Select([], prompt="pick an account", id="f-account"),
            Label("Category *"),
            Select([], prompt="pick a category", id="f-category"),
            Label("Description"),
            Input(placeholder="optional", id="f-description"),
            Label("Cleared?"),
            Select(_CLEARED, value="unset", allow_blank=False, id="f-cleared"),
            Button("Create  (ctrl+s)", id="f-create", variant="primary"),
            id="form",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._load_options()

    @work(thread=True)
    def _load_options(self) -> None:
        # Warm the replica first so the Selects are populated even on a cold
        # cache (the name maps read the replica directly). Best-effort.
        if not self.app._no_cache:
            try:
                from expense import config as config_module
                from expense.cache import ensure_synced
                from expense.http import ExpenseClient

                cfg = config_module.ensure_loaded()
                with ExpenseClient(cfg, cold_start_notice=False) as client:
                    ensure_synced(client, cfg, notice_stream=io.StringIO())
            except Exception:
                pass
        accounts = load_account_name_map()
        categories = load_category_name_map()
        self.app.call_from_thread(self._set_options, accounts, categories)

    def _set_options(self, accounts: dict, categories: dict) -> None:
        self.query_one("#f-account", Select).set_options(
            [(name, aid) for aid, name in accounts.items()]
        )
        self.query_one("#f-category", Select).set_options(
            [(name, cid) for cid, name in categories.items()]
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.action_submit()

    def action_submit(self) -> None:
        title = self.query_one("#f-title", Input).value.strip()
        amount_raw = self.query_one("#f-amount", Input).value.strip()
        account = self.query_one("#f-account", Select).value
        category = self.query_one("#f-category", Select).value
        description = self.query_one("#f-description", Input).value.strip()
        cleared_raw = self.query_one("#f-cleared", Select).value

        if not title:
            self.notify("Title is required.", severity="error")
            return
        try:
            amount = int(amount_raw)
        except ValueError:
            self.notify("Amount must be an integer in signed cents (e.g. -1500).", severity="error")
            return
        if amount == 0:
            self.notify("Amount must be non-zero.", severity="error")
            return
        if account is Select.BLANK:
            self.notify("Pick an account.", severity="error")
            return
        if category is Select.BLANK:
            self.notify("Pick a category.", severity="error")
            return

        payload: dict = {
            "id": str(uuid.uuid4()),
            "title": title,
            "amount_cents": amount,
            "account_id": account,
            "category_id": category,
            "date": now_local_iso(),
        }
        if description:
            payload["description"] = description
        if cleared_raw == "yes":
            payload["cleared"] = True
        elif cleared_raw == "no":
            payload["cleared"] = False
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
