"""The Textual app shell + the `expense world` entry point."""

import sys

import typer
from textual.app import App

from expense.context import get_no_cache, get_verbose
from expense.tui.screens.home import HomeScreen
from expense.tui.theme import DEFAULT_THEME, THEMES


class ExpenseApp(App):
    """Root app: registers themes and hosts the screen stack.

    `verbose` / `no_cache` are read off the typer context and handed to engine
    fetches (run in worker threads by each screen) so the TUI honors `--verbose`
    and stateless mode just like the flat commands.
    """

    CSS_PATH = "app.tcss"
    # no app-level `q` — it would fire from inside ConfirmModal and every list
    # (letters bubble to the App). HomeScreen binds q; ctrl+q quits everywhere.

    def __init__(self, *, verbose: bool = False, no_cache: bool = False) -> None:
        # ansi_color=True makes Textual paint the terminal's OWN default
        # background (SGR 49) instead of our fixed hex, so the app fill and the
        # terminal's window padding are one continuous surface — no seam — and it
        # follows whatever (dark) terminal it runs in. The theme stays non-ANSI,
        # so every design token keeps its authored hex; only the base fill and
        # inherited text color go through the terminal. app.tcss pins the
        # foreground back to $foreground. Rationale + scope: docs/decisions.md.
        super().__init__(ansi_color=True)
        self._verbose = verbose
        self._no_cache = no_cache

    def get_default_screen(self) -> HomeScreen:
        return HomeScreen()

    def on_mount(self) -> None:
        for theme in THEMES:
            self.register_theme(theme)
        self.theme = DEFAULT_THEME


def run_world(ctx: typer.Context) -> None:
    """TTY guard + launch. `expense world` is interactive-only."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        typer.echo("Error: expense world requires an interactive terminal.", err=True)
        raise typer.Exit(code=1)
    # Wipe the screen AND the terminal's scrollback before Textual enters the
    # alt screen (picked 2026-07-13, mockups/expense-world-adaptive-rows.html
    # STEP 5): with mouse tracking off, wheel/scrollbar gestures go to the
    # terminal itself, and Terminal.app reveals scrollback ABOVE the running
    # app — pre-launch prompt text floating over the TUI. CSI 3J leaves
    # nothing to reveal; terminals without it ignore it harmlessly. Accepted
    # cost (the tab's whole scrollback, every launch): docs/decisions.md.
    sys.stdout.write("\x1b[2J\x1b[3J\x1b[H")
    sys.stdout.flush()
    # mouse=False: the TUI is keyboard-only. Textual otherwise enables terminal
    # mouse tracking on launch (clicks/scroll act on widgets AND the terminal's
    # native text-selection/copy is suppressed). Disabling it makes the app
    # ignore the mouse and restores native select-to-copy. Every affordance has
    # a full keyboard path; see docs/decisions.md.
    ExpenseApp(verbose=get_verbose(ctx), no_cache=get_no_cache(ctx)).run(mouse=False)
