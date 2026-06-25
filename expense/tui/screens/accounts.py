"""Accounts screen — banks & people (read-only browse for Phase 1).

Built on SectionScreen + the shared CursorList. Includes people and archived
accounts (archived rows dimmed); the Color column renders the account's hex
color as a swatch. Native-currency balances (home equivalents live in
Outstanding Amounts). `enter` opens the read-only detail modal. New/edit/archive
land in Phase 2.
"""

import io

from rich.text import Text
from textual.widget import Widget
from textual.widgets import Static

from expense.commands import accounts_cmd
from expense.commands._resource import format_cents
from expense.tui.screens._base import SectionScreen
from expense.tui.screens.modals import RecordModal
from expense.tui.widgets.cursor_list import CursorList

_HEADERS = ["Name", "Type", "Cur", "Color", "Balance", "Status"]


def _swatch(color: object) -> Text:
    if isinstance(color, str) and len(color) == 7 and color.startswith("#"):
        return Text("██", style=color)
    return Text("—", style="dim")


def account_rows(items: list[dict]) -> list:
    """Pure (id, cells, base_style) rows for a CursorList. Unit-testable."""
    rows = []
    for it in items:
        archived = bool(it.get("is_archived"))
        cells = [
            it.get("name") or "(unnamed)",
            "person" if it.get("is_person") else "bank",
            it.get("currency_code") or "?",
            _swatch(it.get("color")),
            format_cents(it.get("current_balance_cents")),
            "archived" if archived else "active",
        ]
        rows.append((it.get("id"), cells, "dim" if archived else ""))
    return rows


class AccountsScreen(SectionScreen):
    crumb = ("Manage", "Accounts")
    CARD_WIDTH = 80

    def __init__(self) -> None:
        super().__init__()
        self._by_id: dict = {}

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
        return body.get("items", body) if isinstance(body, dict) else (body or [])

    def build(self, items: list) -> list[Widget]:
        self._by_id = {it.get("id"): it for it in items}
        return [
            Static(Text("Accounts — banks & people"), classes="section-title"),
            CursorList(_HEADERS, account_rows(items), align_right={4}, empty="(no accounts)"),
            Static(
                Text("balances are native currency · home equivalents in Outstanding Amounts"),
                classes="legend",
            ),
        ]

    def on_cursor_list_selected(self, event: CursorList.Selected) -> None:
        item = self._by_id.get(event.key)
        if item:
            self.app.push_screen(RecordModal(f"Account · {item.get('name') or '—'}", item))
