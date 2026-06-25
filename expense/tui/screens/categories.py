"""Categories screen — spending buckets (read-only browse for Phase 1).

Color swatch + system-lock marker; archived rows dimmed. `enter` opens the
detail modal. New/edit/recolor/archive land in Phase 2.
"""

import io

from rich.text import Text
from textual.widget import Widget
from textual.widgets import Static

from expense.commands import categories_cmd
from expense.tui.screens._base import SectionScreen
from expense.tui.screens.modals import RecordModal
from expense.tui.widgets.cells import swatch
from expense.tui.widgets.cursor_list import CursorList

_HEADERS = ["Color", "Name", "System", "Status"]


def category_rows(items: list[dict]) -> list:
    """Pure (id, cells, base_style) rows for a CursorList. Unit-testable."""
    rows = []
    for it in items:
        archived = bool(it.get("is_archived"))
        cells = [
            swatch(it.get("color")),
            it.get("name") or "(unnamed)",
            "system 🔒" if it.get("is_system") else "—",
            "archived" if archived else "active",
        ]
        rows.append((it.get("id"), cells, "dim" if archived else ""))
    return rows


class CategoriesScreen(SectionScreen):
    crumb = ("Manage", "Categories")
    CARD_WIDTH = 60
    BINDINGS = [("a", "archive", "Archive")]

    def __init__(self) -> None:
        super().__init__()
        self._by_id: dict = {}

    def action_archive(self) -> None:
        self.archive_selected("categories", "category")

    def fetch(self) -> list:
        from expense import config as config_module

        cfg = config_module.ensure_loaded()
        body = categories_cmd.fetch_categories(
            cfg,
            include_archived=True,
            no_cache=self.app._no_cache,
            verbose=self.app._verbose,
            cold_start_notice=False,
            notice_stream=io.StringIO(),
        )
        return body.get("items", body) if isinstance(body, dict) else (body or [])

    def build(self, items: list) -> list[Widget]:
        self._by_id = {it.get("id"): it for it in items}
        note = "system categories (@Transfer, @Debt) cannot be renamed"
        return [
            Static(Text("Categories — buckets for every transaction"), classes="section-title"),
            CursorList(_HEADERS, category_rows(items), empty="(no categories)"),
            Static(Text(note), classes="legend"),
        ]

    def on_cursor_list_selected(self, event: CursorList.Selected) -> None:
        item = self._by_id.get(event.key)
        if item:
            self.app.push_screen(RecordModal(f"Category · {item.get('name') or '—'}", item))
