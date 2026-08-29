"""HomeScreen menu dispatch — every wired entry pushes its screen (backlog 6.3).

The multi-branch elif in home.py had zero coverage: a typo'd branch would leave a
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
from expense.tui.screens.log_bar import LogBarScreen
from expense.tui.screens.quick_log import QuickAddLogScreen
from tests.unit.helpers import wait_for

_CASES = [
    ("inbox", home.InboxScreen),
    ("transactions", home.TransactionsScreen),
    ("reconciliations", home.ReconciliationsScreen),
    ("overview", home.OverviewScreen),
    ("accounts", home.AccountsScreen),
    ("categories", home.CategoriesScreen),
    ("hashtags", home.HashtagsScreen),
    ("config", home.ConfigScreen),
    ("auth", home.AuthScreen),
    ("activity", home.ActivityScreen),
    ("rates", home.RatesScreen),
]


def _stub_loaders(monkeypatch):
    """Kill every on-mount fetch: HomeScreen's stat worker, every SectionScreen
    worker (_load), and QuickAddLogScreen's own _load_entities worker."""
    monkeypatch.setattr(HomeScreen, "_load_stats", lambda self: None)
    monkeypatch.setattr(SectionScreen, "_load", lambda self: None)
    monkeypatch.setattr(QuickAddLogScreen, "_load_entities", lambda self: None)
    monkeypatch.setattr(LogBarScreen, "_load_entities", lambda self: None)


async def _select(app, pilot, kind):
    menu = app.query_one("#menu", OptionList)
    app.set_focus(menu)
    menu.highlighted = menu.get_option_index(kind)  # option id is the kind itself
    await pilot.press("enter")


@pytest.mark.parametrize(("kind", "screen_cls"), _CASES, ids=[k for k, _ in _CASES])
def test_menu_dispatch(monkeypatch, kind, screen_cls):
    _stub_loaders(monkeypatch)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await _select(app, pilot, kind)
            await wait_for(pilot, lambda: isinstance(app.screen, screen_cls))
            assert type(app.screen) is screen_cls

    asyncio.run(scenario())


def test_cases_cover_every_wired_menu_entry():
    """Armor: a new _MENU entry must get a dispatch case here (and vice versa).
    Every entry is wired — the last "soon" stub (Monthly report) shipped 2026-07-08."""
    wired = {kind for kind, _ in home._MENU if kind is not None}
    assert wired == {kind for kind, _ in _CASES}


def test_screens_map_covers_every_wired_menu_entry():
    """The dispatch dict must stay in lockstep with _MENU: no wired entry left
    undispatched, no stale screen mapping (replaces the old elif's coverage)."""
    wired = {kind for kind, _ in home._MENU if kind is not None}
    assert set(home._SCREENS) == wired


def test_log_is_no_longer_a_menu_entry():
    """`Log a transaction` was removed from the menu on 2026-08-20 in favour of
    `+`. Guard so it is not re-added by reflex — the row and the key would be two
    doors to one form, and the menu is the slower one."""
    labels = [label for kind, label in home._MENU if kind is not None]
    assert "Log a transaction" not in labels
    assert "log" not in home._SCREENS


def test_plus_opens_the_log_form_from_home(monkeypatch):
    """`+` replaces the deleted menu row (2026-08-20). Plain `+`, no modifier —
    the numpad key and the main-row key send the same byte."""
    _stub_loaders(monkeypatch)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)
            await pilot.press("+")
            await wait_for(pilot, lambda: isinstance(app.screen, LogBarScreen))
            # the LOG bar, not the bar-cycle form: quick-add phase 4 moved the
            # create door and left the edit door alone
            assert app.screen._staged == []

    asyncio.run(scenario())


def test_q_quits_from_home(monkeypatch):
    """q is scoped to HomeScreen (backlog 4.6 B) — from home it quits."""
    _stub_loaders(monkeypatch)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)
            await pilot.press("q")
            await wait_for(pilot, lambda: not app.is_running)

    asyncio.run(scenario())


def test_q_inert_off_home(monkeypatch):
    """On a section screen q must do nothing — no App-level quit binding left."""
    _stub_loaders(monkeypatch)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await _select(app, pilot, "accounts")
            await wait_for(pilot, lambda: isinstance(app.screen, home.AccountsScreen))
            await pilot.press("q")
            await pilot.pause()  # let the (inert) keypress settle, then assert a non-event
            assert app.is_running
            assert isinstance(app.screen, home.AccountsScreen)

    asyncio.run(scenario())
