"""Hashtags screen — cross-cutting tags (read-only browse for Phase 1).

A plain list (Name / Status), consistent with the other list screens, rather
than the chip mockup — usage counts would need engine support the list endpoint
doesn't provide. Archived rows dimmed; `enter` opens the detail modal.
New/rename/archive land in Phase 2.
"""

import io

from rich.text import Text
from textual.widget import Widget
from textual.widgets import Static

from expense.commands import hashtags_cmd
from expense.tui.screens._base import SectionScreen
from expense.tui.screens.modals import RecordModal
from expense.tui.widgets.cursor_list import CursorList

_HEADERS = ["Name", "Status"]


def hashtag_rows(items: list[dict]) -> list:
    """Pure (id, cells, base_style) rows for a CursorList. Unit-testable."""
    rows = []
    for it in items:
        archived = bool(it.get("is_archived"))
        name = it.get("name") or "(unnamed)"
        cells = ["#" + name.lstrip("#"), "archived" if archived else "active"]
        rows.append((it.get("id"), cells, "dim" if archived else ""))
    return rows


class HashtagsScreen(SectionScreen):
    crumb = ("Manage", "Hashtags")
    CARD_WIDTH = 48

    def __init__(self) -> None:
        super().__init__()
        self._by_id: dict = {}

    def fetch(self) -> list:
        from expense import config as config_module

        cfg = config_module.ensure_loaded()
        body = hashtags_cmd.fetch_hashtags(
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
        return [
            Static(Text("Hashtags — tag across categories & accounts"), classes="section-title"),
            CursorList(_HEADERS, hashtag_rows(items), empty="(no hashtags)"),
        ]

    def on_cursor_list_selected(self, event: CursorList.Selected) -> None:
        item = self._by_id.get(event.key)
        if item:
            self.app.push_screen(RecordModal(f"Hashtag · {item.get('name') or '—'}", item))
