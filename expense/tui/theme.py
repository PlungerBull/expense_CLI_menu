"""TUI theme + the semantic palette for Rich-rendered content.

**The terminal supplies the colours.** Every colour here is an ANSI *slot*
(`ansi_green` is slot 2), not a hex — so the palette is whatever the user's
terminal defines, and the app reads correctly on dark, light, Solarized,
Gruvbox or anything else with no detection at startup. Decided 2026-08-19;
mockup `docs/mockups/expense-world-ansi-palette.html`, picks C/D/F/H/K.
This *replaces* the hand-tuned dark palette and the planned `OSC 11`
terminal-background query — see docs/decisions.md for the reversal and what
it cost.

Widgets reference theme variables ($accent, $secondary, $text-muted, $error) in
[app.tcss](app.tcss), so the slots below are the only place a colour is chosen.

Textual has two colour worlds that don't talk: CSS rules resolve `$accent`,
but screens also build Rich `Text`/`Table` objects inside `Static` widgets, and
Rich has never heard of `$accent` — it needs a literal like `green`. `PALETTE`
is the bridge. It holds **no app reference**, which is what lets the pure
row-builders (`account_rows`, `amount_cell`, …) be unit-tested without an app,
and lets them take `palette=None` to render unstyled.

`PALETTE` is a **constant**, not a lookup. It used to be `resolve_palette(app)`,
reading `app.current_theme` on every render so a theme switch would repaint —
but there is one theme and no way to change it (the picker went with the command
palette, 2026-08-17; the light/dark pair went with the ANSI slots, 2026-08-19),
so that call provably returned the same value every time. Removed 2026-08-20
along with the theme-change signal it existed for.

It is still *derived* from the Theme rather than written out: `_rich` turns
Textual's `ansi_green` into the `green` Rich wants, so the slots above stay the
single source of truth — and no literal colour name appears in this package,
which `test_no_literal_color_styles_in_tui` requires.

The two rule constants are the backlog-4.2 product decision: amounts and
account balances are sign-colored everywhere; reconciliation statement
checkpoints (begin/end) stay plain — they're positions, not judgments.
"""

from dataclasses import dataclass
from typing import Literal

from textual.theme import Theme

EXPENSE_ANSI = Theme(
    name="expense-ansi",
    ansi=True,
    primary="ansi_blue",
    # `$secondary` carries the structural rules (header rule, list-panel border).
    # It has to be a *standard* token, not a custom `variables` entry: app.tcss is
    # parsed before on_mount registers this theme, so a custom `$rule` is an
    # undefined-variable error at startup.
    secondary="ansi_bright_black",  # pick F
    accent="ansi_blue",  # pick D — panel titles, focus borders, help keys
    foreground="ansi_default",
    background="ansi_default",
    surface="ansi_default",
    panel="ansi_default",
    success="ansi_green",  # positive amounts
    error="ansi_red",  # negative amounts / errors
    warning="ansi_default",  # pick C — see PENDING_STYLE
    dark=True,
    # An `ansi=True` theme MUST carry these: Textual's own Screen CSS references
    # `$ansi-background`, so omitting them is an undefined-variable error at
    # startup, not a missing nicety. Textual ships two sets (ansi-dark /
    # ansi-light) that disagree on every cursor and selection colour — which is
    # the light/dark split we are refusing to make. Ours sidesteps it: the
    # cursors are **reverse video** (default fg/bg, swapped), which is what
    # CursorList/CheckList already do in Rich (`cursor_list.py`), and is correct
    # on any ground by construction. Only the selections take a real colour, and
    # they take the accent, so a highlight always reads as "the app's colour".
    variables={
        "ansi-background": "ansi_default",
        "ansi-foreground": "ansi_default",
        "border": "ansi_blue",  # focused widget — pick D
        "border-blurred": "ansi_bright_black",  # unfocused — pick F
        "block-cursor-foreground": "ansi_default",
        "block-cursor-background": "ansi_default",
        "block-cursor-text-style": "reverse",
        "input-cursor-foreground": "ansi_default",
        "input-cursor-background": "ansi_default",
        "input-cursor-text-style": "reverse",
        "input-selection-background": "ansi_blue",
        "input-selection-foreground": "ansi_bright_white",
        "screen-selection-background": "ansi_blue",
        "screen-selection-foreground": "ansi_bright_white",
        # Footer key glyphs are part of pick D ("panel titles, focus borders,
        # help key glyphs"). Left undefined, Textual's fallback renders them
        # magenta, which is a colour this app uses nowhere else.
        "footer-key-foreground": "ansi_blue",
    },
)

# Pick C (2026-08-19): drafts and pending states carry **weight, not colour**.
# Slot-3 yellow is the one ANSI colour that reliably fails on a light ground,
# and this app already speaks bold/dim/reverse fluently (~40 sites), so the
# pending role joins that vocabulary instead of gambling on a colour. Not a
# colour string — `Palette.warning` is a Rich *style*, which is why the sites
# that used to write `f"bold {palette.warning}"` now just use it directly.
PENDING_STYLE = "bold"

# Where each rule applies: AMOUNT_RULE — transaction amounts, account balances,
# dashboard totals; BALANCE_RULE — reconciliation begin/end checkpoints only.
AMOUNT_RULE: Literal["sign", "income-only", "plain"] = "sign"
BALANCE_RULE: Literal["sign", "plain"] = "plain"


def _rich(color: str) -> str:
    """Textual's ANSI spelling → Rich's. `ansi_green` → `green` (slot 2)."""
    return color.removeprefix("ansi_")


@dataclass(frozen=True)
class Palette:
    """Resolved, Rich-parseable styles for the current theme.

    `success`/`error` are colours; `warning` is a style with no colour at all
    (see PENDING_STYLE) — the field name is historical, the role is "pending".
    """

    success: str
    error: str
    warning: str


PALETTE = Palette(_rich(EXPENSE_ANSI.success), _rich(EXPENSE_ANSI.error), PENDING_STYLE)

# The help card's key glyphs; same story as PALETTE — one theme, so one value.
ACCENT = _rich(EXPENSE_ANSI.accent)
