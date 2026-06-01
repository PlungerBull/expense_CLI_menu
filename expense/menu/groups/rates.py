"""Menu flows for the Exchange rates group (Step 9.5.15).

One action over `expense rates get`:
  - Look up a rate (target required, base/date optional)

Engine-direct — no cache touched. Validators reject obvious bad inputs
inline so users don't burn engine calls on lowercase codes, slashes
in dates, etc. Anything that survives validation but the engine can't
resolve (RATE_UNAVAILABLE, INVALID_CURRENCY) renders via the standard
error envelope.
"""

import questionary
import typer

from expense import config as config_module
from expense.commands import rates_cmd
from expense.context import get_verbose
from expense.errors import EngineConnectionError, EngineError, render
from expense.http import ExpenseClient
from expense.menu.groups import _common as common
from expense.menu.term import clear_screen

BACK_LABEL = "← Back"


def run_rates_menu(ctx: typer.Context) -> None:
    """Exchange rates sub-menu loop."""
    while True:
        clear_screen()
        try:
            choice = questionary.select(
                "Exchange rates — what do you like to do?",
                choices=[
                    "Look up a rate",
                    BACK_LABEL,
                ],
            ).ask()
        except KeyboardInterrupt:
            return
        if choice is None or choice == BACK_LABEL:
            return
        clear_screen()
        try:
            run_lookup(ctx)
        except typer.Exit:
            pass


# --------------------------------------------------------------- helpers


def _prompt_optional_currency(label: str) -> tuple[bool, str | None]:
    """Optional currency-code prompt. Empty → (True, None). Ctrl-C → (False, None)."""

    def _validate(raw: str) -> bool | str:
        value = raw.strip()
        if value == "":
            return True
        return common.validate_currency_code(value)

    raw = questionary.text(label, validate=_validate).ask()
    if raw is None:
        return False, None
    value = raw.strip()
    return True, (value or None)


def _prompt_optional_iso_date(label: str) -> tuple[bool, str | None]:
    """Optional YYYY-MM-DD prompt. Empty → (True, None). Ctrl-C → (False, None)."""

    def _validate(raw: str) -> bool | str:
        value = raw.strip()
        if value == "":
            return True
        return common.validate_date_iso(value)

    raw = questionary.text(label, validate=_validate).ask()
    if raw is None:
        return False, None
    value = raw.strip()
    return True, (value or None)


# --------------------------------------------------------------- 1. Lookup


def run_lookup(ctx: typer.Context) -> None:
    """`expense rates get` — required target, optional base + date."""
    target = common.prompt_validated_text(
        "Target currency? (3 letters, e.g. PEN, EUR)",
        common.validate_currency_code,
    )
    if target is None:
        return
    ok, base = _prompt_optional_currency("Base currency? (skip = USD)")
    if not ok:
        return
    ok, date = _prompt_optional_iso_date("Date? (YYYY-MM-DD, skip = today)")
    if not ok:
        return

    common.print_recap(
        "rates get",
        [
            ("--target", target),
            ("--base", base),
            ("--date", date),
        ],
    )

    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)
    params: dict = {"target": target}
    if base:
        params["base"] = base
    if date:
        params["date"] = date

    try:
        with ExpenseClient(cfg, verbose=verbose) as client:
            body = client.get("/exchange-rates", params=params)
        rates_cmd._render_rate(body)
    except (EngineError, EngineConnectionError) as err:
        output, _exit_code, use_stderr = render(err, json_mode=False)
        typer.echo(output, err=use_stderr)
    common.pause()
