"""Root menu loop for `expense menu`.

Step 9.5.1 ships the scaffolding only: every group option prints a
"not yet wired" placeholder advertising which sub-phase ships it.
Group wiring lands in Steps 9.5.2 through 9.5.15.
"""

import sys
from collections.abc import Callable

import questionary
import typer

from expense.menu.groups.inbox import run_inbox_menu
from expense.menu.groups.log import run_log_flow
from expense.menu.groups.transactions import run_transactions_menu

QUIT = "Quit"


_GROUP_HANDLERS: dict[str, Callable[[typer.Context], None]] = {
    "Log a transaction": run_log_flow,
    "Inbox": run_inbox_menu,
    "Transactions": run_transactions_menu,
}


_GROUP_PHASES: dict[str, str] = {
    "Log a transaction": "9.5.2",
    "Inbox": "9.5.3",
    "Transactions": "9.5.4",
    "Dashboard": "9.5.5",
    "Reports": "9.5.6",
    "Reconciliations": "9.5.7",
    "Accounts": "9.5.8",
    "Categories": "9.5.9",
    "Hashtags": "9.5.10",
    "Sync": "9.5.11",
    "Activity log": "9.5.12",
    "Exchange rates": "9.5.13",
    "Auth & profile": "9.5.14",
    "Config": "9.5.15",
}


def _root_choices() -> list:
    sep = questionary.Separator("───────────────")
    return [
        "Log a transaction",
        "Inbox",
        "Transactions",
        "Dashboard",
        "Reports",
        "Reconciliations",
        sep,
        "Accounts",
        "Categories",
        "Hashtags",
        sep,
        "Sync",
        "Activity log",
        "Exchange rates",
        sep,
        "Auth & profile",
        "Config",
        sep,
        QUIT,
    ]


def _unwired(group: str) -> None:
    phase = _GROUP_PHASES[group]
    typer.echo(f"  (not yet wired — coming in Step {phase})")


def _require_tty() -> None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        typer.echo("Error: expense menu requires an interactive terminal.", err=True)
        raise typer.Exit(code=1)


def menu_command(ctx: typer.Context) -> None:
    """Interactive shell over the flat command surface.

    Opens a menu-driven walkdown of every command group. Each selection
    dispatches to the same underlying implementation `expense <command>`
    runs — no duplicated logic, no second contract to the engine. Quit
    with `Quit`, `q`, or Ctrl-C.

    Example: expense menu
    """
    _require_tty()
    while True:
        try:
            choice = questionary.select(
                "expense menu — what do you like to do?",
                choices=_root_choices(),
                use_shortcuts=False,
            ).ask()
        except KeyboardInterrupt:
            return
        if choice is None or choice == QUIT:
            return
        handler = _GROUP_HANDLERS.get(choice)
        if handler is None:
            _unwired(choice)
            continue
        try:
            handler(ctx)
        except (KeyboardInterrupt, typer.Exit):
            pass
