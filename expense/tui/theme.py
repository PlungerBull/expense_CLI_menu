"""TUI theme + the semantic palette for Rich-rendered content.

**The terminal supplies the colours.** Every colour here is an ANSI *slot*
(`ansi_green` is slot 2), not a hex — so the palette is whatever the user's
terminal defines, and the app reads correctly on dark, light, Solarized,
Gruvbox or anything else with no detection at startup. Decided 2026-08-19;
mockup `docs/mockups/expense-world-ansi-palette.html`, picks C/D/F/H/K.
This *replaces* the hand-tuned dark palette and the planned `OSC 11`
terminal-background query — see docs/decisions.md for the reversal and what
it cost.

Widgets reference theme variables ($accent, $text-muted, $rule, $error) in
[app.tcss](app.tcss); a theme swap recolors the whole app with no widget
changes.

Rich renderables (Text/Table inside Static widgets) can't resolve `$var`
markup — for those, `resolve_palette(app)` yields Rich-parseable styles and
widgets inject them. Two things it has to do:

  · **Translate the spelling.** Textual writes `ansi_green`; Rich rejects that
    and wants `green` (which it resolves to STANDARD slot 2 — the terminal's
    own). `_rich` strips the prefix, and leaves a hex untouched so a
    non-ANSI theme still works.
  · **Read the authored Theme field, not `theme_variables`** — the shade
    generation turns `ansi_default` surfaces into `transparent` and isn't
    Rich-parseable at all.

Screens re-render on `app.theme_changed_signal`, so injected styles follow a
runtime theme switch. There is no in-app theme *picker* any more — the command
palette that carried Textual's was removed 2026-08-17 (see docs/decisions.md).

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

THEMES = [EXPENSE_ANSI]
DEFAULT_THEME = EXPENSE_ANSI.name

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
    """Textual's ANSI spelling → Rich's. `ansi_green` → `green` (slot 2).

    A hex passes through untouched, so a non-ANSI theme (a Textual built-in,
    or a future designer palette) still resolves correctly.
    """
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


FALLBACK = Palette(_rich(EXPENSE_ANSI.success), _rich(EXPENSE_ANSI.error), PENDING_STYLE)


def resolve_palette(app) -> Palette:
    """The running theme's semantic styles, for injecting into Rich.

    Value object with no app reference — safe to hand to the pure row-builder
    functions. Call on the UI thread; `current_theme` tracks runtime theme
    switches (theme_changed_signal subscribers always read the new theme).
    Theme fields are Optional — a theme that omits one falls back to ours.
    """
    theme = app.current_theme
    return Palette(
        _rich(theme.success or EXPENSE_ANSI.success),
        _rich(theme.error or EXPENSE_ANSI.error),
        PENDING_STYLE,
    )
