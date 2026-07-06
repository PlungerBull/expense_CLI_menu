"""Transactions screen — the posted ledger (read-only browse for Phase 1).

Built on SectionScreen + the shared CursorList. Loads the most recent page via
the shared `transactions_cmd.fetch_transactions`; `enter` opens the read-only
detail modal. No `cl` glyph column (dropped per request); interactive filters,
search, and edit land in a later pass.
"""

import io

from rich.text import Text
from textual.widget import Widget
from textual.widgets import Static

from expense.commands import transactions_cmd
from expense.commands._resource import (
    format_hashtag_cell,
    format_short_date,
    items_of,
    load_account_name_map,
    load_category_name_map,
    load_hashtag_name_map,
    resolve_name,
    truncate,
)
from expense.tui.screens._base import SectionScreen
from expense.tui.screens.quick_log import QuickAddLogScreen
from expense.tui.theme import AMOUNT_RULE, Palette, resolve_palette
from expense.tui.widgets.cells import amount_cell
from expense.tui.widgets.cursor_list import CursorList

_HEADERS = ["Title", "Description", "Amount", "Date", "Account", "Cat", "Tags"]
_PAGE = 50


def transaction_rows(
    items: list[dict],
    accounts: dict,
    categories: dict,
    hashtags: dict,
    palette: Palette | None = None,
) -> list:
    """Pure (id, cells) rows for a CursorList. Unit-testable without a screen."""
    rows = []
    for it in items:
        rows.append(
            (
                it.get("id"),
                [
                    truncate(it.get("title") or "—", 20),
                    truncate(it.get("description"), 18),
                    amount_cell(it.get("amount_cents"), palette, AMOUNT_RULE),
                    format_short_date(it.get("date")),
                    resolve_name(it.get("account_id"), accounts),
                    resolve_name(it.get("category_id"), categories),
                    format_hashtag_cell(it.get("hashtag_ids"), hashtags, max_width=20),
                ],
            )
        )
    return rows


class TransactionsScreen(SectionScreen):
    crumb = ("Capture & ledger", "Transactions")
    CARD_WIDTH = 110

    def __init__(self) -> None:
        super().__init__()
        self._by_id: dict = {}

    def fetch(self) -> dict:
        from expense import config as config_module

        cfg = config_module.ensure_loaded()
        body = transactions_cmd.fetch_transactions(
            cfg,
            limit=_PAGE,
            offset=0,
            no_cache=self.app._no_cache,
            verbose=self.app._verbose,
            cold_start_notice=False,
            notice_stream=io.StringIO(),
        )
        items = items_of(body)
        total = body.get("total") if isinstance(body, dict) else None
        return {
            "items": items,
            "total": total,
            "accounts": load_account_name_map(),
            "categories": load_category_name_map(),
            "hashtags": load_hashtag_name_map(),
        }

    def build(self, data: dict) -> list[Widget]:
        items = data["items"]
        self._by_id = {it.get("id"): it for it in items}
        rows = transaction_rows(
            items,
            data["accounts"],
            data["categories"],
            data["hashtags"],
            palette=resolve_palette(self.app),
        )
        shown = len(rows)
        total = data["total"]
        count = f"showing {shown} of {total}" if isinstance(total, int) else f"showing {shown}"
        return [
            Static(Text("Ledger — posted transactions"), classes="section-title"),
            CursorList(_HEADERS, rows, align_right={2}, empty="(no transactions)"),
            Static(Text(f"{count}   ·   most recent first"), classes="legend"),
        ]

    def on_cursor_list_selected(self, event: CursorList.Selected) -> None:
        item = self._by_id.get(event.key)
        if item:
            self.app.push_screen(
                QuickAddLogScreen(record=item, resource="transactions"),
                lambda _result: self._load(),  # refresh the list after editing
            )
