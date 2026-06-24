"""Phase 0 smoke tests for the `expense world` TUI.

Drives Textual headlessly via `App.run_test()` wrapped in `asyncio.run` (no
pytest-asyncio dependency). Network is never touched: the pure renderable
builder is tested directly, and the nav test stubs `fetch_dashboard`.
"""

import asyncio
import io

from rich.console import Console
from textual.widgets import OptionList

from expense.commands import dashboard_cmd
from expense.tui.app import ExpenseApp
from expense.tui.screens.home import HomeScreen
from expense.tui.screens.outstanding import OutstandingScreen, dashboard_renderables

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
        }
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


def _render(parts) -> str:
    con = Console(file=io.StringIO(), width=80)
    for _css, renderable in parts:
        con.print(renderable)
    return con.file.getvalue()


def test_dashboard_renderables_formats_and_resolves(monkeypatch):
    monkeypatch.setattr(dashboard_cmd, "load_hashtag_name_map", lambda: {"x": "trabajo"})
    out = _render(dashboard_renderables(SAMPLE))
    assert "2026-03" in out
    assert "BCP Soles" in out and "12,450.00" in out  # grouped major units
    assert "Socio Juan" in out and "-1,500.00" in out
    assert "Comida" in out and "-432.50" in out
    assert "trabajo" in out  # hashtag id resolved to name
    assert "inflow" in out and "net" in out


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
            assert any(i.startswith("soon:") for i in ids)

    asyncio.run(scenario())


def test_outstanding_screen_populates_from_fetch(monkeypatch):
    monkeypatch.setattr(dashboard_cmd, "fetch_dashboard", lambda *a, **k: SAMPLE)
    monkeypatch.setattr(dashboard_cmd, "load_hashtag_name_map", lambda: {})
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            await app.push_screen(OutstandingScreen())
            statics = 0
            for _ in range(50):
                await pilot.pause(0.02)
                statics = len(app.screen.query("#content Static"))
                loaders = len(app.screen.query("#content LoadingIndicator"))
                if statics >= 7 and loaders == 0:
                    break
            assert isinstance(app.screen, OutstandingScreen)
            # worker fetched + populate replaced the loading indicator with the
            # rendered sections (accounts / people / categories / totals).
            assert statics >= 7
            assert len(app.screen.query("#content LoadingIndicator")) == 0

    asyncio.run(scenario())
