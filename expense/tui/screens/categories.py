"""Categories screen — spending buckets.

Color swatch + system-lock marker. `n` creates; `e` edits the cursor row
(prefilled EditCategoryScreen). `enter` does nothing. System categories
(@Transfer, @Debt) can be renamed/recolored (the engine keys them by
`system_key`, not name) but cannot be deleted. Category archive was removed
engine-side (2026-08-06 schema slimming) — only accounts archive now.
"""

from expense.commands import categories_cmd
from expense.tui.screens._base import ResourceListScreen
from expense.tui.widgets.cells import swatch

_HEADERS = ["Color", "Name", "System"]


def category_rows(items: list[dict]) -> list:
    """Pure (id, cells, base_style) rows for a CursorList. Unit-testable."""
    rows = []
    for it in items:
        cells = [
            swatch(it.get("color")),
            it.get("name") or "(unnamed)",
            "system 🔒" if it.get("is_system") else "—",
        ]
        rows.append((it.get("id"), cells, ""))
    return rows


class CategoriesScreen(ResourceListScreen):
    crumb = ("Manage", "Categories")
    CARD_WIDTH = 60
    TITLE = "Categories — buckets for every transaction"
    HEADERS = _HEADERS
    EMPTY = "(no categories)"
    LEGEND = "system categories (@Transfer, @Debt) can be renamed but not deleted"
    RESOURCE = "categories"

    def fetch_items(self, cfg, **kw):
        # All pages, not the engine default page: the 20-row window needs
        # the full set for an honest "page 2 of N" (2026-07-11 pagination).
        from expense.commands._resource import fetch_all_pages

        return fetch_all_pages(
            lambda limit, offset: categories_cmd.fetch_categories(
                cfg, limit=limit, offset=offset, **kw
            )
        )

    def rows(self, items: list) -> list:
        return category_rows(items)

    def edit_screen(self, item: dict):
        from expense.tui.screens.create_forms import EditCategoryScreen

        return EditCategoryScreen(item)

    def new_screen(self):
        from expense.tui.screens.create_forms import NewCategoryScreen

        return NewCategoryScreen()
