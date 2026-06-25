"""Smoke tests for the Inbox TUI screen + shared CursorList."""

import asyncio

from expense.tui.app import ExpenseApp
from expense.tui.screens.inbox import InboxScreen, inbox_rows
from expense.tui.screens.modals import RecordModal
from expense.tui.widgets.cursor_list import CursorList

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
    },
]
ACCOUNTS = {"acc1": "BCP Soles"}
CATEGORIES = {"cat1": "Comida"}


def test_inbox_rows_glyphs_and_format():
    by_id = dict(inbox_rows(ITEMS, ACCOUNTS, CATEGORIES, ready_ids={"a"}))
    # ready (in ready set) → ▶, amount formatted, names resolved
    assert by_id["a"][0] == "▶" and by_id["a"][3] == "-180.00"
    assert by_id["a"][5] == "BCP Soles" and by_id["a"][6] == "Comida" and by_id["a"][7] == "pend"
    # promoted (status 2) → ✓
    assert by_id["b"][0] == "✓" and by_id["b"][7] == "prom"
    # incomplete (not ready, not promoted) → ·; null amount + unresolved refs
    assert by_id["c"][0] == "·" and by_id["c"][3] == "(null)" and by_id["c"][5] == "—"


def test_inbox_screen_lists_and_opens_detail(monkeypatch):
    import expense.commands.inbox_cmd as ic
    import expense.tui.screens.inbox as inbox_mod

    monkeypatch.setattr(ic, "fetch_inbox", lambda *a, **k: {"items": ITEMS})
    monkeypatch.setattr(inbox_mod, "load_account_name_map", lambda: ACCOUNTS)
    monkeypatch.setattr(inbox_mod, "load_category_name_map", lambda: CATEGORIES)
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())

    async def scenario():
        app = ExpenseApp(no_cache=True)  # skips the ready-set second fetch
        async with app.run_test() as pilot:
            await app.push_screen(InboxScreen())
            cl = None
            for _ in range(50):
                await pilot.pause(0.02)
                found = app.screen.query(CursorList)
                if found and not app.screen.query("#content LoadingIndicator"):
                    cl = found.first()
                    break
            assert cl is not None  # worker fetched + populate mounted the list
            await pilot.press("enter")  # open the read-only detail modal
            await pilot.pause(0.05)
            assert isinstance(app.screen, RecordModal)

    asyncio.run(scenario())
