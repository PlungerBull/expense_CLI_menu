"""Overview TUI screen — the band, month math, grid merge, pure render, pilot nav.

The screen Outstanding Amounts and the Monthly report became on 2026-08-29. The
`PeopleView` tests came here from `test_tui_smoke.py` with the widget itself.
"""

import asyncio
import io

import pytest
from rich.console import Console
from rich.text import Text

import expense.commands.reports_cmd as reports_cmd
from expense.commands import dashboard_cmd
from expense.commands.reports_cmd import build_range_grid
from expense.tui.app import ExpenseApp
from expense.tui.screens.overview import (
    PANEL_ROWS,
    MonthGridView,
    OverviewScreen,
    PeopleView,
    _balances_panel,
    shift_month,
)
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
                "spent_home_cents": -10000,
                "unconverted_count": 0,
                "hashtag_breakdown": [
                    {"hashtag_ids": ["aaaa"], "spent_home_cents": -6000, "unconverted_count": 0},
                    {"hashtag_ids": [], "spent_home_cents": -4000, "unconverted_count": 0},
                ],
            },
            {
                "id": "cat-rent",
                "name": "Rent",
                "spent_home_cents": -200000,
                "unconverted_count": 0,
                "hashtag_breakdown": [],
            },
        ],
        "totals": {
            "inflow_home_cents": 0,
            "outflow_home_cents": 210000,
            "net_home_cents": -210000,
            "unconverted_count": 0,
        },
    },
    {
        "month": {"year": 2025, "month": 12},
        "categories": [
            {
                "id": "cat-food",
                "name": "Food",
                "spent_home_cents": -12000,
                "unconverted_count": 0,
                "hashtag_breakdown": [
                    {"hashtag_ids": ["aaaa"], "spent_home_cents": -7000, "unconverted_count": 0},
                    {"hashtag_ids": ["bbbb"], "spent_home_cents": -5000, "unconverted_count": 0},
                ],
            },
            {
                "id": "cat-salary",
                "name": "Salary",
                "spent_home_cents": 900000,
                "unconverted_count": 0,
                "hashtag_breakdown": [],
            },
        ],
        "totals": {
            "inflow_home_cents": 900000,
            "outflow_home_cents": 12000,
            "net_home_cents": 888000,
            "unconverted_count": 0,
        },
    },
]
RANGE_BODY = {"months": MONTHS}
NAMES = {"aaaa": "#groceries", "bbbb": "#restaurants"}

#: Seven accounts against a PANEL_ROWS of 5 — the cap has to bite for the
#: cap tests to mean anything.
SEVEN_ACCOUNTS = [
    {"name": f"Bank {i}", "currency_code": "PEN", "current_balance_cents": 1000 * i}
    for i in range(1, 8)
]

_PEOPLE = [
    {"name": "Majo", "currency_code": "PEN", "current_balance_cents": 34000},
    {"name": "Diego", "currency_code": "USD", "current_balance_cents": 0},
    {"name": "Ana", "currency_code": "PEN", "current_balance_cents": -1200},
]

DASHBOARD = {
    "month": {"year": 2025, "month": 12},
    "bank_accounts": SEVEN_ACCOUNTS,
    "people": _PEOPLE,
    "totals": {
        "inflow_home_cents": 0,
        "outflow_home_cents": 0,
        "net_home_cents": 0,
        "unconverted_count": 0,
    },
}


def _text(renderable) -> str:
    con = Console(file=io.StringIO(), width=80)
    con.print(renderable)
    return con.file.getvalue()


