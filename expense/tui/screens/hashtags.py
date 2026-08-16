"""Hashtags screen — cross-cutting tags.

A plain name list, consistent with the other list screens, rather than the
chip mockup — usage counts would need engine support the list endpoint
doesn't provide. `n` creates; `e` renames the cursor row (prefilled
EditHashtagScreen). `enter` does nothing. Hashtag archive was removed
engine-side (2026-08-06 schema slimming) — only accounts archive now.
"""

from expense.commands import hashtags_cmd
from expense.tui.screens._base import ResourceListScreen

_HEADERS = ["Name"]


def hashtag_rows(items: list[dict]) -> list:
    """Pure (id, cells, base_style) rows for a CursorList. Unit-testable."""
    rows = []
    for it in items:
        name = it.get("name") or "(unnamed)"
        rows.append((it.get("id"), ["#" + name.lstrip("#")], ""))
    return rows


class HashtagsScreen(ResourceListScreen):
    crumb = ("Manage", "Hashtags")
    CARD_WIDTH = 48
    TITLE = "Hashtags — tag across categories & accounts"
    HEADERS = _HEADERS
    EMPTY = "(no hashtags)"
    RESOURCE = "hashtags"

    def fetch_items(self, cfg, **kw):
        # All pages, not the engine default page: the 20-row window needs
        # the full set for an honest "page 2 of N" (2026-07-11 pagination).
        from expense.commands._resource import fetch_all_pages

        return fetch_all_pages(
            lambda limit, offset: hashtags_cmd.fetch_hashtags(cfg, limit=limit, offset=offset, **kw)
        )

    def rows(self, items: list) -> list:
        return hashtag_rows(items)

    def edit_screen(self, item: dict):
        from expense.tui.screens.create_forms import EditHashtagScreen

        return EditHashtagScreen(item)

    def new_screen(self):
        from expense.tui.screens.create_forms import NewHashtagScreen

        return NewHashtagScreen()
