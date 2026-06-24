"""Menu flows for the Reports group (Step 9.5.8).

The umbrella over both reporting endpoints: the point-in-time **Outstanding
Amounts** snapshot (`GET /v1/dashboard`, account balances + current-month
panels) and the historical **Monthly report** trends (`GET /v1/reports/monthly`,
single month or a multi-month range). Two distinct engine contracts, one menu —
the separator keeps the snapshot-vs-trends distinction visible.

The Outstanding Amounts entries delegate to the dashboard group's flow
functions; the monthly-report entries wrap `expense reports monthly` and add
two display
toggles ("show hashtag breakdown?" / "expand by hashtag?") that the flat
command exposes today only as defaults — the engine round-trip is identical,
the toggle controls rendering. Hashtag names are resolved client-side against
the local cache (`expense.cache.queries.list_hashtags`).
"""

from datetime import date as date_cls

import questionary
import typer

from expense import config as config_module
from expense.commands import reports_cmd
from expense.context import get_no_cache, get_verbose
from expense.menu.groups import _common as common
from expense.menu.groups import dashboard as dashboard_group
from expense.menu.term import clear_screen

BACK_LABEL = "← Back"


def run_reports_menu(ctx: typer.Context) -> None:
    """Reports sub-menu loop."""
    while True:
        clear_screen()
        try:
            choice = questionary.select(
                "Reports — what do you like to view?",
                choices=[
                    "Outstanding Amounts (current month)",
                    "Outstanding Amounts (with archived panels)",
                    questionary.Separator("───────────────"),
                    "Monthly report (single month)",
                    "Monthly report (range)",
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
        clear_screen()
        try:
            handler(ctx)
        except typer.Exit:
            pass


def _current_year_month() -> str:
    today = date_cls.today()
    return f"{today.year:04d}-{today.month:02d}"


def run_single_month(ctx: typer.Context) -> None:
    ok, ym = common.prompt_year_month("Month (YYYY-MM)", default=_current_year_month())
    if not ok or ym is None:
        return

    show = common.prompt_yes_no("Show hashtag breakdown?", default_no=False)
    if show is None:
        return

    flags = [("--date", ym)]
    common.print_recap("reports monthly", flags)

    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)
    no_cache = get_no_cache(ctx)
    year, month = int(ym.split("-")[0]), int(ym.split("-")[1])
    try:
        reports_cmd.run_single_month(
            cfg,
            year=year,
            month=month,
            verbose=verbose,
            json_mode=False,
            show_hashtags=show,
            no_cache=no_cache,
        )
    except typer.Exit:
        pass
    common.pause()


def run_range(ctx: typer.Context) -> None:
    ok_from, ym_from = common.prompt_year_month("From (YYYY-MM)")
    if not ok_from or ym_from is None:
        return
    ok_to, ym_to = common.prompt_year_month("To (YYYY-MM)", default=ym_from)
    if not ok_to or ym_to is None:
        return

    from_ym = (int(ym_from.split("-")[0]), int(ym_from.split("-")[1]))
    to_ym = (int(ym_to.split("-")[0]), int(ym_to.split("-")[1]))
    span = reports_cmd._months_between(from_ym, to_ym)
    if span < 1:
        typer.echo(
            f"--from ({ym_from}) must be on or before --to ({ym_to}).",
            err=True,
        )
        common.pause()
        return
    if span > reports_cmd._MAX_RANGE_MONTHS:
        typer.echo(
            f"Range span is {span} months; max is {reports_cmd._MAX_RANGE_MONTHS}.",
            err=True,
        )
        common.pause()
        return

    expand = common.prompt_yes_no("Expand by hashtag?", default_no=True)
    if expand is None:
        return

    common.print_recap("reports monthly", [("--from", ym_from), ("--to", ym_to)])

    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)
    no_cache = get_no_cache(ctx)
    try:
        reports_cmd.run_range(
            cfg,
            from_ym=from_ym,
            to_ym=to_ym,
            verbose=verbose,
            json_mode=False,
            expand_hashtags=expand,
            no_cache=no_cache,
        )
    except typer.Exit:
        pass
    common.pause()


_HANDLERS = {
    "Outstanding Amounts (current month)": dashboard_group.run_current_month,
    "Outstanding Amounts (with archived panels)": dashboard_group.run_with_archived,
    "Monthly report (single month)": run_single_month,
    "Monthly report (range)": run_range,
}