def _cents(cells: dict) -> dict:
    """Just the amounts out of a grid row's cell dicts, for readable asserts."""
    return {label: cell["cents"] for label, cell in cells.items()}


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
    # A cell carries its unconverted_count alongside the figure — `None` alone
    # cannot say whether a blank is "no activity" or "the engine refused to
    # price this".
    assert _cents(food["cells"]) == {"2025-11": -10000, "2025-12": -12000}
    assert _cents(rent["cells"]) == {"2025-11": -200000}  # no Dec activity → no cell
    assert rent["cells"].get("2025-12") is None
    assert _cents(salary["cells"]) == {"2025-12": 900000}

    # combos keep first-appearance order; #aaaa merges across both months
    assert [tuple(sub["hashtag_ids"]) for sub in food["breakdown"]] == [
        ("aaaa",),
        (),
        ("bbbb",),
    ]
    assert _cents(food["breakdown"][0]["cells"]) == {"2025-11": -6000, "2025-12": -7000}
    assert _cents(food["breakdown"][2]["cells"]) == {"2025-12": -5000}

    assert _cents(grid["totals"]["net"]) == {"2025-11": -210000, "2025-12": 888000}
    assert all(cell["unconverted"] == 0 for cell in grid["totals"]["net"].values())
    # inflow/outflow ride alongside net off the same month payload (2026-08-29)
    assert set(grid["totals"]) == set(reports_cmd.TOTALS_KEYS)


def test_build_range_grid_carries_the_unconverted_count_and_drops_empty_rows():
    """Three states: a figure, a real zero (no activity), and an unpriceable month."""
    months = [
        {
            "month": {"year": 2026, "month": 1},
            "categories": [
                {
                    "id": "cat-food",
                    "name": "Food",
                    "spent_home_cents": -10000,
                    "unconverted_count": 0,
                    "hashtag_breakdown": [],
                },
                {
                    "id": "cat-gifts",
                    "name": "Gifts",
                    "spent_home_cents": 0,
                    "unconverted_count": 0,
                    "hashtag_breakdown": [],
                },
            ],
            "totals": {"net_home_cents": -10000, "unconverted_count": 0},
        },
        {
            "month": {"year": 2026, "month": 2},
            "categories": [
                {
                    "id": "cat-food",
                    "name": "Food",
                    "spent_home_cents": None,
                    "unconverted_count": 3,
                    "hashtag_breakdown": [],
                },
                {
                    "id": "cat-gifts",
                    "name": "Gifts",
                    "spent_home_cents": 0,
                    "unconverted_count": 0,
                    "hashtag_breakdown": [],
                },
            ],
            "totals": {"net_home_cents": None, "unconverted_count": 3},
        },
    ]
    grid = build_range_grid(months)

    # Gifts spent nothing in either month, so it is not drawn at all.
    assert [row["name"] for row in grid["rows"]] == ["Food"]

    feb = grid["rows"][0]["cells"]["2026-02"]
    assert feb == {"cents": None, "unconverted": 3}
    assert not reports_cmd.cell_is_empty(feb)  # unpriceable is NOT empty
    assert reports_cmd.format_grid_cell(feb) == "3 unrated"

    # ...and a genuinely empty cell reads as the no-activity mark, not as 0.00.
    assert reports_cmd.format_grid_cell(None) == reports_cmd.NO_ACTIVITY_MARK
    assert reports_cmd.format_grid_cell({"cents": 0, "unconverted": 0}) == (
        reports_cmd.NO_ACTIVITY_MARK
    )
    assert grid["totals"]["net"]["2026-02"] == {"cents": None, "unconverted": 3}
    # all three totals share the month's one count, so they fail together
    assert grid["totals"]["inflow"]["2026-02"]["unconverted"] == 3
    assert grid["totals"]["outflow"]["2026-02"]["unconverted"] == 3


def _first_column(table) -> list[str]:
    return [str(cell) for cell in table.columns[0].cells]


def test_month_grid_view_build_collapsed_expanded_and_empty():
    grid = build_range_grid(MONTHS)
    view = MonthGridView(grid, NAMES)

    collapsed = view._build()
    names = _first_column(collapsed)
    # 3 categories + 3 totals rows, breakdown hidden by default (▶ caret on Food)
    assert collapsed.row_count == 6
    assert names[0] == "▶ Food" and "    #groceries" not in names

    view._expanded.add(0)
    expanded = view._build()
    names = _first_column(expanded)
    assert expanded.row_count == 9  # + Food's 3 combos
    assert names[0] == "▼ Food"
    assert "    #groceries" in names and "    (no hashtags)" in names

    empty_view = MonthGridView(build_range_grid([]), {})
    empty = empty_view._build()
    assert empty.row_count == 4  # "(no activity)" message + the 3 totals rows
    assert "(no activity in this window)" in _first_column(empty)[0]


