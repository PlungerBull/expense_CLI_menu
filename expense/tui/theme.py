"""TUI themes.

Dark-neutral by default. Themes are Textual `Theme` objects — adding a new
theme is one object + `app.register_theme(...)`. Widgets reference theme
variables ($surface, $accent, $text-muted, $success/$error) in
[app.tcss](app.tcss), so a theme swap recolors the whole app with no widget
changes.
"""

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
    warning="#d8b066",
    error="#cf7d7d",  # negative amounts / errors
    dark=True,
)

THEMES = [EXPENSE_DARK]
DEFAULT_THEME = EXPENSE_DARK.name
