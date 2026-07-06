"""Backlog 4.2 — semantic palette resolution + the no-literal-colors guard.

The TUI's Rich content can't use $theme-variables, so widgets inject resolved
hexes via `resolve_palette` / `amount_cell`. These tests pin (1) the Textual
contract that the plain "success"/"error"/"warning" variables resolve to the
Theme's exact raw hex (an implementation detail of ColorSystem — a Textual
upgrade that changes it should fail here, loudly), (2) the amount_cell rule
matrix, (3) that no literal green/red/yellow style strings creep back in, and
(4) that a runtime theme switch rebuilds section screens.
"""

import asyncio
import re
from pathlib import Path

import expense.tui as tui_pkg
from expense.tui.app import ExpenseApp
from expense.tui.screens.accounts import AccountsScreen
from expense.tui.theme import EXPENSE_DARK, FALLBACK, Palette, resolve_palette
from expense.tui.widgets.cells import amount_cell
from tests.unit.helpers import wait_for

PALETTE = Palette("#0f0", "#f00", "#ff0")


def test_fallback_matches_theme_constants():
    assert FALLBACK == Palette(EXPENSE_DARK.success, EXPENSE_DARK.error, EXPENSE_DARK.warning)


def test_resolve_palette_returns_raw_theme_hexes():
    """Contract: resolve_palette == the authored Theme hexes, exactly.

    Reads app.current_theme, NOT theme_variables — the variable generation
    HSL-roundtrips colors and drifts channels by one bit (e.g. warning
    #d6b878 → #D5B878), which would break color parity with the approved
    mockups. Also pins that a runtime switch is picked up.
    """

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test():
            assert resolve_palette(app) == FALLBACK
            app.theme = "textual-dark"  # builtin themes are pre-registered
            switched = resolve_palette(app)
            assert switched != FALLBACK and switched.success.startswith("#")

    asyncio.run(scenario())


def test_amount_cell_rule_matrix():
    # plain rule, missing palette, or non-int cents → the bare string
    assert amount_cell(100, PALETTE, "plain") == amount_cell(100, None, "sign")
    assert isinstance(amount_cell(None, PALETTE, "sign"), str)
    # sign: both directions colored
    assert amount_cell(100, PALETTE, "sign").style == PALETTE.success
    assert amount_cell(-100, PALETTE, "sign").style == PALETTE.error
    assert str(amount_cell(-43250, PALETTE, "sign")) == "-432.50"
    # income-only: positives colored, negatives bare
    assert amount_cell(100, PALETTE, "income-only").style == PALETTE.success
    assert isinstance(amount_cell(-100, PALETTE, "income-only"), str)


def test_no_literal_color_styles_in_tui():
    """Guard: hardcoded green/red/yellow must never reappear under expense/tui/.

    create_forms.py is exempt — its ("#5ab87a", "green") pairs are user-facing
    swatch *names* (account/category color picker data), not Rich styles.
    """
    tui_dir = Path(tui_pkg.__file__).parent
    pattern = re.compile(r"""["'](green|red|yellow)["']""")
    offenders = [
        f"{path.name}: {match.group(0)}"
        for path in sorted(tui_dir.rglob("*.py"))
        if path.name != "create_forms.py"
        for match in pattern.finditer(path.read_text())
    ]
    assert not offenders, f"literal color styles bypass the theme: {offenders}"


def test_theme_change_rebuilds_section_screens(monkeypatch):
    """Switching themes at runtime (ctrl+p palette) must re-fetch/re-render."""
    calls: list = []
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())
    monkeypatch.setattr(
        "expense.commands.accounts_cmd.fetch_accounts",
        lambda cfg, **k: (calls.append(1), {"items": []})[1],
    )

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = AccountsScreen()
            await app.push_screen(screen)
            await wait_for(pilot, lambda: calls)
            seen = len(calls)
            app.theme = "textual-dark"  # builtin themes are pre-registered
            await wait_for(pilot, lambda: len(calls) > seen)

    asyncio.run(scenario())
