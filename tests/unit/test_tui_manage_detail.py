"""Manage record detail (Phase 2, Option B) — edit + archive from the detail.

`enter` on a Manage list opens the detail (covered in the list smoke tests);
here we exercise the detail's own actions: `a` archive/unarchive, `e` edit
(prefilled PUT), and the system-category rule (edit offered, archive hidden).
"""

import asyncio

from expense.tui.app import ExpenseApp
from expense.tui.screens.create_forms import EditAccountScreen
from expense.tui.screens.manage_detail import (
    AccountDetailScreen,
    CategoryDetailScreen,
    HashtagDetailScreen,
)
from expense.tui.screens.modals import ConfirmModal
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
ARCHIVED_ACCOUNT = {**ACCOUNT, "is_archived": True}
SYS_CAT = {"id": "c1", "name": "@Transfer", "is_system": True, "is_archived": False, "color": None}
HASHTAG = {"id": "h1", "name": "trabajo", "is_archived": False}


def test_account_detail_archive_confirms_then_writes(fake_client, monkeypatch):
    monkeypatch.setattr("expense.commands.accounts_cmd.fetch_accounts", lambda *a, **k: [ACCOUNT])

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            await app.push_screen(AccountDetailScreen(ACCOUNT))
            await pilot.pause(0.05)
            await pilot.press("a")  # archive → ConfirmModal
            await pilot.pause(0.05)
            assert isinstance(app.screen, ConfirmModal)
            await pilot.press("y")  # confirm → run_write
            await wait_for(pilot, lambda: fake_client.calls)

    asyncio.run(scenario())
    assert ("POST", "/accounts/a1/archive") in fake_client.requests


def test_account_detail_unarchive_is_direct(fake_client, monkeypatch):
    """Unarchive skips the ConfirmModal — it undoes, not destroys (backlog 4.7)."""
    monkeypatch.setattr(
        "expense.commands.accounts_cmd.fetch_accounts", lambda *a, **k: [ARCHIVED_ACCOUNT]
    )

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            await app.push_screen(AccountDetailScreen(ARCHIVED_ACCOUNT))
            await pilot.pause(0.05)
            await pilot.press("a")  # unarchive: straight to the write, no modal
            await wait_for(pilot, lambda: fake_client.calls)
            assert not isinstance(app.screen, ConfirmModal)

    asyncio.run(scenario())
    assert ("POST", "/accounts/a1/unarchive") in fake_client.requests


def test_account_detail_edit_prefills_and_puts(fake_client, monkeypatch):
    monkeypatch.setattr("expense.commands.accounts_cmd.fetch_accounts", lambda *a, **k: [ACCOUNT])

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            await app.push_screen(AccountDetailScreen(ACCOUNT))
            await pilot.pause(0.05)
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


def test_system_category_hides_archive_but_offers_edit(fake_client):
    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = CategoryDetailScreen(SYS_CAT)
            await app.push_screen(screen)
            await pilot.pause(0.05)
            # archive is hidden (engine 403s system categories); edit is offered
            assert screen.check_action("archive", ()) is None
            assert screen.check_action("edit", ()) is True
            await pilot.press("a")  # inert — no confirm, no write
            await pilot.pause(0.05)
            assert not isinstance(app.screen, ConfirmModal)
            assert not fake_client.calls

    asyncio.run(scenario())


def test_hashtag_detail_edit_puts(fake_client, monkeypatch):
    monkeypatch.setattr("expense.commands.hashtags_cmd.fetch_hashtags", lambda *a, **k: [HASHTAG])

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            await app.push_screen(HashtagDetailScreen(HASHTAG))
            await pilot.pause(0.05)
            await pilot.press("e")
            await pilot.pause(0.05)
            await pilot.press("ctrl+s")
            await wait_for(pilot, lambda: fake_client.calls)

    asyncio.run(scenario())
    puts = dict(fake_client.puts)
    assert "/hashtags/h1" in puts
    assert puts["/hashtags/h1"]["name"] == "trabajo"


def test_manage_detail_renders_with_size(fake_client):
    """The detail card must actually paint (guards against a modal-style collapse)."""

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test(size=(100, 40)) as pilot:
            await app.push_screen(AccountDetailScreen(ACCOUNT))
            await pilot.pause(0.05)
            detail = app.screen.query_one("#detail")
            assert detail.size.height > 3  # header + several field rows

    asyncio.run(scenario())
