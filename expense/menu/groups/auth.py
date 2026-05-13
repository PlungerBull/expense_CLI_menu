"""Menu flows for the Auth & profile group (Step 9.5.7).

Wraps `expense auth me / bootstrap / profile / settings`. Every action
collects inputs interactively, prints the equivalent flat command for
audit, confirms, then delegates to the same Typer functions that power
the flat surface — same pattern as Step 9.5.6 (Config). The second
freshman bootstrap leg: with this in place, a new user can finish "set
engine URL → set token → bootstrap → see profile" without ever leaving
the menu.
"""

import questionary
import typer

from expense import config as config_module
from expense.commands import auth_cmd
from expense.menu import prompts
from expense.menu.groups import _common as common

BACK_LABEL = "← Back"


def run_auth_menu(ctx: typer.Context) -> None:
    """Auth & profile sub-menu loop."""
    while True:
        try:
            choice = questionary.select(
                "Auth & profile — what do you like to do?",
                choices=[
                    "Show my profile (whoami)",
                    "Bootstrap (first-time login)",
                    "Update display name",
                    "Update settings…",
                    "Update main currency",
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


def _require_token() -> bool:
    """Engine-call precondition: config file exists and token is set."""
    cfg = config_module.load()
    if cfg is None or not cfg.token:
        typer.echo(
            "Set engine URL and token first (Config submenu).",
            err=True,
        )
        common.pause()
        return False
    return True


# ----------------------------------------------------------- 1. Show profile


def run_show_profile(ctx: typer.Context) -> None:
    if not _require_token():
        return
    try:
        auth_cmd.me(ctx, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 2. Bootstrap


def _validate_display_name(raw: str) -> bool | str:
    if not raw or not raw.strip():
        return "Display name is required."
    return True


def _validate_optional_timezone(raw: str) -> bool | str:
    # Empty = auto-detect on the flat command; non-empty passes through and
    # the engine validates the IANA string. CLI doesn't gate on TZ format.
    return True


def run_bootstrap(ctx: typer.Context) -> None:
    if not _require_token():
        return
    display_name = common.prompt_validated_text("Display name", _validate_display_name)
    if display_name is None:
        return
    tz_raw = common.prompt_validated_text(
        "Timezone (leave blank to auto-detect)", _validate_optional_timezone
    )
    if tz_raw is None:
        return
    timezone = tz_raw or None
    common.print_recap(
        "auth bootstrap",
        [
            ("--display-name", display_name),
            ("--timezone", timezone if timezone else "<auto>"),
        ],
    )
    confirm = common.prompt_yes_no("Confirm and call engine?", default_no=True)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        return
    try:
        auth_cmd.bootstrap(
            ctx,
            display_name=display_name,
            timezone=timezone,
            json_output=False,
        )
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 3. Update display name


def run_update_display_name(ctx: typer.Context) -> None:
    if not _require_token():
        return
    value = common.prompt_validated_text("New display name", _validate_display_name)
    if value is None:
        return
    common.print_recap("auth profile", [("--display-name", value)])
    confirm = common.prompt_yes_no("Confirm and save?", default_no=True)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        return
    try:
        auth_cmd.profile(ctx, display_name=value, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 4. Update settings (inner picker)


def _validate_int(raw: str) -> bool | str:
    if not raw or not raw.strip():
        return "Value is required."
    try:
        int(raw.strip())
    except ValueError:
        return "Must be an integer."
    return True


def _validate_non_empty_text(raw: str) -> bool | str:
    if not raw or not raw.strip():
        return "Value is required."
    return True


_BOOL_FIELDS = {
    "Sidebar — show bank accounts": (
        "sidebar_show_bank_accounts",
        "--sidebar-show-bank-accounts",
        "--no-sidebar-show-bank-accounts",
    ),
    "Sidebar — show people": (
        "sidebar_show_people",
        "--sidebar-show-people",
        "--no-sidebar-show-people",
    ),
    "Sidebar — show categories": (
        "sidebar_show_categories",
        "--sidebar-show-categories",
        "--no-sidebar-show-categories",
    ),
}


def _empty_settings_kwargs() -> dict[str, object | None]:
    """All-None kwargs matching auth_cmd.settings signature, minus yes/json_output.

    Required because typer.Option(None, …) defaults resolve to OptionInfo
    sentinels when the function is called directly from Python — passing
    explicit None bypasses that.
    """
    return {
        "theme": None,
        "start_of_week": None,
        "main_currency": None,
        "transaction_sort_preference": None,
        "display_timezone": None,
        "sidebar_show_bank_accounts": None,
        "sidebar_show_people": None,
        "sidebar_show_categories": None,
    }


def run_update_settings(ctx: typer.Context) -> None:
    if not _require_token():
        return
    try:
        field = questionary.select(
            "Which setting?",
            choices=[
                "Theme",
                "Start of week",
                "Transaction sort preference",
                "Display timezone",
                "Sidebar — show bank accounts",
                "Sidebar — show people",
                "Sidebar — show categories",
                BACK_LABEL,
            ],
        ).ask()
    except KeyboardInterrupt:
        return
    if field is None or field == BACK_LABEL:
        return

    kwargs = _empty_settings_kwargs()
    recap_flag: tuple[str, str] | None = None

    if field == "Theme":
        raw = common.prompt_validated_text("Theme index", _validate_int)
        if raw is None:
            return
        kwargs["theme"] = int(raw)
        recap_flag = ("--theme", raw)
    elif field == "Start of week":
        raw = common.prompt_validated_text("Start of week (0=Sunday, 1=Monday, …)", _validate_int)
        if raw is None:
            return
        kwargs["start_of_week"] = int(raw)
        recap_flag = ("--start-of-week", raw)
    elif field == "Transaction sort preference":
        raw = common.prompt_validated_text("Transaction sort preference", _validate_int)
        if raw is None:
            return
        kwargs["transaction_sort_preference"] = int(raw)
        recap_flag = ("--transaction-sort-preference", raw)
    elif field == "Display timezone":
        raw = common.prompt_validated_text(
            "Display timezone (IANA, e.g. America/Lima)", _validate_non_empty_text
        )
        if raw is None:
            return
        kwargs["display_timezone"] = raw
        recap_flag = ("--display-timezone", raw)
    else:
        kw, on_flag, off_flag = _BOOL_FIELDS[field]
        answer = common.prompt_yes_no(f"Show «{field.split('— ')[1]}»?", default_no=False)
        if answer is None:
            return
        kwargs[kw] = answer
        recap_flag = (on_flag if answer else off_flag, "")

    common.print_recap("auth settings", [recap_flag])
    confirm = common.prompt_yes_no("Confirm and save?", default_no=True)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        return
    try:
        auth_cmd.settings(ctx, yes=True, json_output=False, **kwargs)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 5. Update main currency


def _validate_currency_code(raw: str) -> bool | str:
    value = raw.strip() if raw else ""
    if not value:
        return "Currency code is required."
    if len(value) != 3 or not value.isalpha() or not value.isupper():
        return "Currency code must be 3 uppercase letters (e.g. USD, PEN)."
    return True


def run_update_main_currency(ctx: typer.Context) -> None:
    if not _require_token():
        return
    value = common.prompt_validated_text(
        "New main currency (e.g. USD, PEN)", _validate_currency_code
    )
    if value is None:
        return
    common.print_recap(
        "auth settings",
        [("--main-currency", value), ("--yes", "")],
    )
    confirmed = prompts.confirm_destructive(
        f"Change main currency to {value}?",
        warning=(
            "The engine will synchronously rewrite home-currency amounts across "
            "every transaction, transfer leg, and pending inbox row. This cannot "
            "be undone except by re-changing the currency back."
        ),
    )
    if not confirmed:
        typer.echo("Aborted.")
        return
    kwargs = _empty_settings_kwargs()
    kwargs["main_currency"] = value
    try:
        auth_cmd.settings(ctx, yes=True, json_output=False, **kwargs)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- dispatch

_HANDLERS = {
    "Show my profile (whoami)": run_show_profile,
    "Bootstrap (first-time login)": run_bootstrap,
    "Update display name": run_update_display_name,
    "Update settings…": run_update_settings,
    "Update main currency": run_update_main_currency,
}
