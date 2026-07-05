"""Smoke tests for the Transactions TUI screen."""

import asyncio

from expense.tui.app import ExpenseApp
from expense.tui.screens.quick_log import QuickAddLogScreen
from expense.tui.screens.transactions import TransactionsScreen, transaction_rows
from expense.tui.widgets.cursor_list import CursorList
from tests.unit.helpers import wait_for

ITEMS = [
    {
        "id": "t1",
        "title": "Sueldo marzo",
        "description": "Planilla",
        "amount_cents": 651900,
        "date": "2026-03-05T00:00:00Z",
        "account_id": "acc1",
        "category_id": "cat1",
        "hashtag_ids": ["h1"],
    },
    {
        "id": "t2",
        "title": "Supermercado",
        "description": None,
        "amount_cents": -43250,
        "date": "2026-03-12T00:00:00Z",
        "account_id": "acc1",
        "category_id": "cat2",
        "hashtag_ids": [],
    },
]
ACCOUNTS = {"acc1": "BCP Soles"}
CATEGORIES = {"cat1": "Ingreso", "cat2": "Comida"}
HASHTAGS = {"h1": "trabajo"}


def test_transaction_rows_format_and_resolve():
    by_id = dict(transaction_rows(ITEMS, ACCOUNTS, CATEGORIES, HASHTAGS))
    # amount grouped, account/category resolved, tags resolved
    assert by_id["t1"][2] == "6,519.00" and by_id["t1"][4] == "BCP Soles"
    assert by_id["t1"][5] == "Ingreso" and by_id["t1"][6] == "trabajo"
    # no tags → em dash; negative amount formatted
    assert by_id["t2"][2] == "-432.50" and by_id["t2"][6] == "—"


def test_transactions_screen_lists_and_opens_detail(monkeypatch):
    import expense.commands.transactions_cmd as tc
    import expense.tui.screens.transactions as tx_mod

    monkeypatch.setattr(tc, "fetch_transactions", lambda *a, **k: {"items": ITEMS, "total": 2})
    monkeypatch.setattr(tx_mod, "load_account_name_map", lambda: ACCOUNTS)
    monkeypatch.setattr(tx_mod, "load_category_name_map", lambda: CATEGORIES)
    monkeypatch.setattr(tx_mod, "load_hashtag_name_map", lambda: HASHTAGS)
    # the edit screen loads entities on mount — stub those too
    monkeypatch.setattr("expense.commands.accounts_cmd.fetch_accounts", lambda *a, **k: [])
    monkeypatch.setattr("expense.commands.categories_cmd.fetch_categories", lambda *a, **k: [])
    monkeypatch.setattr("expense.commands.hashtags_cmd.fetch_hashtags", lambda *a, **k: [])
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            await app.push_screen(TransactionsScreen())
            await wait_for(
                pilot,
                lambda: (
                    app.screen.query(CursorList)
                    and not app.screen.query("#content LoadingIndicator")
                ),
            )
            await pilot.press("enter")  # opens the edit screen, pre-filled
            await pilot.pause(0.05)
            assert isinstance(app.screen, QuickAddLogScreen)
            assert app.screen._mode == "edit" and app.screen._values["amount"] == 651900

    asyncio.run(scenario())
