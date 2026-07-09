"""Smoke tests for the `expense world` TUI.

Drives Textual headlessly via `App.run_test()` wrapped in `asyncio.run` (no
pytest-asyncio dependency). Network is never touched: pure render helpers and
`CategoriesView._build` are tested directly; the nav test stubs `fetch_dashboard`.
"""

import asyncio
import io

from rich.console import Console
from textual.widgets import OptionList

from expense.commands import dashboard_cmd
from expense.tui.app import ExpenseApp
from expense.tui.screens.home import HomeScreen
from expense.tui.screens.outstanding import (
    CategoriesView,
    OutstandingScreen,
    _accounts_table,
    _totals_table,
)
from tests.unit.helpers import wait_for

SAMPLE = {
    "month": {"year": 2026, "month": 3},
    "bank_accounts": [
        {"name": "BCP Soles", "currency_code": "PEN", "current_balance_cents": 1245000}
    ],
    "people": [{"name": "Socio Juan", "currency_code": "PEN", "current_balance_cents": -150000}],
    "categories": [
        {
            "name": "Comida",
            "spent_cents": -43250,
            "hashtag_breakdown": [{"hashtag_ids": ["x"], "spent_cents": -25000}],
        },
        {"name": "Vivienda", "spent_cents": -250000, "hashtag_breakdown": []},
    ],
    "totals": {
        "inflow_cents": 651900,
        "inflow_home_cents": 651900,
        "outflow_cents": -341250,
        "outflow_home_cents": -385650,
        "net_cents": 266250,
        "net_home_cents": 266250,
    },
}


def _text(renderable) -> str:
    con = Console(file=io.StringIO(), width=80)
    con.print(renderable)
    return con.file.getvalue()


def test_static_sections_format():
    accounts = _text(_accounts_table(SAMPLE["bank_accounts"]))
    assert "BCP Soles" in accounts and "12,450.00" in accounts  # grouped major units
    totals = _text(_totals_table(SAMPLE["totals"]))
    assert "inflow" in totals and "net" in totals and "6,519.00" in totals


def test_categories_view_formats_and_resolves(monkeypatch):
    view = CategoriesView(SAMPLE["categories"], {"x": "trabajo"})
    out = _text(view._build())
    assert "▼ Comida" in out and "-432.50" in out  # caret + amount
    assert "trabajo" in out and "-250.00" in out  # hashtag id resolved + child amount
    assert "Vivienda" in out  # leaf category (no caret/children)


def test_categories_view_collapse_hides_children():
    view = CategoriesView(SAMPLE["categories"], {"x": "trabajo"})
    assert "trabajo" in _text(view._build())  # expanded by default
    view._collapsed.add(0)
    collapsed = _text(view._build())
    assert "▶ Comida" in collapsed  # caret flips
    assert "trabajo" not in collapsed  # child row hidden


def test_app_launches_home_with_outstanding_option():
    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)
            option_list = app.query_one(OptionList)
            ids = [
                option_list.get_option_at_index(i).id
                for i in range(option_list.option_count)
                if option_list.get_option_at_index(i).id
            ]
            assert any(i.startswith("outstanding:") for i in ids)
            assert any(i.startswith("report:") for i in ids)
            # every entry is wired — the last "soon" stub shipped 2026-07-08
            assert not any(i.startswith("soon:") for i in ids)

    asyncio.run(scenario())


def test_outstanding_screen_populates_and_tree_collapses(monkeypatch):
    monkeypatch.setattr(dashboard_cmd, "fetch_dashboard", lambda *a, **k: SAMPLE)
    monkeypatch.setattr(dashboard_cmd, "load_hashtag_name_map", lambda: {"x": "trabajo"})
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            await app.push_screen(OutstandingScreen())
            await wait_for(
                pilot,
                lambda: (
                    app.screen.query(CategoriesView)
                    and not app.screen.query("#content LoadingIndicator")
                ),
            )
            # worker fetched + populate mounted the tree
            view = app.screen.query(CategoriesView).first()
            assert view._collapsed == set()
            await pilot.press("left")  # collapse focused category
            assert view._collapsed == {0}

    asyncio.run(scenario())
