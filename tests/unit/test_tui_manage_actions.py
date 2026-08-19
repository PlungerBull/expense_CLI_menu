"""Manage list actions — `e` edit and `a` archive act on the cursor row.

The record detail was deleted 2026-07-11 (decisions.md): the list is the only
surface. `a` toggles archive/unarchive immediately — no ConfirmModal, a second
`a` undoes — and the cursor stays on the acted-on row across the reload.
`enter` is a no-op. Archive is Accounts-only since the 2026-08-06 engine
schema slimming removed category/hashtag archive.
"""

import asyncio

from expense.tui.app import ExpenseApp
from expense.tui.screens.accounts import AccountsScreen
from expense.tui.screens.categories import CategoriesScreen
from expense.tui.screens.create_forms import EditAccountScreen, EditHashtagScreen
from expense.tui.screens.hashtags import HashtagsScreen
from expense.tui.screens.modals import ConfirmModal
from expense.tui.widgets.cursor_list import CursorList
from tests.unit.helpers import wait_for, wait_for_list

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
SYS_CAT = {"id": "c1", "name": "@Opening", "is_system": True, "color": None}
HASHTAG = {"id": "h1", "name": "trabajo"}


def test_archive_is_immediate_no_modal(fake_client, monkeypatch):
    monkeypatch.setattr("expense.commands.accounts_cmd.fetch_accounts", lambda *a, **k: [ACCOUNT])

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = AccountsScreen()
            await app.push_screen(screen)
            await wait_for_list(pilot, app)
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
        app = ExpenseApp()
        async with app.run_test() as pilot:
            await app.push_screen(AccountsScreen())
            await wait_for_list(pilot, app)
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
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = AccountsScreen()
            await app.push_screen(screen)
            await wait_for_list(pilot, app)
            await pilot.press("down")  # cursor → a2
            await pilot.press("a")
            await wait_for(pilot, lambda: fake_client.calls)
            await wait_for(pilot, lambda: not screen._toggle_busy)  # reload landed
            cursor_list = screen.query(CursorList).first()
            assert cursor_list.cursor_key == "a2"

    asyncio.run(scenario())
    assert ("POST", "/accounts/a2/archive") in fake_client.requests


def test_archive_toggle_restores_cursor_across_pages(fake_client, monkeypatch):
    """25 accounts: act on row 22 — beyond the 20-row window (2026-07-11
    pagination). The reload must land the cursor back on that row, on its page."""
    accounts = [{**ACCOUNT, "id": f"a{i}", "name": f"Acct {i:02d}"} for i in range(25)]
    monkeypatch.setattr("expense.commands.accounts_cmd.fetch_accounts", lambda *a, **k: accounts)

    async def scenario():
        app = ExpenseApp()
        # tall harness: rows-per-page adapt to the terminal since 2026-07-13;
        # 40 lines keeps the manage window at the 20-row cap, so a22 is page 2
        async with app.run_test(size=(120, 40)) as pilot:
            screen = AccountsScreen()
            await app.push_screen(screen)
            await wait_for_list(pilot, app)
            cursor_list = screen.query(CursorList).first()
            cursor_list.set_cursor(cursor_list.index_of("a22"))
            await pilot.press("a")
            await wait_for(pilot, lambda: fake_client.calls)
            await wait_for(pilot, lambda: not screen._toggle_busy)  # reload landed
            cursor_list = screen.query(CursorList).first()
            assert cursor_list.cursor_key == "a22"
            assert cursor_list.page_status == "rows 21-25 of 25 · page 2 of 2"

    asyncio.run(scenario())
    assert ("POST", "/accounts/a22/archive") in fake_client.requests


def test_edit_prefills_and_puts(fake_client, monkeypatch):
    monkeypatch.setattr("expense.commands.accounts_cmd.fetch_accounts", lambda *a, **k: [ACCOUNT])

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            await app.push_screen(AccountsScreen())
            await wait_for_list(pilot, app)
            await pilot.press("e")  # → prefilled EditAccountScreen
            await wait_for(pilot, lambda: isinstance(app.screen, EditAccountScreen))
            await pilot.press("ctrl+s")  # save unchanged → PUT
            await wait_for(pilot, lambda: fake_client.calls)

    asyncio.run(scenario())
    puts = dict(fake_client.puts)
    assert "/accounts/a1" in puts
    assert puts["/accounts/a1"]["name"] == "BCP"  # prefilled name round-trips
    assert "currency_code" not in puts["/accounts/a1"]  # currency is immutable


def test_categories_have_no_archive_action(fake_client, monkeypatch):
    """Category archive died with the 2026-08-06 schema slimming: the `a`
    binding lives on AccountsScreen only, so on Categories it is inert."""
    monkeypatch.setattr(
        "expense.commands.categories_cmd.fetch_categories", lambda *a, **k: [SYS_CAT]
    )

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = CategoriesScreen()
            await app.push_screen(screen)
            await wait_for_list(pilot, app)
            assert not hasattr(screen, "action_archive")
            assert screen.check_action("edit", ()) is True  # edit still offered
            await pilot.press("a")  # inert — no confirm, no write
            await pilot.pause()  # let the (inert) keypress settle, then assert a non-event
            assert not isinstance(app.screen, ConfirmModal)
            assert not fake_client.calls

    asyncio.run(scenario())


def test_hashtag_edit_puts(fake_client, monkeypatch):
    monkeypatch.setattr("expense.commands.hashtags_cmd.fetch_hashtags", lambda *a, **k: [HASHTAG])

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            await app.push_screen(HashtagsScreen())
            await wait_for_list(pilot, app)
            await pilot.press("e")
            await wait_for(pilot, lambda: isinstance(app.screen, EditHashtagScreen))
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
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = AccountsScreen()
            await app.push_screen(screen)
            await wait_for_list(pilot, app)
            await pilot.press("enter")
            await pilot.pause()  # let the (inert) keypress settle, then assert a non-event
            assert app.screen is screen  # nothing pushed
            assert not fake_client.calls  # nothing written

    asyncio.run(scenario())
