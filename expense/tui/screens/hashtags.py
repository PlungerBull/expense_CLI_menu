"""Hashtags screen — cross-cutting tags.

A plain list (Name / Status), consistent with the other list screens, rather
than the chip mockup — usage counts would need engine support the list endpoint
doesn't provide. Archived rows dimmed. `n` creates; `e` renames the cursor row
(prefilled EditHashtagScreen); `a` toggles archive immediately — a second `a`
undoes. `enter` does nothing.
"""

from expense.commands import hashtags_cmd
from expense.tui.screens._base import ResourceListScreen

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


class HashtagsScreen(ResourceListScreen):
    crumb = ("Manage", "Hashtags")
    CARD_WIDTH = 48
    TITLE = "Hashtags — tag across categories & accounts"
    HEADERS = _HEADERS
    EMPTY = "(no hashtags)"
    RESOURCE = "hashtags"

    def fetch_items(self, cfg, **kw):
        return hashtags_cmd.fetch_hashtags(cfg, include_archived=True, **kw)

    def rows(self, items: list) -> list:
        return hashtag_rows(items)

    def edit_screen(self, item: dict):
        from expense.tui.screens.create_forms import EditHashtagScreen

        return EditHashtagScreen(item)

    def new_screen(self):
        from expense.tui.screens.create_forms import NewHashtagScreen

        return NewHashtagScreen()
