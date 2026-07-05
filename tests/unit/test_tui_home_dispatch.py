"""HomeScreen menu dispatch — every wired entry pushes its screen (backlog 6.3).

The 14-branch elif in home.py had zero coverage: a typo'd branch would leave a
menu entry dead with a green suite. Each case drives the real path — focus the
OptionList, highlight the entry, press enter — and asserts the pushed screen.
"""

import asyncio

import pytest
from textual.widgets import OptionList

import expense.tui.screens.home as home
from expense.tui.app import ExpenseApp
from expense.tui.screens._base import SectionScreen
from expense.tui.screens.home import HomeScreen
from expense.tui.screens.quick_log import QuickAddLogScreen
from tests.unit.helpers import wait_for

_CASES = [
    ("log", home.QuickAddLogScreen),
    ("inbox", home.InboxScreen),
    ("transactions", home.TransactionsScreen),
    ("reconciliations", home.ReconciliationsScreen),
    ("outstanding", home.OutstandingScreen),
    ("accounts", home.AccountsScreen),
    ("categories", home.CategoriesScreen),
    ("hashtags", home.HashtagsScreen),
    ("config", home.ConfigScreen),
    ("auth", home.AuthScreen),
    ("sync", home.SyncScreen),
    ("activity", home.ActivityScreen),
    ("rates", home.RatesScreen),
]


def _stub_loaders(monkeypatch):
    """Kill every on-mount fetch: 12 targets are SectionScreens (worker _load),
    QuickAddLogScreen is a plain Screen with its own _load_entities worker."""
    monkeypatch.setattr(SectionScreen, "_load", lambda self: None)
    monkeypatch.setattr(QuickAddLogScreen, "_load_entities", lambda self: None)


async def _select(app, pilot, kind):
    menu = app.query_one("#menu", OptionList)
    opt_id = next(
        menu.get_option_at_index(i).id
        for i in range(menu.option_count)
        if (menu.get_option_at_index(i).id or "").startswith(f"{kind}:")
    )
    app.set_focus(menu)
    menu.highlighted = menu.get_option_index(opt_id)
    await pilot.press("enter")


@pytest.mark.parametrize(("kind", "screen_cls"), _CASES, ids=[k for k, _ in _CASES])
def test_menu_dispatch(monkeypatch, kind, screen_cls):
    _stub_loaders(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _select(app, pilot, kind)
            await wait_for(pilot, lambda: isinstance(app.screen, screen_cls))
            assert type(app.screen) is screen_cls

    asyncio.run(scenario())


def test_soon_notifies_and_stays_home(monkeypatch):
    _stub_loaders(monkeypatch)
    seen: list = []
    monkeypatch.setattr(
        HomeScreen, "notify", lambda self, message, **kw: seen.append((message, kw))
    )

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _select(app, pilot, "soon")
            await wait_for(pilot, lambda: seen)
            assert isinstance(app.screen, HomeScreen)  # nothing pushed
            assert seen[0][1].get("title") == "Not wired yet"

    asyncio.run(scenario())


def test_cases_cover_every_wired_menu_entry():
    """Armor: a new _MENU entry must get a dispatch case here (and vice versa)."""
    wired = {kind for kind, _ in home._MENU if kind not in (None, "soon")}
    assert wired == {kind for kind, _ in _CASES}
