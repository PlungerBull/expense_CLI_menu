"""Phase 2 write-action smoke tests (Inbox promote/delete, Accounts archive).

Uses a fake HTTP client so nothing real is mutated — asserts the right
engine endpoint would be called via the ConfirmModal → run_write path.
"""

import asyncio

from expense.tui.app import ExpenseApp
from expense.tui.screens.accounts import AccountsScreen
from expense.tui.screens.inbox import InboxScreen
from expense.tui.screens.modals import ConfirmModal
from tests.unit.helpers import wait_for

INBOX = [{"id": "i1", "title": "Almuerzo", "status": 1, "amount_cents": -1000}]
ACCOUNTS = [{"id": "a1", "name": "BCP", "is_person": False, "is_archived": False, "color": None}]


async def _drive(app, screen, key, fake_client):
    async with app.run_test() as pilot:
        await app.push_screen(screen)
        from expense.tui.widgets.cursor_list import CursorList

        await wait_for(
            pilot,
            lambda: (
                app.screen.query(CursorList) and not app.screen.query("#content LoadingIndicator")
            ),
        )
        await pilot.press(key)  # action → ConfirmModal
        await pilot.pause(0.05)
        assert isinstance(app.screen, ConfirmModal)
        await pilot.press("y")  # confirm → run_write
        await wait_for(pilot, lambda: fake_client.calls)


def test_inbox_promote_calls_engine(fake_client, monkeypatch):
    monkeypatch.setattr("expense.commands.inbox_cmd.fetch_inbox", lambda *a, **k: {"items": INBOX})
    monkeypatch.setattr("expense.tui.screens.inbox.load_account_name_map", lambda: {})
    monkeypatch.setattr("expense.tui.screens.inbox.load_category_name_map", lambda: {})

    asyncio.run(_drive(ExpenseApp(no_cache=True), InboxScreen(), "p", fake_client))
    assert ("POST", "/inbox/i1/promote") in fake_client.requests


def test_inbox_delete_calls_engine(fake_client, monkeypatch):
    monkeypatch.setattr("expense.commands.inbox_cmd.fetch_inbox", lambda *a, **k: {"items": INBOX})
    monkeypatch.setattr("expense.tui.screens.inbox.load_account_name_map", lambda: {})
    monkeypatch.setattr("expense.tui.screens.inbox.load_category_name_map", lambda: {})

    asyncio.run(_drive(ExpenseApp(no_cache=True), InboxScreen(), "d", fake_client))
    assert ("DELETE", "/inbox/i1") in fake_client.requests


def test_accounts_archive_calls_engine(fake_client, monkeypatch):
    monkeypatch.setattr("expense.commands.accounts_cmd.fetch_accounts", lambda *a, **k: ACCOUNTS)

    asyncio.run(_drive(ExpenseApp(no_cache=True), AccountsScreen(), "a", fake_client))
    assert ("POST", "/accounts/a1/archive") in fake_client.requests
