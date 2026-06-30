"""Inbox screen — drafts awaiting promotion (read-only browse for Phase 1).

Built on SectionScreen (breadcrumb/card/worker) + the shared CursorList. Data
comes from the shared `inbox_cmd.fetch_inbox`; the per-row `rdy` glyph reuses
the cache's exact "ready" predicate (a second `fetch_inbox(ready=True)` query)
rather than reimplementing it. `enter` opens a read-only detail modal; `f`
cycles the filter. Writes (add/edit/promote/delete) land in Phase 2.
"""

import io

from rich.text import Text
from textual.widget import Widget
from textual.widgets import Static

from expense.commands import inbox_cmd
from expense.commands._resource import (
    format_cents,
    format_short_date,
    load_account_name_map,
    load_category_name_map,
    resolve_name,
    truncate,
)
from expense.tui.screens._base import SectionScreen
from expense.tui.screens.quick_log import QuickAddLogScreen
from expense.tui.widgets.cursor_list import CursorList

_HEADERS = ["", "Title", "Description", "Amount", "Date", "Account", "Category", "St"]
_STATUS = {1: "pend", 2: "prom"}
_FILTERS = ["all", "ready", "overdue"]


def _glyph(item: dict, ready_ids: set) -> str:
    if item.get("status") == 2:
        return "✓"  # promoted
    if item.get("id") in ready_ids:
        return "▶"  # ready to promote
    return "·"  # incomplete


def inbox_rows(items: list[dict], accounts: dict, categories: dict, ready_ids: set) -> list:
    """Pure (id, cells) rows for a CursorList. Unit-testable without a screen."""
    rows = []
    for it in items:
        cells = [
            _glyph(it, ready_ids),
            truncate(it.get("title") or "—", 18),
            truncate(it.get("description"), 16),
            format_cents(it.get("amount_cents")),
            format_short_date(it.get("date")),
            resolve_name(it.get("account_id"), accounts),
            resolve_name(it.get("category_id"), categories),
            _STATUS.get(it.get("status"), "—"),
        ]
        rows.append((it.get("id"), cells))
    return rows


class InboxScreen(SectionScreen):
    crumb = ("Capture & ledger", "Inbox")
    CARD_WIDTH = 100
    BINDINGS = [
        ("f", "cycle_filter", "Filter"),
        ("p", "promote", "Promote"),
        ("d", "delete", "Delete"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._filter = "all"
        self._by_id: dict = {}

    def fetch(self) -> dict:
        from expense import config as config_module

        cfg = config_module.ensure_loaded()
        kw = dict(
            no_cache=self.app._no_cache,
            verbose=self.app._verbose,
            cold_start_notice=False,
            notice_stream=io.StringIO(),
        )
        body = inbox_cmd.fetch_inbox(
            cfg, ready=self._filter == "ready", overdue=self._filter == "overdue", **kw
        )
        items = body.get("items", body) if isinstance(body, dict) else (body or [])
        # Mark readiness with the engine's own predicate (cache ready filter),
        # not a reimplementation. Skipped in stateless mode (no cache filter).
        ready_ids: set = set()
        if not self.app._no_cache:
            rb = inbox_cmd.fetch_inbox(cfg, ready=True, **kw)
            ritems = rb.get("items", rb) if isinstance(rb, dict) else (rb or [])
            ready_ids = {it.get("id") for it in ritems}
        return {
            "items": items,
            "ready_ids": ready_ids,
            "accounts": load_account_name_map(),
            "categories": load_category_name_map(),
        }

    def build(self, data: dict) -> list[Widget]:
        items = data["items"]
        self._by_id = {it.get("id"): it for it in items}
        rows = inbox_rows(items, data["accounts"], data["categories"], data["ready_ids"])
        return [
            Static(Text("Inbox — capture now, complete later"), classes="section-title"),
            CursorList(_HEADERS, rows, align_right={3}, empty="(no inbox items)"),
            Static(
                Text(f"▶ ready · · incomplete · ✓ promoted        filter: {self._filter}"),
                classes="legend",
            ),
        ]

    def action_cycle_filter(self) -> None:
        i = _FILTERS.index(self._filter)
        self._filter = _FILTERS[(i + 1) % len(_FILTERS)]
        self.action_reload()

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
            f"Soft-delete the draft “{item.get('title') or '—'}”.",
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
