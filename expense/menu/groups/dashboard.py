"""Menu flows for the Dashboard group (Step 9.5.5).

Wraps `expense dashboard` with and without --include-archived. No payload
construction or HTTP logic — flows delegate to dashboard_cmd.dashboard().
"""

import questionary
import typer

from expense.commands import dashboard_cmd
from expense.menu.groups import _common as common

BACK_LABEL = "← Back"


def run_dashboard_menu(ctx: typer.Context) -> None:
    """Dashboard sub-menu loop."""
    while True:
        try:
            choice = questionary.select(
                "Dashboard — what do you like to view?",
                choices=[
                    "View dashboard (current month)",
                    "View dashboard with archived panels",
                    BACK_LABEL,
                ],
            ).ask()
        except KeyboardInterrupt:
            return
        if choice is None or choice == BACK_LABEL:
            return
        handler = _HANDLERS.get(choice)
        if handler is None:
            continue
        try:
            handler(ctx)
        except typer.Exit:
            pass


def run_current_month(ctx: typer.Context) -> None:
    try:
        dashboard_cmd.dashboard(ctx, include_archived=False, json_output=False)
    except typer.Exit:
        pass
    common.pause()


def run_with_archived(ctx: typer.Context) -> None:
    try:
        dashboard_cmd.dashboard(ctx, include_archived=True, json_output=False)
    except typer.Exit:
        pass
    common.pause()


_HANDLERS = {
    "View dashboard (current month)": run_current_month,
    "View dashboard with archived panels": run_with_archived,
}
