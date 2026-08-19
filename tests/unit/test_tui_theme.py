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
from expense.tui.widgets.cells import amount_cell, difference_cell
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
        app = ExpenseApp()
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


def test_difference_cell_balances_to_a_dim_dash():
    """Phase 3 sketch picks: sign-colored when off (B), dim em dash when it
    balances (H). Zero must never render as a colored 0.00 — a balanced batch
    is the goal state, not a number to check."""
    balanced = difference_cell(0, PALETTE)
    assert str(balanced) == "—" and balanced.style == "dim"
    # a missing/omitted field reads the same, never a misleading 0.00
    assert str(difference_cell(None, PALETTE)) == "—"
    # off in either direction: sign-colored like every other amount
    assert difference_cell(-3500, PALETTE).style == PALETTE.error
    assert difference_cell(3500, PALETTE).style == PALETTE.success
    assert str(difference_cell(-3500, PALETTE)) == "-35.00"


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
    """Switching themes at runtime must rebuild the card — Rich
    bakes resolved hexes at build time — but must NOT re-fetch: it repaints from
    the data already in memory (backlog §5)."""
    fetches: list = []
    builds: list = []
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())
    monkeypatch.setattr(
        "expense.commands.accounts_cmd.fetch_accounts",
        lambda cfg, **k: (fetches.append(1), {"items": []})[1],
    )

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = AccountsScreen()
            orig_build = screen.build
            monkeypatch.setattr(
                screen, "build", lambda data: (builds.append(1), orig_build(data))[1]
            )
            await app.push_screen(screen)
            await wait_for(pilot, lambda: fetches and builds)
            fetched, built = len(fetches), len(builds)
            app.theme = "textual-dark"  # builtin themes are pre-registered
            await wait_for(pilot, lambda: len(builds) > built)  # re-rendered
            assert len(fetches) == fetched  # ...but did NOT re-fetch

    asyncio.run(scenario())


def test_tui_runs_in_ansi_mode():
    """ansi_color=True is what makes the app paint the terminal's OWN background,
    so the app fill and the terminal's window padding are one surface (no seam).
    A refactor that drops the flag silently re-introduces the seam."""
    assert ExpenseApp().ansi_color is True


def test_base_fills_are_terminal_transparent():
    """The base fills (Screen, #menu) must stay `ansi_default`, never an opaque
    hex. A hardcoded `background: $background` would paint over the terminal and
    bring back the frame (on the menu edge, if only #menu regressed). The modal
    dim scrim `background: $background 60%` is alpha-blended, not an opaque fill,
    so it deliberately doesn't match the forbidden exact string."""
    tcss = (Path(tui_pkg.__file__).parent / "app.tcss").read_text()
    assert tcss.count("background: ansi_default;") >= 2, "Screen + #menu base fills"
    assert "background: $background;" not in tcss, "opaque base fill re-seams the app"
