"""Smoke tests for the `expense world` TUI.

Drives Textual headlessly via `App.run_test()` wrapped in `asyncio.run` (no
pytest-asyncio dependency). Network is never touched — the nav test stubs
`fetch_dashboard`.

The render-helper and fold tests that used to live here moved to
`test_tui_overview.py` with the 2026-08-29 merge; the ones for `CategoriesView`
went away with the widget, whose job the month grid's newest column already did.
"""

import asyncio

from textual.widgets import OptionList, Static

from expense.commands import dashboard_cmd
from expense.tui.app import ExpenseApp
from expense.tui.screens.home import HomeScreen
from tests.unit.helpers import wait_for

SAMPLE = {
    "month": {"year": 2026, "month": 3},
    "bank_accounts": [
        {"name": "BCP Soles", "currency_code": "PEN", "current_balance_cents": 1245000}
    ],
    "people": [{"name": "Socio Juan", "currency_code": "PEN", "current_balance_cents": -150000}],
    # Aggregates are home-currency only since 2026-08-05, each nullable with an
    # `unconverted_count`. `Vacío` spent nothing and must not be drawn.
    "categories": [
        {
            "name": "Comida",
            "spent_home_cents": -43250,
            "unconverted_count": 0,
            "hashtag_breakdown": [
                {"hashtag_ids": ["x"], "spent_home_cents": -25000, "unconverted_count": 0}
            ],
        },
        {
            "name": "Vivienda",
            "spent_home_cents": -250000,
            "unconverted_count": 0,
            "hashtag_breakdown": [],
        },
        {"name": "Vacío", "spent_home_cents": 0, "unconverted_count": 0, "hashtag_breakdown": []},
    ],
    "totals": {
        "inflow_home_cents": 651900,
        "outflow_home_cents": -385650,
        "net_home_cents": 266250,
        "unconverted_count": 0,
    },
}


def test_app_launches_home_with_the_overview_option():
    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)
            option_list = app.query_one(OptionList)
            ids = [
                option_list.get_option_at_index(i).id
                for i in range(option_list.option_count)
                if option_list.get_option_at_index(i).id
            ]
            # option id is now the bare kind (no "kind:label" round-trip)
            assert "overview" in ids
            # both halves of the 2026-08-29 merge are gone as separate rows —
            # asserted negatively so a reflex re-add fails here, loudly
            assert "outstanding" not in ids
            assert "report" not in ids
            # every entry is wired — the last "soon" stub shipped 2026-07-08
            assert "soon" not in ids

    asyncio.run(scenario())


def test_home_header_stat_cluster_populates_from_worker(monkeypatch):
    """Drive the real on-mount worker path end-to-end: fetch → _extract_stats →
    call_from_thread → _set_stats (which caches _stats and re-renders #brand).
    The header Static exists from first paint; the stats arrive once the worker
    returns. (Rendering of _stats into the cluster is covered in
    test_tui_home_header.py.)"""
    body = {
        "totals": {
            "net_home_cents": 480000,
            "outflow_home_cents": 320000,
            "unconverted_count": 0,
        },
        "people": [{"current_balance_home_cents": 42000}],  # they owe you
    }
    monkeypatch.setattr(dashboard_cmd, "fetch_dashboard", lambda *a, **k: body)
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            home = app.screen
            assert home.query_one("#brand", Static) is not None  # header up from first paint
            await wait_for(pilot, lambda: home._stats is not None)
            assert home._stats == {
                "net": 480000,
                "spent": 320000,
                "owed": 42000,
                "unrated": 0,
            }

    asyncio.run(scenario())
