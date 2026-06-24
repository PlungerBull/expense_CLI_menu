"""Outstanding Amounts view flows (Step 9.5.5).

Wraps the `expense dashboard` command (`GET /v1/dashboard`) with and without
--include-archived. No payload construction or HTTP logic — flows delegate to
dashboard_cmd.dashboard().

Surfaced under the Reports umbrella menu (`expense.menu.groups.reports`) as the
"Outstanding Amounts" entries; there is no standalone sub-menu.
"""

import typer

from expense.commands import dashboard_cmd
from expense.menu.groups import _common as common


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
