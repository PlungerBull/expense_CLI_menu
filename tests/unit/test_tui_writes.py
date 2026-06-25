"""Phase 2 write-action smoke tests (Inbox promote/delete, Accounts archive).

Uses a fake HTTP client so nothing real is mutated — asserts the right
engine endpoint would be called via the ConfirmModal → run_write path.
"""

import asyncio

from expense.tui.app import ExpenseApp
from expense.tui.screens.accounts import AccountsScreen
from expense.tui.screens.inbox import InboxScreen
from expense.tui.screens.modals import ConfirmModal

INBOX = [{"id": "i1", "title": "Almuerzo", "status": 1, "amount_cents": -1000}]
ACCOUNTS = [{"id": "a1", "name": "BCP", "is_person": False, "is_archived": False, "color": None}]


class _FakeClient:
    calls: list = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, path, json_body=None):
        _FakeClient.calls.append(("POST", path))
        return {}

    def delete(self, path):
        _FakeClient.calls.append(("DELETE", path))
        return {}


def _patch_writes(monkeypatch):
    _FakeClient.calls = []
    monkeypatch.setattr("expense.http.ExpenseClient", _FakeClient)
    monkeypatch.setattr("expense.cache.refresh_after_write", lambda *a, **k: None)
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())


async def _drive(app, screen, key):
    async with app.run_test() as pilot:
        await app.push_screen(screen)
        from expense.tui.widgets.cursor_list import CursorList

        for _ in range(50):
            await pilot.pause(0.02)
            if app.screen.query(CursorList) and not app.screen.query("#content LoadingIndicator"):
                break
        await pilot.press(key)  # action → ConfirmModal
        await pilot.pause(0.05)
        assert isinstance(app.screen, ConfirmModal)
        await pilot.press("y")  # confirm → run_write
        for _ in range(50):
            await pilot.pause(0.02)
            if _FakeClient.calls:
                break


def test_inbox_promote_calls_engine(monkeypatch):
    _patch_writes(monkeypatch)
    monkeypatch.setattr("expense.commands.inbox_cmd.fetch_inbox", lambda *a, **k: {"items": INBOX})
    monkeypatch.setattr("expense.tui.screens.inbox.load_account_name_map", lambda: {})
    monkeypatch.setattr("expense.tui.screens.inbox.load_category_name_map", lambda: {})

    asyncio.run(_drive(ExpenseApp(no_cache=True), InboxScreen(), "p"))
    assert ("POST", "/inbox/i1/promote") in _FakeClient.calls


def test_inbox_delete_calls_engine(monkeypatch):
    _patch_writes(monkeypatch)
    monkeypatch.setattr("expense.commands.inbox_cmd.fetch_inbox", lambda *a, **k: {"items": INBOX})
    monkeypatch.setattr("expense.tui.screens.inbox.load_account_name_map", lambda: {})
    monkeypatch.setattr("expense.tui.screens.inbox.load_category_name_map", lambda: {})

    asyncio.run(_drive(ExpenseApp(no_cache=True), InboxScreen(), "d"))
    assert ("DELETE", "/inbox/i1") in _FakeClient.calls


def test_accounts_archive_calls_engine(monkeypatch):
    _patch_writes(monkeypatch)
    monkeypatch.setattr("expense.commands.accounts_cmd.fetch_accounts", lambda *a, **k: ACCOUNTS)

    asyncio.run(_drive(ExpenseApp(no_cache=True), AccountsScreen(), "a"))
    assert ("POST", "/accounts/a1/archive") in _FakeClient.calls