def test_overview_renders_and_slides_the_month_window(monkeypatch):
    calls: list[dict] = []

    def fake_fetch_range(cfg, **kwargs):
        calls.append(kwargs)
        return RANGE_BODY

    monkeypatch.setattr(reports_cmd, "fetch_range", fake_fetch_range)
    monkeypatch.setattr(dashboard_cmd, "fetch_dashboard", lambda cfg, **kw: DASHBOARD)
    monkeypatch.setattr("expense.tui.screens.overview.load_hashtag_name_map", lambda: NAMES)
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            await app.push_screen(OverviewScreen(end=(2025, 12)))
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

            # The month window rides the page keys since 2026-08-27 (option C,
            # mockups/expense-world-movement-keys.html). `pgup` is newer, `pgdn`
            # older — paging down walks back in time, like a newest-first ledger.
            await pilot.press("pageup")  # pgup → newer
            await wait_for(pilot, lambda: len(calls) >= 2)
            assert calls[1]["to_ym"] == (2026, 1)

            await pilot.press("pagedown")  # pgdn → back one older
            await wait_for(pilot, lambda: len(calls) >= 3)
            assert calls[2]["to_ym"] == (2025, 12)

    asyncio.run(scenario())


def test_grid_cells_are_theme_colored_not_literal():
    """Amount cells go through the palette; empty cells dash; unpriced ones warn."""
    from expense.tui.screens.overview import _grid_cell
    from expense.tui.theme import PALETTE

    negative = _grid_cell({"cents": -100, "unconverted": 0}, PALETTE)
    assert isinstance(negative, Text) and negative.style == PALETTE.error
    positive = _grid_cell({"cents": 100, "unconverted": 0}, PALETTE)
    assert isinstance(positive, Text) and positive.style == PALETTE.success

    # No activity — a dim dash, as before.
    missing = _grid_cell(None, PALETTE)
    assert isinstance(missing, Text) and str(missing) == "—"
    zero = _grid_cell({"cents": 0, "unconverted": 0}, PALETTE)
    assert isinstance(zero, Text) and str(zero) == "—"

    # Unpriceable — its own warning-colored figure, never a dash and never 0.00.
    unrated = _grid_cell({"cents": None, "unconverted": 3}, PALETTE)
    assert isinstance(unrated, Text) and str(unrated) == "3 unrated"
    assert unrated.style == PALETTE.warning
    assert str(unrated) != str(missing)


# --- the band ---------------------------------------------------------------


def test_accounts_panel_caps_at_five_rows_and_never_filters_the_data():
    """The cap truncates *drawing*. Seven accounts in, five rows out, seven kept.

    The second half is the point: `expense accounts` and `expense dashboard`
    still show every account, and a future reader must not mistake the cap for a
    filter on the fetch (owner decision, 2026-08-29 — the overflow is simply not
    drawn, because the Accounts screen is one keypress away).
    """
    out = _text(_balances_panel(SEVEN_ACCOUNTS))
    drawn = [name for name in ("Bank 1", "Bank 2", "Bank 3", "Bank 4", "Bank 5") if name in out]
    assert len(drawn) == PANEL_ROWS
    assert "Bank 6" not in out and "Bank 7" not in out
    assert len(SEVEN_ACCOUNTS) == 7  # the source list is untouched


