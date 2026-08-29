"""Transactions screen — the posted ledger.

Built on SectionScreen + the shared CursorList. Fetch-paged (PagedListMixin —
real limit/offset against the engine, sized to the terminal ≤20 rows;
pgdn/. turns the page); `enter` opens the record in the editable
QuickAddLogScreen and `+` opens an empty one (`LogTransactionMixin`). No `cl`
glyph column (dropped per request); interactive filters and search land in a
later pass.
"""

from textual.widget import Widget

from expense.commands import transactions_cmd
from expense.commands._resource import (
    ENGINE_PAGE_CAP,
    format_hashtag_cell,
    format_short_date,
    items_of,
    load_account_name_map,
    load_category_name_map,
    load_hashtag_name_map,
    resolve_name,
    truncate,
)
from expense.tui.screens._base import (
    LogTransactionMixin,
    PagedListMixin,
    SectionScreen,
    screen_fetch_kwargs,
)
from expense.tui.screens.quick_log import QuickAddLogScreen
from expense.tui.theme import AMOUNT_RULE, PALETTE, Palette
from expense.tui.widgets.cells import amount_cell
from expense.tui.widgets.cursor_list import CursorList

_HEADERS = ["Title", "Description", "Amount", "Date", "Account", "Cat", "Hashtags"]


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


class TransactionsScreen(LogTransactionMixin, PagedListMixin, SectionScreen):
    BINDINGS = [*LogTransactionMixin.BINDINGS]
    crumb = ("Capture & ledger", "Transactions")
    # None = the card fills the terminal width, and PAGE_ROWS_CAP lets the page
    # fill its height: the ledger is the screen you sit in, so it takes the
    # window you gave it instead of holding a 110x20 card in the corner of a
    # large one (2026-08-29). The cap is the engine's own `limit` ceiling.
    CARD_WIDTH = None
    PAGE_ROWS_CAP = ENGINE_PAGE_CAP

    def __init__(self) -> None:
        super().__init__()
        self._by_id: dict = {}

    def fetch(self) -> dict:
        from expense import config as config_module

        cfg = config_module.ensure_loaded()
        kw = screen_fetch_kwargs(self.app)
        body = self.fetch_page_body(
            lambda pkw: transactions_cmd.fetch_transactions(cfg, **pkw, **kw)
        )
        return {
            "items": items_of(body),
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
            palette=PALETTE,
        )
        # Panel title absorbs the old title + legend rows; the border subtitle
        # carries the page status (picks B/A, 2026-07-11).
        return [
            CursorList(
                _HEADERS,
                rows,
                align_right={2},
                empty="(no transactions)",
                title="Ledger — posted transactions · most recent first",
                page_size=self.page_rows,
                page_meta=self.page_meta(),
            ),
        ]

    def _after_log(self, _result=None) -> None:
        self._load()  # a transaction written with `+` belongs in this list now

    def on_cursor_list_selected(self, event: CursorList.Selected) -> None:
        item = self._by_id.get(event.key)
        if item:
            self.app.push_screen(
                QuickAddLogScreen(record=item, resource="transactions"),
                lambda _result: self._load(),  # refresh the list after editing
            )
