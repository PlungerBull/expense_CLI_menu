"""Smoke tests for the Accounts TUI screen + CursorList enhancements."""

import asyncio

from rich.text import Text

from expense.tui.app import ExpenseApp
from expense.tui.screens.accounts import AccountsScreen, account_rows
from expense.tui.screens.create_forms import EditAccountScreen
from expense.tui.widgets.cursor_list import CursorList
from tests.unit.helpers import wait_for

ITEMS = [
    {
        "id": "a1",
        "name": "BCP Soles",
        "is_person": False,
        "is_archived": False,
        "currency_code": "PEN",
        "color": "#4a90d9",
        "current_balance_cents": 1245000,
    },
    {
        "id": "a2",
        "name": "Socio Juan",
        "is_person": True,
        "is_archived": False,
        "currency_code": "PEN",
        "color": None,
        "current_balance_cents": -150000,
    },
    {
        "id": "a3",
        "name": "Old BCP",
        "is_person": False,
        "is_archived": True,
        "currency_code": "PEN",
        "color": "#888888",
        "current_balance_cents": 0,
    },
]


def test_account_rows_type_balance_status_and_swatch():
    by_id = {r[0]: r for r in account_rows(ITEMS)}
    # bank, formatted balance, active status, colored swatch Text
    _key, cells, style = by_id["a1"]
    assert cells[1] == "bank" and cells[4] == "12,450.00" and cells[5] == "active"
    assert isinstance(cells[3], Text) and cells[3].style == "#4a90d9"
    assert style == ""
    # person row
    assert by_id["a2"][1][1] == "person"
    # archived → dim base style + status archived
    _k, cells3, style3 = by_id["a3"]
    assert cells3[5] == "archived" and style3 == "dim"


def test_accounts_screen_lists_and_edits(monkeypatch):
    import expense.commands.accounts_cmd as ac

    monkeypatch.setattr(ac, "fetch_accounts", lambda *a, **k: ITEMS)
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            await app.push_screen(AccountsScreen())
            await wait_for(
                pilot,
                lambda: (
                    app.screen.query(CursorList)
                    and not app.screen.query("#content LoadingIndicator")
                ),
            )
            cl = app.screen.query(CursorList).first()
            assert cl is not None
            await pilot.press("e")  # edit the cursor row — no detail hop
            await pilot.pause(0.05)
            assert isinstance(app.screen, EditAccountScreen)

    asyncio.run(scenario())