def test_panels_are_lean_so_the_grid_keeps_its_net_row():
    """No box padding, no header row — the measurement the layout rests on.

    Drawn boxed (`box.SIMPLE` + a header row), the band costs 12 lines instead
    of 8 and pushes the grid's `net` row below the fold on a 120x34 terminal:
    you see inflow and outflow and not the number they add up to. Two asserts
    guarding a decision nobody will remember making.
    """
    table = _balances_panel(SEVEN_ACCOUNTS)
    assert table.box is None
    assert table.show_header is False
    assert "Balance" not in _text(table)


def test_people_panel_caps_the_outstanding_but_never_the_settled_count():
    """`PANEL_ROWS` and the settled fold are different mechanisms.

    A settled person is folded, never dropped (2026-08-16) — capping the count
    row away would delete the only trace she exists. The cap applies to the
    outstanding rows; the settled count row is always drawn.
    """
    crowd = [
        {"name": f"P{i}", "currency_code": "PEN", "current_balance_cents": 100 * i}
        for i in range(1, 8)
    ] + [{"name": "Settled", "currency_code": "PEN", "current_balance_cents": 0}]
    out = _text(PeopleView(crowd)._build())
    assert "P5" in out and "P6" not in out and "P7" not in out
    assert "1 settled" in out


def test_expanding_the_settled_fold_is_never_capped():
    """One keypress must show *exactly who* — a capped expansion would lie."""
    settled = [
        {"name": f"S{i}", "currency_code": "PEN", "current_balance_cents": 0} for i in range(1, 8)
    ]
    view = PeopleView(settled)
    view.action_expand()
    out = _text(view._build())
    assert all(f"S{i}" in out for i in range(1, 8))


# --- the totals rows --------------------------------------------------------


def test_grid_draws_inflow_outflow_and_net_in_order():
    view = MonthGridView(build_range_grid(MONTHS), NAMES)
    assert _first_column(view._build())[-3:] == list(reports_cmd.TOTALS_KEYS)


def test_an_unpriced_month_marks_every_totals_row_not_just_net():
    """All three share the month's one count, so they fail together.

    Replaces `_totals_table`'s collapse-to-one-line behaviour, which a grid
    cannot express per month: the column says `3 unrated` three times instead.
    """
    months = [
        {
            "month": {"year": 2026, "month": 2},
            "categories": [
                {"id": "c", "name": "Food", "spent_home_cents": None, "unconverted_count": 3}
            ],
            "totals": {
                "inflow_home_cents": None,
                "outflow_home_cents": None,
                "net_home_cents": None,
                "unconverted_count": 3,
            },
        }
    ]
    out = _text(MonthGridView(build_range_grid(months), {})._build())
    assert out.count("3 unrated") >= 4  # Food + the three totals rows
    assert "0.00" not in out


# --- the screen -------------------------------------------------------------


def _stub_reads(monkeypatch, *, dashboard=None, range_body=None):
    monkeypatch.setattr(dashboard_cmd, "fetch_dashboard", dashboard or (lambda c, **k: DASHBOARD))
    monkeypatch.setattr(reports_cmd, "fetch_range", range_body or (lambda c, **k: RANGE_BODY))
    monkeypatch.setattr("expense.tui.screens.overview.load_hashtag_name_map", lambda: NAMES)
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())


@pytest.mark.parametrize("failing", ["dashboard", "range"])
def test_either_fetch_failing_takes_the_whole_screen_to_the_error_card(monkeypatch, failing):
    """No partial render: half a report still looks like a whole one."""

    def boom(*_a, **_kw):
        raise RuntimeError("engine down")

    _stub_reads(
        monkeypatch,
        dashboard=boom if failing == "dashboard" else None,
        range_body=boom if failing == "range" else None,
    )

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            await app.push_screen(OverviewScreen(end=(2025, 12)))
            await wait_for(pilot, lambda: app.screen.query(".error"))
            assert not app.screen.query(MonthGridView)

    asyncio.run(scenario())


