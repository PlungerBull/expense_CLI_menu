"""SectionScreen failure paths — error banner, reload recovery, write failure
(backlog 6.4). Uses AccountsScreen as the concrete SectionScreen; nothing here
is accounts-specific.
"""

import asyncio
import io

from rich.console import Console
from textual.widgets import Static

from expense.errors import EngineError
from expense.tui.app import ExpenseApp
from expense.tui.screens.accounts import AccountsScreen
from expense.tui.screens.manage_detail import AccountDetailScreen, ManageDetailScreen
from expense.tui.screens.modals import ConfirmModal
from tests.unit.helpers import wait_for

ACCOUNTS = [{"id": "a1", "name": "BCP", "is_person": False, "is_archived": False, "color": None}]


def _text(renderable) -> str:
    con = Console(file=io.StringIO(), width=80)
    con.print(renderable)
    return con.file.getvalue()


def test_fetch_error_renders_banner(fake_client, monkeypatch):
    """_load catches the fetch exception and mounts the 'Could not load.' banner."""

    def boom(*a, **k):
        raise EngineError("INTERNAL", "engine exploded", None, 500, {})

    monkeypatch.setattr("expense.commands.accounts_cmd.fetch_accounts", boom)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            await app.push_screen(AccountsScreen())
            await wait_for(pilot, lambda: app.screen.query(".error"))
            banner = _text(app.screen.query_one(".error", Static).content)
            assert "Could not load." in banner
            assert "INTERNAL — engine exploded" in banner  # canonical format_error text

    asyncio.run(scenario())


def test_action_reload_recovers_after_error(fake_client, monkeypatch):
    """`r` remounts the spinner, re-runs fetch, and replaces the banner with data."""
    attempts = []

    def flaky(*a, **k):
        attempts.append(1)
        if len(attempts) == 1:
            raise EngineError("INTERNAL", "first call fails", None, 500, {})
        return ACCOUNTS

    monkeypatch.setattr("expense.commands.accounts_cmd.fetch_accounts", flaky)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            await app.push_screen(AccountsScreen())
            await wait_for(pilot, lambda: app.screen.query(".error"))
            await pilot.press("r")  # action_reload
            await wait_for(pilot, lambda: app.screen.query("#card"))
            assert not app.screen.query(".error")
            assert len(attempts) == 2

    asyncio.run(scenario())


def test_run_write_failure_notifies_and_skips_after_write(fake_client, monkeypatch):
    """A failing write toasts title='Failed' and never fires success/refresh/reload.

    Archive now lives on the record detail (ManageDetailScreen), which shares
    EngineWriteMixin.run_write with SectionScreen — same failure path.
    """
    fake_client.errors["POST"] = EngineError("CONFLICT", "cannot archive", None, 409, {})
    seen: list = []
    monkeypatch.setattr(
        ManageDetailScreen, "notify", lambda self, message, **kw: seen.append((message, kw))
    )
    account = {"id": "a1", "name": "BCP", "is_person": False, "is_archived": False, "color": None}

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            await app.push_screen(AccountDetailScreen(account))
            await wait_for(pilot, lambda: isinstance(app.screen, AccountDetailScreen))
            await pilot.press("a")  # archive → ConfirmModal
            await wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
            await pilot.press("y")  # confirm → run_write → POST raises
            await wait_for(pilot, lambda: seen)
            message, kw = seen[0]
            assert "CONFLICT — cannot archive" in message
            assert kw.get("title") == "Failed" and kw.get("severity") == "error"
            assert len(seen) == 1  # no success toast, no reload (_written skipped)
            assert fake_client.refreshes == 0  # refresh_after_write never reached

    asyncio.run(scenario())
