"""Monthly report TUI screen — month math, grid merge, pure render, pilot nav."""

import asyncio

from rich.text import Text

import expense.commands.reports_cmd as reports_cmd
from expense.commands.reports_cmd import build_range_grid
from expense.tui.app import ExpenseApp
from expense.tui.screens.reports import MonthGridView, MonthlyReportScreen, shift_month
from tests.unit.helpers import wait_for

# Two months with overlapping-but-different categories: Rent only in Nov,
# Salary only in Dec, Food in both (its #bbbb combo appears only in Dec).
MONTHS = [
    {
        "month": {"year": 2025, "month": 11},
        "categories": [
            {
                "id": "cat-food",
                "name": "Food",
                "spent_cents": -10000,
                "spent_home_cents": -10000,
                "hashtag_breakdown": [
                    {"hashtag_ids": ["aaaa"], "spent_cents": -6000, "spent_home_cents": -6000},
                    {"hashtag_ids": [], "spent_cents": -4000, "spent_home_cents": -4000},
                ],
            },
            {
                "id": "cat-rent",
                "name": "Rent",
                "spent_cents": -200000,
                "spent_home_cents": -200000,
                "hashtag_breakdown": [],
            },
        ],
        "totals": {
            "inflow_cents": 0,
            "inflow_home_cents": 0,
            "outflow_cents": 210000,
            "outflow_home_cents": 210000,
            "net_cents": -210000,
            "net_home_cents": -210000,
        },
    },
    {
        "month": {"year": 2025, "month": 12},
        "categories": [
            {
                "id": "cat-food",
                "name": "Food",
                "spent_cents": -12000,
                "spent_home_cents": -12000,
                "hashtag_breakdown": [
                    {"hashtag_ids": ["aaaa"], "spent_cents": -7000, "spent_home_cents": -7000},
                    {"hashtag_ids": ["bbbb"], "spent_cents": -5000, "spent_home_cents": -5000},
                ],
            },
            {
                "id": "cat-salary",
                "name": "Salary",
                "spent_cents": 900000,
                "spent_home_cents": 900000,
                "hashtag_breakdown": [],
            },
        ],
        "totals": {
            "inflow_cents": 900000,
            "inflow_home_cents": 900000,
            "outflow_cents": 12000,
            "outflow_home_cents": 12000,
            "net_cents": 888000,
            "net_home_cents": 888000,
        },
    },
]
RANGE_BODY = {"months": MONTHS}
NAMES = {"aaaa": "#groceries", "bbbb": "#restaurants"}


def test_shift_month_rolls_over_years():
    assert shift_month(2026, 1, -1) == (2025, 12)
    assert shift_month(2025, 12, 1) == (2026, 1)
    assert shift_month(2026, 7, -3) == (2026, 4)
    assert shift_month(2026, 7, 0) == (2026, 7)
    assert shift_month(2026, 2, -14) == (2024, 12)


def test_build_range_grid_merges_first_appearance_order():
    grid = build_range_grid(MONTHS)
    assert grid["labels"] == ["2025-11", "2025-12"]
    assert [row["name"] for row in grid["rows"]] == ["Food", "Rent", "Salary"]

    food, rent, salary = grid["rows"]
    assert food["cells"] == {"2025-11": -10000, "2025-12": -12000}
    assert rent["cells"] == {"2025-11": -200000}  # no Dec activity → no cell
    assert rent["cells"].get("2025-12") is None
    assert salary["cells"] == {"2025-12": 900000}

    # combos keep first-appearance order; #aaaa merges across both months
    assert [tuple(sub["hashtag_ids"]) for sub in food["breakdown"]] == [
        ("aaaa",),
        (),
        ("bbbb",),
    ]
    assert food["breakdown"][0]["cells"] == {"2025-11": -6000, "2025-12": -7000}
    assert food["breakdown"][2]["cells"] == {"2025-12": -5000}

    assert grid["net"] == {"2025-11": -210000, "2025-12": 888000}


def _first_column(table) -> list[str]:
    return [str(cell) for cell in table.columns[0].cells]


def test_month_grid_view_build_collapsed_expanded_and_empty():
    grid = build_range_grid(MONTHS)
    view = MonthGridView(grid, NAMES)

    collapsed = view._build()
    names = _first_column(collapsed)
    # 3 categories + net footer, breakdown hidden by default (▶ caret on Food)
    assert collapsed.row_count == 4
    assert names[0] == "▶ Food" and "    #groceries" not in names

    view._expanded.add(0)
    expanded = view._build()
    names = _first_column(expanded)
    assert expanded.row_count == 7  # + Food's 3 combos
    assert names[0] == "▼ Food"
    assert "    #groceries" in names and "    (no hashtags)" in names

    empty_view = MonthGridView(build_range_grid([]), {})
    empty = empty_view._build()
    assert empty.row_count == 2  # "(no activity)" message + net footer
    assert "(no activity in this window)" in _first_column(empty)[0]


def test_monthly_report_screen_renders_and_slides_window(monkeypatch):
    calls: list[dict] = []

    def fake_fetch_range(cfg, **kwargs):
        calls.append(kwargs)
        return RANGE_BODY

    monkeypatch.setattr(reports_cmd, "fetch_range", fake_fetch_range)
    monkeypatch.setattr("expense.tui.screens.reports.load_hashtag_name_map", lambda: NAMES)
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            await app.push_screen(MonthlyReportScreen(end=(2025, 12)))
            await wait_for(
                pilot,
                lambda: (
                    app.screen.query(MonthGridView)
                    and not app.screen.query("#content LoadingIndicator")
                ),
            )
            assert calls[0]["from_ym"] == (2025, 9)
            assert calls[0]["to_ym"] == (2025, 12)
            title = str(app.screen.query(".section-title").first().render())
            assert "2025-11 → 2025-12" in title

            await pilot.press("right_square_bracket")  # ] → newer
            await wait_for(pilot, lambda: len(calls) >= 2)
            assert calls[1]["to_ym"] == (2026, 1)

            await pilot.press("left_square_bracket")  # [ → back one older
            await wait_for(pilot, lambda: len(calls) >= 3)
            assert calls[2]["to_ym"] == (2025, 12)

    asyncio.run(scenario())


def test_grid_cells_are_theme_colored_not_literal():
    """Amount cells go through amount_cell/palette; None cells render a dim dash."""
    from expense.tui.screens.reports import _grid_cell
    from expense.tui.theme import FALLBACK

    negative = _grid_cell(-100, FALLBACK)
    assert isinstance(negative, Text) and negative.style == FALLBACK.error
    positive = _grid_cell(100, FALLBACK)
    assert isinstance(positive, Text) and positive.style == FALLBACK.success
    missing = _grid_cell(None, FALLBACK)
    assert isinstance(missing, Text) and str(missing) == "—"
