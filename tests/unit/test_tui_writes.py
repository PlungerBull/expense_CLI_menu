"""Phase 2 write-action smoke tests (Inbox promote/delete + write-worker
isolation / content-swap serialization on a SectionScreen).

Uses a fake HTTP client so nothing real is mutated — asserts the right
engine endpoint would be called via the ConfirmModal → run_write path.
Manage-list archive is an immediate toggle on the list itself — see
test_tui_manage_actions.py.
"""

import asyncio
import threading

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
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
        await pilot.press("y")  # confirm → run_write
        await wait_for(pilot, lambda: fake_client.calls)


def test_inbox_promote_calls_engine(fake_client, monkeypatch):
    monkeypatch.setattr("expense.commands.inbox_cmd.fetch_inbox", lambda *a, **k: {"items": INBOX})
    monkeypatch.setattr("expense.tui.screens.inbox.load_account_name_map", lambda: {})
    monkeypatch.setattr("expense.tui.screens.inbox.load_category_name_map", lambda: {})

    asyncio.run(_drive(ExpenseApp(), InboxScreen(), "p", fake_client))
    assert ("POST", "/inbox/i1/promote") in fake_client.requests


def test_inbox_delete_calls_engine(fake_client, monkeypatch):
    monkeypatch.setattr("expense.commands.inbox_cmd.fetch_inbox", lambda *a, **k: {"items": INBOX})
    monkeypatch.setattr("expense.tui.screens.inbox.load_account_name_map", lambda: {})
    monkeypatch.setattr("expense.tui.screens.inbox.load_category_name_map", lambda: {})

    asyncio.run(_drive(ExpenseApp(), InboxScreen(), "d", fake_client))
    assert ("DELETE", "/inbox/i1") in fake_client.requests


def test_refresh_mid_write_does_not_cancel_the_write(fake_client, monkeypatch):
    """`r` mid-write must not cancel the engine-write worker (backlog 3.2).

    run_write and _load used to share the default exclusive group, so a
    refresh or theme change cancelled an in-flight write worker. Exercised on
    Inbox promote (a SectionScreen list write + inherited `r` refresh).
    """
    monkeypatch.setattr("expense.commands.inbox_cmd.fetch_inbox", lambda *a, **k: {"items": INBOX})
    monkeypatch.setattr("expense.tui.screens.inbox.load_account_name_map", lambda: {})
    monkeypatch.setattr("expense.tui.screens.inbox.load_category_name_map", lambda: {})
    real_post = fake_client.post
    release = threading.Event()

    def gated_post(path, json_body=None):
        # Hold the write in flight until the test releases it. A fixed sleep is
        # racy: pilot.press awaits Textual's CPU-idleness heuristic, which on a
        # busy runner doesn't return until the whole write (sleep + reload)
        # has finished, so the engine-write worker is already gone by
        # the time we snapshot app.workers. The gate makes the window definite.
        release.wait(2.0)
        return real_post(path, json_body=json_body)

    fake_client.post = gated_post

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = InboxScreen()
            await app.push_screen(screen)
            from expense.tui.widgets.cursor_list import CursorList

            await wait_for(
                pilot,
                lambda: (
                    app.screen.query(CursorList)
                    and not app.screen.query("#content LoadingIndicator")
                ),
            )
            await pilot.press("p")  # promote → ConfirmModal
            await wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
            await pilot.press("y")  # confirm → gated run_write
            # Poll (don't snapshot) until the write worker registers — it's
            # blocked in gated_post, so this state is stable, not fleeting.
            await wait_for(
                pilot,
                lambda: [w for w in app.workers if w.group == "engine-write"],
                message="write worker not running in its own group",
            )
            write_worker = next(w for w in app.workers if w.group == "engine-write")
            await pilot.press("r")  # refresh while the write is in flight
            await pilot.pause()  # let the refresh keypress settle, then assert a non-event
            assert not write_worker.is_cancelled, "refresh cancelled the in-flight write"
            release.set()  # let the gated write complete
            await wait_for(pilot, lambda: fake_client.calls)
            assert not write_worker.is_cancelled

    try:
        asyncio.run(scenario())
    finally:
        release.set()  # never leave the worker thread blocked on the gate
    assert ("POST", "/inbox/i1/promote") in fake_client.requests


def test_rapid_writes_serialize_in_order(fake_client, monkeypatch):
    """Two immediate run_writes on any screen send both, one at a time, in
    order — the mixin-level generalization of the checklist-toggle queue
    (backlog 6.4b)."""
    import time

    monkeypatch.setattr("expense.commands.inbox_cmd.fetch_inbox", lambda *a, **k: {"items": INBOX})
    monkeypatch.setattr("expense.tui.screens.inbox.load_account_name_map", lambda: {})
    monkeypatch.setattr("expense.tui.screens.inbox.load_category_name_map", lambda: {})

    active = 0
    max_active = 0
    lock = threading.Lock()
    real_post = fake_client.post

    def slow_post(path, json_body=None):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.08)  # wide enough that overlapping POSTs would be caught
        with lock:
            active -= 1
        return real_post(path, json_body=json_body)

    fake_client.post = slow_post

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = InboxScreen()
            await app.push_screen(screen)
            from expense.tui.widgets.cursor_list import CursorList

            await wait_for(
                pilot,
                lambda: (
                    app.screen.query(CursorList)
                    and not app.screen.query("#content LoadingIndicator")
                ),
            )
            screen.run_write("POST", "/inbox/i1/promote", on_success=lambda: None)
            screen.run_write("POST", "/inbox/i1/snooze", on_success=lambda: None)
            await wait_for(pilot, lambda: len(fake_client.posts) == 2)

    asyncio.run(scenario())
    assert max_active == 1  # serialized: never two writes in flight
    assert [p for p, _ in fake_client.posts] == ["/inbox/i1/promote", "/inbox/i1/snooze"]


def test_concurrent_content_swaps_mount_one_card(fake_client, monkeypatch):
    """Two loads landing together must swap #content atomically.

    _show suspends between remove_children and mount; unserialized, the
    interleave mounts a second '#card' (DuplicateIds) and kills the load
    worker — seen on slow CI runners as a refresh raced a post-write reload.
    """
    monkeypatch.setattr("expense.commands.accounts_cmd.fetch_accounts", lambda *a, **k: ACCOUNTS)

    async def scenario():
        app = ExpenseApp()
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
