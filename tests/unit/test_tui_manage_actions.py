"""Manage list actions — `e` edit and `a` archive act on the cursor row.

The record detail was deleted 2026-07-11 (decisions.md): the list is the only
surface. `a` toggles archive/unarchive immediately — no ConfirmModal, a second
`a` undoes — and the cursor stays on the acted-on row across the reload.
`enter` is a no-op. System categories: edit offered, archive hidden.
"""

import asyncio

from expense.tui.app import ExpenseApp
from expense.tui.screens.accounts import AccountsScreen
from expense.tui.screens.categories import CategoriesScreen
from expense.tui.screens.create_forms import EditAccountScreen
from expense.tui.screens.hashtags import HashtagsScreen
from expense.tui.screens.modals import ConfirmModal
from expense.tui.widgets.cursor_list import CursorList
from tests.unit.helpers import wait_for

ACCOUNT = {
    "id": "a1",
    "name": "BCP",
    "is_person": False,
    "is_archived": False,
    "currency_code": "PEN",
    "color": "#4a90d9",
    "current_balance_cents": -7495,
}
ACCOUNT_2 = {**ACCOUNT, "id": "a2", "name": "Interbank", "color": None}
ARCHIVED_ACCOUNT = {**ACCOUNT, "is_archived": True}
SYS_CAT = {"id": "c1", "name": "@Transfer", "is_system": True, "is_archived": False, "color": None}
HASHTAG = {"id": "h1", "name": "trabajo", "is_archived": False}


async def _wait_loaded(app, pilot):
    await wait_for(
        pilot,
        lambda: app.screen.query(CursorList) and not app.screen.query("#content LoadingIndicator"),
    )


def test_archive_is_immediate_no_modal(fake_client, monkeypatch):
    monkeypatch.setattr("expense.commands.accounts_cmd.fetch_accounts", lambda *a, **k: [ACCOUNT])

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = AccountsScreen()
            await app.push_screen(screen)
            await _wait_loaded(app, pilot)
            await pilot.press("a")  # straight to the write — no ConfirmModal
            assert not isinstance(app.screen, ConfirmModal)
            await wait_for(pilot, lambda: fake_client.calls)

    asyncio.run(scenario())
    assert ("POST", "/accounts/a1/archive") in fake_client.requests


def test_unarchive_is_direct(fake_client, monkeypatch):
    """`a` on an archived row unarchives — same key, opposite verb, no prompt."""
    monkeypatch.setattr(
        "expense.commands.accounts_cmd.fetch_accounts", lambda *a, **k: [ARCHIVED_ACCOUNT]
    )

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            await app.push_screen(AccountsScreen())
            await _wait_loaded(app, pilot)
            await pilot.press("a")
            assert not isinstance(app.screen, ConfirmModal)
            await wait_for(pilot, lambda: fake_client.calls)

    asyncio.run(scenario())
    assert ("POST", "/accounts/a1/unarchive") in fake_client.requests


def test_archive_toggle_keeps_cursor_on_row(fake_client, monkeypatch):
    """The reload after a toggle re-selects the acted-on row (fresh CursorList
    would otherwise snap to row 0, so a second `a` would hit the wrong record)."""
    monkeypatch.setattr(
        "expense.commands.accounts_cmd.fetch_accounts", lambda *a, **k: [ACCOUNT, ACCOUNT_2]
    )

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = AccountsScreen()
            await app.push_screen(screen)
            await _wait_loaded(app, pilot)
            await pilot.press("down")  # cursor → a2
            await pilot.press("a")
            await wait_for(pilot, lambda: fake_client.calls)
            await wait_for(pilot, lambda: not screen._toggle_busy)  # reload landed
            cursor_list = screen.query(CursorList).first()
            assert cursor_list.cursor_key == "a2"

    asyncio.run(scenario())
    assert ("POST", "/accounts/a2/archive") in fake_client.requests


def test_edit_prefills_and_puts(fake_client, monkeypatch):
    monkeypatch.setattr("expense.commands.accounts_cmd.fetch_accounts", lambda *a, **k: [ACCOUNT])

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            await app.push_screen(AccountsScreen())
            await _wait_loaded(app, pilot)
            await pilot.press("e")  # → prefilled EditAccountScreen
            await pilot.pause(0.05)
            assert isinstance(app.screen, EditAccountScreen)
            await pilot.press("ctrl+s")  # save unchanged → PUT
            await wait_for(pilot, lambda: fake_client.calls)

    asyncio.run(scenario())
    puts = dict(fake_client.puts)
    assert "/accounts/a1" in puts
    assert puts["/accounts/a1"]["name"] == "BCP"  # prefilled name round-trips
    assert "currency_code" not in puts["/accounts/a1"]  # currency is immutable


def test_system_category_hides_archive_but_offers_edit(fake_client, monkeypatch):
    monkeypatch.setattr(
        "expense.commands.categories_cmd.fetch_categories", lambda *a, **k: [SYS_CAT]
    )

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = CategoriesScreen()
            await app.push_screen(screen)
            await _wait_loaded(app, pilot)
            # archive is hidden (engine 403s system categories); edit is offered
            assert screen.check_action("archive", ()) is None
            assert screen.check_action("edit", ()) is True
            await pilot.press("a")  # inert — no confirm, no write
            await pilot.pause(0.05)
            assert not isinstance(app.screen, ConfirmModal)
            assert not fake_client.calls

    asyncio.run(scenario())


def test_hashtag_edit_puts(fake_client, monkeypatch):
    monkeypatch.setattr("expense.commands.hashtags_cmd.fetch_hashtags", lambda *a, **k: [HASHTAG])

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            await app.push_screen(HashtagsScreen())
            await _wait_loaded(app, pilot)
            await pilot.press("e")
            await pilot.pause(0.05)
            await pilot.press("ctrl+s")
            await wait_for(pilot, lambda: fake_client.calls)

    asyncio.run(scenario())
    puts = dict(fake_client.puts)
    assert "/hashtags/h1" in puts
    assert puts["/hashtags/h1"]["name"] == "trabajo"


def test_enter_is_a_noop(fake_client, monkeypatch):
    """The record detail is gone: `enter` opens nothing, mutates nothing."""
    monkeypatch.setattr("expense.commands.accounts_cmd.fetch_accounts", lambda *a, **k: [ACCOUNT])

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = AccountsScreen()
            await app.push_screen(screen)
            await _wait_loaded(app, pilot)
            await pilot.press("enter")
            await pilot.pause(0.05)
            assert app.screen is screen  # nothing pushed
            assert not fake_client.calls  # nothing written

    asyncio.run(scenario())
