"""TUI themes + the semantic palette for Rich-rendered content.

Dark-neutral by default. Themes are Textual `Theme` objects — adding a new
theme is one object + `app.register_theme(...)`. Widgets reference theme
variables ($surface, $accent, $text-muted, $error) in [app.tcss](app.tcss),
so a theme swap recolors the whole app with no widget changes.

Rich renderables (Text/Table inside Static widgets) can't resolve `$var`
markup — for those, `resolve_palette(app)` yields Rich-parseable hexes and
widgets inject them as styles. It reads `app.current_theme`'s own fields
(the exact authored hex): the `theme_variables` shade generation HSL-
roundtrips colors and can drift a channel by one bit, the `text-*` variants
are auto-tinted, and `text-muted` ("auto 60%") isn't Rich-parseable at all.
Screens re-render on `app.theme_changed_signal`, so baked hexes follow
runtime theme switches. There is no in-app theme *picker* any more — the
command palette that carried Textual's was removed 2026-08-17 (see
docs/decisions.md); the signal still matters because the light theme will set
`app.theme` from terminal detection at startup.

The two rule constants are the backlog-4.2 product decision (approved via
docs/mockups/expense-world-amount-colors-4.2.html): amounts and account
balances are sign-colored everywhere; reconciliation statement checkpoints
(begin/end) stay plain — they're positions, not judgments.
"""

from dataclasses import dataclass
from typing import Literal

from textual.theme import Theme

EXPENSE_DARK = Theme(
    name="expense-dark",
    primary="#9aa7b2",  # cool-grey accent (focus, headers, selection)
    secondary="#6f7680",
    accent="#9aa7b2",
    foreground="#d6d6da",
    background="#0e0e11",
    surface="#16161a",
    panel="#1d1d22",
    success="#7fbf8f",  # positive amounts
    warning="#d6b878",  # draft/pending states
    error="#cf8d8d",  # negative amounts / errors
    dark=True,
)

THEMES = [EXPENSE_DARK]
DEFAULT_THEME = EXPENSE_DARK.name

# Where each rule applies: AMOUNT_RULE — transaction amounts, account balances,
# dashboard totals; BALANCE_RULE — reconciliation begin/end checkpoints only.
AMOUNT_RULE: Literal["sign", "income-only", "plain"] = "sign"
BALANCE_RULE: Literal["sign", "plain"] = "plain"


@dataclass(frozen=True)
class Palette:
    """Resolved, Rich-parseable hex colors for the current theme."""

    success: str
    error: str
    warning: str


FALLBACK = Palette(EXPENSE_DARK.success, EXPENSE_DARK.error, EXPENSE_DARK.warning)


def resolve_palette(app) -> Palette:
    """The running theme's semantic colors, for injecting into Rich styles.

    Value object with no app reference — safe to hand to the pure row-builder
    functions. Call on the UI thread; `current_theme` tracks runtime theme
    switches (theme_changed_signal subscribers always read the new theme).
    Theme fields are Optional — a theme that omits one falls back to the
    HSL-roundtripped `theme_variables` value, then to our own defaults.
    """
    theme = app.current_theme
    tv = app.theme_variables
    return Palette(
        theme.success or tv.get("success", FALLBACK.success),
        theme.error or tv.get("error", FALLBACK.error),
        theme.warning or tv.get("warning", FALLBACK.warning),
    )