def test_the_title_says_balances_are_todays_even_after_paging_back(monkeypatch):
    """The label is the whole mitigation for a band that cannot follow the window.

    There is no historical-balance endpoint, so `pgdn` moves the grid and leaves
    the balances on today. Without this assert a future tidy-up deletes the one
    sentence that says so.
    """
    _stub_reads(monkeypatch)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            await app.push_screen(OverviewScreen(end=(2025, 12)))
            await wait_for(pilot, lambda: app.screen.query(MonthGridView))
            assert "balances today" in str(app.screen.query(".section-title").first().render())

            await pilot.press("pagedown")
            await wait_for(pilot, lambda: app.screen.query(MonthGridView))
            assert "balances today" in str(app.screen.query(".section-title").first().render())

    asyncio.run(scenario())


def test_the_month_window_keys_beat_the_scroll_container(monkeypatch):
    """`pgdn`/`pgup` must slide the window, not page-scroll the card.

    Regression: `#content` is a `VerticalScroll`, and once the band made the
    card taller than a short terminal the scroll container began handling these
    keys itself — so the window silently stopped moving on exactly the terminals
    where the card overflows. The screen's bindings are `priority=True` for this
    reason; this test is what says so out loud.
    """
    calls: list[dict] = []

    def recording_range(cfg, **kwargs):
        calls.append(kwargs)
        return RANGE_BODY

    _stub_reads(monkeypatch, range_body=recording_range)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test(size=(80, 12)) as pilot:  # deliberately overflowing
            await app.push_screen(OverviewScreen(end=(2025, 12)))
            await wait_for(pilot, lambda: len(calls) >= 1)
            await pilot.press("pagedown")
            await wait_for(pilot, lambda: len(calls) >= 2)
            assert calls[1]["to_ym"] == (2025, 11)

    asyncio.run(scenario())


# ---------------------------------------------------------------- natural width
# Option A of docs/mockups/expense-world-overview-width.html, picked by the owner
# 2026-08-29: every table on this screen is `expand=False`, so it is exactly as
# wide as its content no matter how wide the terminal is. The bug these lock out
# is the one that shipped: `expand=True` plus `ratio=1` on the grid's label column
# handed that column every spare cell, so on a wide terminal the amounts rode the
# right edge with a lake of blanks in front of them. Asserting "narrower than the
# console" rather than an exact width keeps these from breaking on a font or a
# label change while still failing the moment a table starts filling the pane.


def _widest(renderable, width: int) -> int:
    """Longest rendered line, drawn into a console of `width` columns."""
    con = Console(file=io.StringIO(), width=width)
    con.print(renderable)
    return max(len(line.rstrip()) for line in con.file.getvalue().splitlines())


def test_the_balances_panel_takes_its_natural_width_not_the_console_width():
    rows = [
        {"name": "BCP Signature USD", "currency_code": "USD", "current_balance_cents": -53284},
        {"name": "BCP PEN", "currency_code": "PEN", "current_balance_cents": 501893},
    ]
    panel = _balances_panel(rows)
    # The widest name is 17 chars; + currency + a right-aligned amount lands well
    # under 50, and must not grow when the terminal does.
    assert _widest(panel, 200) == _widest(panel, 80) <= 50


def test_the_month_grid_takes_its_natural_width_not_the_console_width():
    view = MonthGridView(build_range_grid(MONTHS), NAMES)
    narrow, wide = _widest(view._build(), 80), _widest(view._build(), 200)
    assert narrow == wide
    # Two months of test data: a label column plus two amount columns is nowhere
    # near 200. The pre-fix render filled the console exactly.
    assert wide <= 60


def test_neither_table_expands_and_no_column_carries_a_ratio():
    """The sizing rule, asserted on the tables themselves.

    Checked here rather than by scanning the source, which would also match the
    module docstring where the old `expand=True` is quoted as history.
    """
    panel = _balances_panel([{"name": "A", "currency_code": "PEN", "current_balance_cents": 100}])
    grid = MonthGridView(build_range_grid(MONTHS), NAMES)._build()
    for table in (panel, grid):
        assert table.expand is False
        # `ratio` only applies to an expanding table; leaving one behind would
        # read as live sizing while doing nothing.
        assert all(col.ratio is None for col in table.columns)
