"""Menu flows for the Config group (Step 9.5.6).

Wraps `expense config get/set/clear`. No engine calls and no cache touch —
this is pure local-file I/O against ~/.expense-config (or whatever
EXPENSE_CONFIG points at). First step of the freshman walk: a new user
can set engine URL + PAT + main currency without ever leaving the menu.
"""

import questionary
import typer

from expense import config as config_module
from expense.commands import config_cmd
from expense.menu import prompts
from expense.menu.groups import _common as common

BACK_LABEL = "← Back"


def run_config_menu(ctx: typer.Context) -> None:
    """Config sub-menu loop."""
    while True:
        try:
            choice = questionary.select(
                "Config — what do you like to do?",
                choices=[
                    "Show current config",
                    "Set engine URL",
                    "Set token (PAT)",
                    "Set main currency (local default)",
                    "Clear all config",
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


# ----------------------------------------------------------- 1. Show


def run_show(ctx: typer.Context) -> None:
    try:
        config_cmd.get_cmd(show_token=False, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 2. Set engine URL


def _validate_engine_url(raw: str) -> bool | str:
    value = raw.strip()
    if not value:
        return "Engine URL is required."
    if not (value.startswith("http://") or value.startswith("https://")):
        return "Must start with http:// or https://"
    return True


def run_set_engine_url(ctx: typer.Context) -> None:
    value = common.prompt_validated_text("Engine URL", _validate_engine_url)
    if value is None:
        return
    common.print_recap("config set", [("--engine-url", value)])
    confirm = common.prompt_yes_no("Confirm and save?", default_no=True)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        return
    try:
        config_cmd.set_cmd(engine_url=value, token=None, main_currency=None)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 3. Set token


def _validate_token(raw: str) -> bool | str:
    if not raw or not raw.strip():
        return "Token is required."
    return True


def run_set_token(ctx: typer.Context) -> None:
    if config_module.load() is None:
        typer.echo("Set engine URL first.", err=True)
        common.pause()
        return
    value = common.prompt_validated_text("Token (PAT, ewe_pat_…)", _validate_token, password=True)
    if value is None:
        return
    # Intentionally no recap — printing `expense config set --token <raw>`
    # would teach the user a command that leaks their PAT into shell history.
    confirm = common.prompt_yes_no("Save token?", default_no=True)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        return
    try:
        config_cmd.set_cmd(engine_url=None, token=value, main_currency=None)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 4. Set main currency


def run_set_main_currency(ctx: typer.Context) -> None:
    if config_module.load() is None:
        typer.echo("Set engine URL first.", err=True)
        common.pause()
        return
    value = common.prompt_validated_text(
        "Main currency (local default)", common.validate_currency_code
    )
    if value is None:
        return
    common.print_recap("config set", [("--main-currency", value)])
    confirm = common.prompt_yes_no("Confirm and save?", default_no=True)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        return
    try:
        config_cmd.set_cmd(engine_url=None, token=None, main_currency=value)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 5. Clear


def run_clear(ctx: typer.Context) -> None:
    path = config_module.config_path()
    if not path.exists():
        typer.echo("No config file to clear.")
        common.pause()
        return
    confirmed = prompts.confirm_destructive(
        f"Clear all config at {path}?",
        warning="Wipes engine URL, token, and main currency. You'll need to re-bootstrap.",
    )
    if not confirmed:
        typer.echo("Aborted.")
        return
    try:
        config_cmd.clear_cmd(yes=True)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- dispatch

_HANDLERS = {
    "Show current config": run_show,
    "Set engine URL": run_set_engine_url,
    "Set token (PAT)": run_set_token,
    "Set main currency (local default)": run_set_main_currency,
    "Clear all config": run_clear,
}
