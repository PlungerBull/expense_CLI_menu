"""Hashtags screen — cross-cutting tags.

A plain list (Name / Status), consistent with the other list screens, rather
than the chip mockup — usage counts would need engine support the list endpoint
doesn't provide. Archived rows dimmed. `n` creates; `enter` opens the record
detail (HashtagDetailScreen), where `e` renames and `a` archives.
"""

import io

from rich.text import Text
from textual.widget import Widget
from textual.widgets import Static

from expense.commands import hashtags_cmd
from expense.commands._resource import items_of
from expense.tui.screens._base import SectionScreen
from expense.tui.screens.manage_detail import HashtagDetailScreen
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
    BINDINGS = [("n", "new", "New")]  # archive lives on the detail (enter), not the list

    def __init__(self) -> None:
        super().__init__()
        self._by_id: dict = {}

    def action_new(self) -> None:
        from expense.tui.screens.create_forms import NewHashtagScreen

        self.app.push_screen(NewHashtagScreen(), lambda _result: self._load())

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
        return items_of(body)

    def build(self, items: list) -> list[Widget]:
        self._by_id = {it.get("id"): it for it in items}
        return [
            Static(Text("Hashtags — tag across categories & accounts"), classes="section-title"),
            CursorList(_HEADERS, hashtag_rows(items), empty="(no hashtags)"),
        ]

    def on_cursor_list_selected(self, event: CursorList.Selected) -> None:
        item = self._by_id.get(event.key)
        if item:
            self.app.push_screen(HashtagDetailScreen(item), lambda _result: self._load())
