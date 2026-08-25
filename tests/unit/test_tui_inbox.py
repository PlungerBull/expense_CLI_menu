"""Smoke tests for the Inbox TUI screen + shared CursorList."""

import asyncio

from expense.tui.app import ExpenseApp
from expense.tui.screens.inbox import InboxScreen, inbox_rows
from expense.tui.screens.log_bar import LogBarScreen
from expense.tui.screens.quick_log import QuickAddLogScreen
from expense.tui.widgets.cursor_list import CursorList
from tests.unit.helpers import wait_for, wait_for_list

ITEMS = [
    {
        "id": "a",
        "title": "Almuerzo con cliente",
        "description": "obra",
        "amount_cents": -18000,
        "date": "2026-03-20T00:00:00Z",
        "account_id": "acc1",
        "category_id": "cat1",
        "status": 1,
        "hashtag_ids": ["tag1"],
    },
    {
        "id": "b",
        "title": "Pago internet",
        "description": "Movistar",
        "amount_cents": -12000,
        "date": "2026-03-15T00:00:00Z",
        "account_id": "acc1",
        "category_id": "cat1",
        "status": 2,
        "hashtag_ids": [],
    },
    {
        "id": "c",
        "title": "Compra ferreteria",
        "description": None,
        "amount_cents": None,
        "date": None,
        "account_id": None,
        "category_id": None,
        "status": 1,
        "hashtag_ids": [],
    },
]
ACCOUNTS = {"acc1": "BCP Soles"}
CATEGORIES = {"cat1": "Comida"}
HASHTAGS = {"tag1": "obra"}


def test_inbox_rows_glyphs_and_format():
    # Cells are asserted positionally; the Tags column landed at index 7 with
    # backlog 6.1, pushing status to 8. `align_right={3}` in the screen is an
    # index into this same list — amount must stay at 3.
    by_id = dict(inbox_rows(ITEMS, ACCOUNTS, CATEGORIES, HASHTAGS, ready_ids={"a"}))
    # ready (in ready set) → ▶, amount formatted, names resolved
    assert by_id["a"][0] == "▶" and by_id["a"][3] == "-180.00"
    assert by_id["a"][5] == "BCP Soles" and by_id["a"][6] == "Comida" and by_id["a"][8] == "pend"
    # promoted (status 2) → ✓
    assert by_id["b"][0] == "✓" and by_id["b"][8] == "prom"
    # incomplete (not ready, not promoted) → ·; null amount + unresolved refs
    assert by_id["c"][0] == "·" and by_id["c"][3] == "(null)" and by_id["c"][5] == "—"


def test_inbox_rows_render_tags():
    """Tags resolve to names; an untagged draft says `—`, never blank."""
    by_id = dict(inbox_rows(ITEMS, ACCOUNTS, CATEGORIES, HASHTAGS, ready_ids={"a"}))
    assert by_id["a"][7] == "obra"
    assert by_id["b"][7] == "—"


def test_pressing_f_cycles_filter_and_reloads(monkeypatch):
    """`f` must actually re-fetch with the new filter, not just mutate state (backlog 1.5)."""
    import expense.commands.inbox_cmd as ic
    import expense.tui.screens.inbox as inbox_mod

    monkeypatch.setattr(
        ic,
        "fetch_inbox",
        lambda *a, **k: {"items": [ITEMS[0]]} if k.get("ready") else {"items": ITEMS},
    )
    monkeypatch.setattr(inbox_mod, "load_account_name_map", lambda: ACCOUNTS)
    monkeypatch.setattr(inbox_mod, "load_category_name_map", lambda: CATEGORIES)
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            await app.push_screen(InboxScreen())
            await wait_for_list(pilot, app)
            assert len(app.screen.query_one(CursorList)._rows) == 3
            await pilot.press("f")  # all → ready
            await wait_for(
                pilot,
                lambda: (
                    app.screen.query(CursorList)
                    and len(app.screen.query_one(CursorList)._rows) == 1
                ),
            )
            legend = app.screen.query(".legend").last().render()
            assert "filter: ready" in str(legend)

    asyncio.run(scenario())


def test_inbox_screen_lists_and_opens_detail(monkeypatch):
    import expense.commands.inbox_cmd as ic
    import expense.tui.screens.inbox as inbox_mod

    monkeypatch.setattr(ic, "fetch_inbox", lambda *a, **k: {"items": ITEMS})
    monkeypatch.setattr(inbox_mod, "load_account_name_map", lambda: ACCOUNTS)
    monkeypatch.setattr(inbox_mod, "load_category_name_map", lambda: CATEGORIES)
    # the edit screen loads entities on mount — stub those too
    monkeypatch.setattr("expense.commands.accounts_cmd.fetch_accounts", lambda *a, **k: [])
    monkeypatch.setattr("expense.commands.categories_cmd.fetch_categories", lambda *a, **k: [])
    monkeypatch.setattr("expense.commands.hashtags_cmd.fetch_hashtags", lambda *a, **k: [])
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            await app.push_screen(InboxScreen())
            # worker fetched + populate mounted the list
            await wait_for_list(pilot, app)
            await pilot.press("enter")  # opens the edit screen (inbox draft)
            await wait_for(pilot, lambda: isinstance(app.screen, QuickAddLogScreen))
            assert app.screen._resource == "inbox"
            # Drafts carry hashtag_ids and the tags survive promotion, so the
            # draft form offers the same picker as a transaction (backlog 6.1).
            assert "hashtags" in app.screen._sequence()

    asyncio.run(scenario())


def test_plus_logs_a_transaction_not_a_draft(monkeypatch):
    """`+` means the same thing on every screen that has it: a posted
    transaction (option C, 2026-08-20) — the LOG bar since quick-add phase 4.
    Standing in the Inbox does not change what it writes: a line lands in the
    Inbox only when the grammar says it is too sparse to post, never because of
    where you were standing. Creating a draft outright from the TUI is still not
    possible, and `expense inbox add` remains the only way (docs/todo.md)."""
    import expense.commands.inbox_cmd as ic
    import expense.tui.screens.inbox as inbox_mod

    monkeypatch.setattr(ic, "fetch_inbox", lambda *a, **k: {"items": ITEMS})
    monkeypatch.setattr(inbox_mod, "load_account_name_map", lambda: ACCOUNTS)
    monkeypatch.setattr(inbox_mod, "load_category_name_map", lambda: CATEGORIES)
    monkeypatch.setattr(QuickAddLogScreen, "_load_entities", lambda self: None)
    monkeypatch.setattr(LogBarScreen, "_load_entities", lambda self: None)
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            await app.push_screen(InboxScreen())
            await wait_for_list(pilot, app)
            await pilot.press("+")
            await wait_for(pilot, lambda: isinstance(app.screen, LogBarScreen))
            assert app.screen._staged == []

    asyncio.run(scenario())
