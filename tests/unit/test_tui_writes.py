"""Phase 2 write-action smoke tests (Inbox promote/delete, Accounts archive).

Uses a fake HTTP client so nothing real is mutated — asserts the right
engine endpoint would be called via the ConfirmModal → run_write path.
"""

import asyncio
import time

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


def test_refresh_mid_write_does_not_cancel_the_write(fake_client, monkeypatch):
    """`r` mid-write must not cancel the engine-write worker (backlog 3.2).

    run_write and _load used to share the default exclusive group, so a
    refresh or theme change cancelled an in-flight write worker.
    """
    monkeypatch.setattr("expense.commands.accounts_cmd.fetch_accounts", lambda *a, **k: ACCOUNTS)
    real_post = fake_client.post

    def slow_post(path, json_body=None):
        time.sleep(0.15)  # keep the write worker observable in flight
        return real_post(path, json_body=json_body)

    fake_client.post = slow_post

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = AccountsScreen()
            await app.push_screen(screen)
            from expense.tui.widgets.cursor_list import CursorList

            await wait_for(
                pilot,
                lambda: (
                    app.screen.query(CursorList)
                    and not app.screen.query("#content LoadingIndicator")
                ),
            )
            await pilot.press("a")  # archive → ConfirmModal
            await pilot.pause(0.05)
            await pilot.press("y")  # confirm → slow run_write
            write_workers = [w for w in app.workers if w.group == "engine-write"]
            assert write_workers, "write worker not running in its own group"
            await pilot.press("r")  # refresh while the write is in flight
            await wait_for(pilot, lambda: fake_client.calls)
            assert not write_workers[0].is_cancelled

    asyncio.run(scenario())
    assert ("POST", "/accounts/a1/archive") in fake_client.requests


def test_concurrent_content_swaps_mount_one_card(fake_client, monkeypatch):
    """Two loads landing together must swap #content atomically.

    _show suspends between remove_children and mount; unserialized, the
    interleave mounts a second '#card' (DuplicateIds) and kills the load
    worker — seen on slow CI runners as a refresh raced a post-write reload.
    """
    monkeypatch.setattr("expense.commands.accounts_cmd.fetch_accounts", lambda *a, **k: ACCOUNTS)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = AccountsScreen()
            await app.push_screen(screen)
            from expense.tui.widgets.cursor_list import CursorList

            await wait_for(
                pilot,
                lambda: (
                    app.screen.query(CursorList)
                    and not app.screen.query("#content LoadingIndicator")
                ),
            )
            await asyncio.gather(screen._show(ACCOUNTS), screen._show(ACCOUNTS))
            assert len(screen.query("#card")) == 1

    asyncio.run(scenario())


ARCHIVED = [{"id": "a1", "name": "BCP", "is_person": False, "is_archived": True, "color": None}]


def test_accounts_unarchive_is_direct(fake_client, monkeypatch):
    """Unarchive skips the ConfirmModal (backlog 4.7 — mirrors the flat CLI, 1.2)."""
    monkeypatch.setattr("expense.commands.accounts_cmd.fetch_accounts", lambda *a, **k: ARCHIVED)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = AccountsScreen()
            await app.push_screen(screen)
            from expense.tui.widgets.cursor_list import CursorList

            await wait_for(
                pilot,
                lambda: (
                    app.screen.query(CursorList)
                    and not app.screen.query("#content LoadingIndicator")
                ),
            )
            await pilot.press("a")  # unarchive: no modal, straight to the write
            await wait_for(pilot, lambda: fake_client.calls)
            assert not isinstance(app.screen, ConfirmModal)

    asyncio.run(scenario())
    assert ("POST", "/accounts/a1/unarchive") in fake_client.requests
