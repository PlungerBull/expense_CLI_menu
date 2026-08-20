"""Semantic palette resolution + the no-literal-colors guard.

The TUI's Rich content can't use $theme-variables, so widgets inject resolved
styles via the `PALETTE` constant / `amount_cell`. Since 2026-08-19 those come
from the *terminal*: the theme holds ANSI slots (`ansi_green`), and Rich wants
that spelled `green`. These tests pin (1) that translation in both directions —
ANSI slot stripped, hex left alone — plus the pending role carrying no colour at
all, (2) the amount_cell rule matrix, (3) that no literal green/red/yellow style
strings creep back in, and (4) that a runtime theme switch rebuilds section
screens.
"""

import asyncio
import re
from pathlib import Path

import expense.tui as tui_pkg
from expense.tui.app import ExpenseApp
from expense.tui.theme import EXPENSE_ANSI, PALETTE, PENDING_STYLE, Palette, _rich
from expense.tui.widgets.cells import amount_cell, difference_cell
from tests.unit.helpers import wait_for

# A deliberately fake palette: the cell rules must be colour-agnostic.
SYNTHETIC = Palette("#0f0", "#f00", "#ff0")


def test_theme_is_ansi_slots_not_hexes():
    """The whole proposition: no colour in the theme is a fixed value.

    A hex here would pin the app to one terminal again — the 2026-08-19
    reversal exists precisely to stop that.
    """
    assert EXPENSE_ANSI.ansi is True
    for field in (
        "success",
        "error",
        "warning",
        "accent",
        "primary",
        "foreground",
        "background",
        "surface",
        "panel",
    ):
        value = getattr(EXPENSE_ANSI, field)
        assert value.startswith("ansi_"), f"{field} is {value!r}, not a terminal slot"
    assert EXPENSE_ANSI.secondary == "ansi_bright_black"  # pick F — structural rules


def test_rich_translation_strips_ansi_prefix_but_not_hexes():
    """Rich rejects Textual's `ansi_green` and resolves `green` to slot 2."""
    from rich.color import Color

    assert _rich("ansi_green") == "green"
    assert _rich("ansi_bright_black") == "bright_black"
    assert _rich("#7fbf8f") == "#7fbf8f"  # a non-ANSI theme still resolves
    # ...and the output is a terminal palette slot, not a fixed colour
    assert Color.parse(_rich("ansi_green")).number == 2


def test_palette_is_derived_from_the_theme_and_rich_can_read_it():
    """PALETTE is a constant, but a *derived* one — the slots stay the single
    source of truth, and no literal colour name appears in the package."""
    from rich.style import Style

    assert PALETTE == Palette("green", "red", PENDING_STYLE)
    for style in (PALETTE.success, PALETTE.error, PALETTE.warning):
        Style.parse(style)  # raises if Rich can't read it


def test_pending_carries_weight_not_colour():
    """Pick C: slot-3 yellow fails on a light ground, so the pending role uses
    bold. Guard against someone quietly reintroducing a colour here."""
    from rich.style import Style

    style = Style.parse(PENDING_STYLE)
    assert style.bold is True
    assert style.color is None


def test_amount_cell_rule_matrix():
    # plain rule, missing palette, or non-int cents → the bare string
    assert amount_cell(100, SYNTHETIC, "plain") == amount_cell(100, None, "sign")
    assert isinstance(amount_cell(None, SYNTHETIC, "sign"), str)
    # sign: both directions colored
    assert amount_cell(100, SYNTHETIC, "sign").style == SYNTHETIC.success
    assert amount_cell(-100, SYNTHETIC, "sign").style == SYNTHETIC.error
    assert str(amount_cell(-43250, SYNTHETIC, "sign")) == "-432.50"
    # income-only: positives colored, negatives bare
    assert amount_cell(100, SYNTHETIC, "income-only").style == SYNTHETIC.success
    assert isinstance(amount_cell(-100, SYNTHETIC, "income-only"), str)


def test_difference_cell_balances_to_a_dim_dash():
    """Phase 3 sketch picks: sign-colored when off (B), dim em dash when it
    balances (H). Zero must never render as a colored 0.00 — a balanced batch
    is the goal state, not a number to check."""
    balanced = difference_cell(0, SYNTHETIC)
    assert str(balanced) == "—" and balanced.style == "dim"
    # a missing/omitted field reads the same, never a misleading 0.00
    assert str(difference_cell(None, SYNTHETIC)) == "—"
    # off in either direction: sign-colored like every other amount
    assert difference_cell(-3500, SYNTHETIC).style == SYNTHETIC.error
    assert difference_cell(3500, SYNTHETIC).style == SYNTHETIC.success
    assert str(difference_cell(-3500, SYNTHETIC)) == "-35.00"


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


def test_tui_runs_in_ansi_mode():
    """ansi_color=True is what makes the app paint the terminal's OWN background,
    so the app fill and the terminal's window padding are one surface (no seam).
    A refactor that drops the flag silently re-introduces the seam."""
    assert ExpenseApp().ansi_color is True


def test_base_fills_are_terminal_transparent():
    """The base fills (Screen, #menu) must stay `ansi_default`, never an opaque
    hex. A hardcoded `background: $background` would paint over the terminal and
    bring back the frame (on the menu edge, if only #menu regressed). #modal
    carries `ansi_default` deliberately — an opaque card in the terminal's own
    colour, which is what makes it hide the rows behind it (pick H)."""
    tcss = (Path(tui_pkg.__file__).parent / "app.tcss").read_text()
    assert tcss.count("background: ansi_default;") >= 2, "Screen + #menu base fills"
    assert "background: $background;" not in tcss, "opaque base fill re-seams the app"


def test_modal_scrim_dims_rather_than_wipes():
    """The scrim must keep an alpha and must NOT be an ANSI colour.

    Alpha is dropped on `ansi_default`, so `background: $background 60%` — which
    is what this rule said until 2026-08-19, and what Textual's own ModalScreen
    ships — silently resolves to an OPAQUE fill and blanks the screen behind the
    modal. Every other test still passed with that bug; only a render caught it.
    Asserted on the composited output, not on the CSS text, because the CSS
    reads correct either way.
    """
    from expense.tui.screens.modals import ConfirmModal

    async def scenario():
        app = ExpenseApp()
        async with app.run_test(size=(74, 16)) as pilot:
            await app.push_screen(ConfirmModal("Delete account", "Delete BCP?"))
            await wait_for(pilot, lambda: bool(app.screen.query("#modal")))
            scrim = app.screen.styles.background
            assert scrim.a < 1.0, f"scrim is opaque ({scrim!r}) — it wipes, not dims"
            assert scrim.ansi is None, f"an ANSI scrim ({scrim!r}) loses its alpha"

    asyncio.run(scenario())
