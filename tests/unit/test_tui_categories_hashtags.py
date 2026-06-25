"""Smoke tests for the Categories and Hashtags TUI screens."""

import asyncio

from rich.text import Text

from expense.tui.app import ExpenseApp
from expense.tui.screens.categories import CategoriesScreen, category_rows
from expense.tui.screens.hashtags import HashtagsScreen, hashtag_rows
from expense.tui.screens.modals import RecordModal
from expense.tui.widgets.cursor_list import CursorList

CATS = [
    {"id": "c1", "name": "Comida", "color": "#d9744a", "is_system": False, "is_archived": False},
    {"id": "c2", "name": "@Transfer", "color": None, "is_system": True, "is_archived": False},
    {"id": "c3", "name": "Cripto", "color": None, "is_system": False, "is_archived": True},
]
TAGS = [
    {"id": "h1", "name": "trabajo", "is_archived": False},
    {"id": "h2", "name": "#casa", "is_archived": False},
    {"id": "h3", "name": "black-friday", "is_archived": True},
]


def test_category_rows_swatch_system_and_archived():
    by_id = {r[0]: r for r in category_rows(CATS)}
    _k, cells, style = by_id["c1"]
    assert isinstance(cells[0], Text) and cells[0].style == "#d9744a"
    assert cells[1] == "Comida" and cells[2] == "—" and cells[3] == "active" and style == ""
    assert by_id["c2"][1][2] == "system 🔒"  # system marker
    assert by_id["c3"][1][3] == "archived" and by_id["c3"][2] == "dim"


def test_hashtag_rows_hash_prefix_and_status():
    by_id = {r[0]: r for r in hashtag_rows(TAGS)}
    assert by_id["h1"][1][0] == "#trabajo"  # prefix added
    assert by_id["h2"][1][0] == "#casa"  # no double-hash
    assert by_id["h3"][1][1] == "archived" and by_id["h3"][2] == "dim"


def _run_list_screen(monkeypatch, screen_cls, fetch_mod, fetch_name, items):
    monkeypatch.setattr(fetch_mod, fetch_name, lambda *a, **k: {"items": items})
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            await app.push_screen(screen_cls())
            cl = None
            for _ in range(50):
                await pilot.pause(0.02)
                found = app.screen.query(CursorList)
                if found and not app.screen.query("#content LoadingIndicator"):
                    cl = found.first()
                    break
            assert cl is not None
            await pilot.press("enter")
            await pilot.pause(0.05)
            assert isinstance(app.screen, RecordModal)

    asyncio.run(scenario())


def test_categories_screen_lists_and_opens_detail(monkeypatch):
    import expense.commands.categories_cmd as cc

    _run_list_screen(monkeypatch, CategoriesScreen, cc, "fetch_categories", CATS)


def test_hashtags_screen_lists_and_opens_detail(monkeypatch):
    import expense.commands.hashtags_cmd as hc

    _run_list_screen(monkeypatch, HashtagsScreen, hc, "fetch_hashtags", TAGS)
