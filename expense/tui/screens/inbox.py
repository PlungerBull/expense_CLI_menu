"""Inbox screen — drafts awaiting promotion, with inline write actions.

Built on SectionScreen (breadcrumb/card/worker) + the shared CursorList. Data
comes from the shared `inbox_cmd.fetch_inbox`; the per-row `rdy` glyph reuses
the engine's exact "ready" predicate (a second `fetch_inbox(ready=True)` query)
rather than reimplementing it. `f` cycles the filter, `p` promotes and `d`
deletes (each via a ConfirmModal), and `enter` opens the item in the editable
QuickAddLogScreen.
"""

from rich.text import Text
from textual.widget import Widget
from textual.widgets import Static

from expense.commands import inbox_cmd
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
from expense.tui.screens._base import PagedListMixin, SectionScreen, screen_fetch_kwargs
from expense.tui.screens.quick_log import QuickAddLogScreen
from expense.tui.theme import AMOUNT_RULE, Palette, resolve_palette
from expense.tui.widgets.cells import amount_cell
from expense.tui.widgets.cursor_list import CursorList

# Hashtags sits before St, matching the Transactions screen's column order so the
# two lists read the same way (backlog 6.1, sketch pick H). The label follows the
# engine's vocabulary — /hashtags, hashtag_ids — everywhere (backlog Phase 8,
# 2026-08-16). NOTE: ALIGN_RIGHT below is a positional index into these cells —
# check it when moving any column.
_HEADERS = ["", "Title", "Description", "Amount", "Date", "Account", "Category", "Hashtags", "St"]
_STATUS = {1: "pend", 2: "prom"}
_FILTERS = ["all", "ready", "overdue"]


def _glyph(item: dict, ready_ids: set) -> str:
    if item.get("status") == 2:
        return "✓"  # promoted
    if item.get("id") in ready_ids:
        return "▶"  # ready to promote
    return "·"  # incomplete


def inbox_rows(
    items: list[dict],
    accounts: dict,
    categories: dict,
    hashtags: dict,
    ready_ids: set,
    palette: Palette | None = None,
) -> list:
    """Pure (id, cells) rows for a CursorList. Unit-testable without a screen.

    `hashtags` is required rather than defaulted: a silently-empty map would
    render every tagged draft as short-ids in production while tests stayed green.
    """
    rows = []
    for it in items:
        cells = [
            _glyph(it, ready_ids),
            truncate(it.get("title") or "—", 18),
            truncate(it.get("description"), 16),
            amount_cell(it.get("amount_cents"), palette, AMOUNT_RULE),
            format_short_date(it.get("date")),
            resolve_name(it.get("account_id"), accounts),
            resolve_name(it.get("category_id"), categories),
            format_hashtag_cell(it.get("hashtag_ids"), hashtags, max_width=20),
            _STATUS.get(it.get("status"), "—"),
        ]
        rows.append((it.get("id"), cells))
    return rows


class InboxScreen(PagedListMixin, SectionScreen):
    crumb = ("Capture & ledger", "Inbox")
    CARD_WIDTH = 110  # matches Transactions since the Hashtags column landed (backlog 6.1)
    BINDINGS = [
        ("f", "cycle_filter", "Filter"),
        ("p", "promote", "Promote"),
        ("d", "delete", "Delete"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._filter = "all"
        self._by_id: dict = {}

    def list_extra_lines(self) -> int:
        return 2  # the glyph/filter legend below the list (margin-top 1 + text)

    def fetch(self) -> dict:
        from expense import config as config_module

        cfg = config_module.ensure_loaded()
        kw = screen_fetch_kwargs(self.app)
        body = self.fetch_page_body(
            lambda pkw: inbox_cmd.fetch_inbox(
                cfg, ready=self._filter == "ready", overdue=self._filter == "overdue", **pkw, **kw
            )
        )
        items = items_of(body)
        # Mark readiness with the engine's own predicate (a second ready=True
        # query), not a reimplementation.
        rb = inbox_cmd.fetch_inbox(cfg, ready=True, **kw)
        ready_ids: set = {it.get("id") for it in items_of(rb)}
        return {
            "items": items,
            "ready_ids": ready_ids,
            "accounts": load_account_name_map(),
            "categories": load_category_name_map(),
            # Resolved worker-side, never in build(): a reference read on the
            # render path blocks first paint (same rule as outstanding.py).
            "hashtags": load_hashtag_name_map(),
        }

    def build(self, data: dict) -> list[Widget]:
        items = data["items"]
        self._by_id = {it.get("id"): it for it in items}
        rows = inbox_rows(
            items,
            data["accounts"],
            data["categories"],
            data["hashtags"],
            data["ready_ids"],
            palette=resolve_palette(self.app),
        )
        return [
            CursorList(
                _HEADERS,
                rows,
                align_right={3},
                empty="(no inbox items)",
                title="Inbox — capture now, complete later",
                page_size=self.page_rows,
                page_meta=self.page_meta(),
            ),
            Static(
                Text(f"▶ ready · · incomplete · ✓ promoted        filter: {self._filter}"),
                classes="legend",
            ),
        ]

    async def action_cycle_filter(self) -> None:
        i = _FILTERS.index(self._filter)
        self._filter = _FILTERS[(i + 1) % len(_FILTERS)]
        self.reset_page()  # a new filter invalidates the old offset
        await self.action_reload()

    def action_promote(self) -> None:
        item = self.selected_record()
        if not item:
            return
        title = item.get("title") or "—"
        self.confirm_write(
            "Promote to ledger?",
            f"Create a real transaction from “{title}” and soft-delete the draft. "
            "The engine rejects items missing required fields.",
            "POST",
            f"/inbox/{item['id']}/promote",
            success="Promoted to ledger.",
        )

    def action_delete(self) -> None:
        item = self.selected_record()
        if not item:
            return
        self.confirm_write(
            "Delete inbox item?",
            f"Dismiss the draft “{item.get('title') or '—'}”. "
            "Dismissal is final — there is no restore.",
            "DELETE",
            f"/inbox/{item['id']}",
            success="Deleted.",
        )

    def on_cursor_list_selected(self, event: CursorList.Selected) -> None:
        item = self._by_id.get(event.key)
        if item:
            self.app.push_screen(
                QuickAddLogScreen(record=item, resource="inbox"),
                lambda _result: self._load(),  # refresh the list after editing
            )
