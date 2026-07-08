"""Accounts screen — banks & people.

Built on SectionScreen + the shared CursorList. Includes people and archived
accounts (archived rows dimmed); the Color column renders the account's hex
color as a swatch. Native-currency balances (home equivalents live in
Outstanding Amounts). `n` creates; `enter` opens the record detail
(AccountDetailScreen), where `e` edits and `a` archives.
"""

import io

from rich.text import Text
from textual.widget import Widget
from textual.widgets import Static

from expense.commands import accounts_cmd
from expense.commands._resource import items_of
from expense.tui.screens._base import SectionScreen
from expense.tui.screens.manage_detail import AccountDetailScreen
from expense.tui.theme import AMOUNT_RULE, Palette, resolve_palette
from expense.tui.widgets.cells import amount_cell, swatch
from expense.tui.widgets.cursor_list import CursorList

_HEADERS = ["Name", "Type", "Cur", "Color", "Balance", "Status"]


def account_rows(items: list[dict], palette: Palette | None = None) -> list:
    """Pure (id, cells, base_style) rows for a CursorList. Unit-testable."""
    rows = []
    for it in items:
        archived = bool(it.get("is_archived"))
        cells = [
            it.get("name") or "(unnamed)",
            "person" if it.get("is_person") else "bank",
            it.get("currency_code") or "?",
            swatch(it.get("color")),
            amount_cell(it.get("current_balance_cents"), palette, AMOUNT_RULE),
            "archived" if archived else "active",
        ]
        rows.append((it.get("id"), cells, "dim" if archived else ""))
    return rows


class AccountsScreen(SectionScreen):
    crumb = ("Manage", "Accounts")
    CARD_WIDTH = 80
    BINDINGS = [("n", "new", "New")]  # archive lives on the detail (enter), not the list

    def __init__(self) -> None:
        super().__init__()
        self._by_id: dict = {}

    def action_new(self) -> None:
        from expense.tui.screens.create_forms import NewAccountScreen

        self.app.push_screen(NewAccountScreen(), lambda _result: self._load())

    def fetch(self) -> list:
        from expense import config as config_module

        cfg = config_module.ensure_loaded()
        body = accounts_cmd.fetch_accounts(
            cfg,
            include_archived=True,
            include_people=True,
            no_cache=self.app._no_cache,
            verbose=self.app._verbose,
            cold_start_notice=False,
            notice_stream=io.StringIO(),
        )
        return items_of(body)

    def build(self, items: list) -> list[Widget]:
        self._by_id = {it.get("id"): it for it in items}
        return [
            Static(Text("Accounts — banks & people"), classes="section-title"),
            CursorList(
                _HEADERS,
                account_rows(items, palette=resolve_palette(self.app)),
                align_right={4},
                empty="(no accounts)",
            ),
            Static(
                Text("balances are native currency · home equivalents in Outstanding Amounts"),
                classes="legend",
            ),
        ]

    def on_cursor_list_selected(self, event: CursorList.Selected) -> None:
        item = self._by_id.get(event.key)
        if item:
            self.app.push_screen(AccountDetailScreen(item), lambda _result: self._load())
