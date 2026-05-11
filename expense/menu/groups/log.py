"""Menu flow for the root-level `Log a transaction` shortcut (Step 9.5.2).

Wraps `expense log`. Reuses the existing flat command's implementation —
no payload construction or HTTP call lives here. The flow's only job is
to gather inputs interactively, recap them for audit, confirm, and
delegate to `log_cmd.log()`.
"""

import questionary
import typer

from expense.commands import log_cmd
from expense.dates import to_canonical_aware
from expense.menu import prompts


def _prompt_title() -> str | None:
    answer = questionary.text(
        "Title",
        validate=lambda raw: True if raw.strip() else "Title is required.",
    ).ask()
    if answer is None:
        return None
    return answer.strip()


def _prompt_optional_text(label: str) -> str | None:
    answer = questionary.text(f"{label} (skip)").ask()
    if answer is None:
        return None
    answer = answer.strip()
    return answer or None


def _prompt_date_optional() -> tuple[bool, str | None]:
    """Returns (ok, value). ok=False signals user aborted (Ctrl-C)."""
    raw = questionary.text("Date  [now]").ask()
    if raw is None:
        return False, None
    raw = raw.strip()
    if raw == "":
        return True, None
    try:
        return True, to_canonical_aware(raw)
    except typer.BadParameter as exc:
        typer.echo(f"  {exc.message}", err=True)
        return False, None


def _prompt_cleared_tri() -> tuple[bool, bool | None]:
    answer = questionary.select(
        "Cleared?",
        choices=[
            questionary.Choice(title="Default (unset)", value="unset"),
            questionary.Choice(title="Yes (cleared)", value=True),
            questionary.Choice(title="No (not cleared)", value=False),
        ],
    ).ask()
    if answer is None:
        return False, None
    return True, None if answer == "unset" else bool(answer)


def _prompt_exchange_rate() -> tuple[bool, float | None]:
    def _validate(raw: str) -> bool | str:
        if raw == "":
            return True
        try:
            value = float(raw)
        except ValueError:
            return "Must be a number (e.g. 3.75)."
        if value <= 0:
            return "Exchange rate must be positive."
        return True

    raw = questionary.text("Override exchange rate? (skip)", validate=_validate).ask()
    if raw is None:
        return False, None
    raw = raw.strip()
    if raw == "":
        return True, None
    return True, float(raw)


def _prompt_yes_no(message: str, *, default_no: bool = True) -> bool | None:
    answer = questionary.select(
        message,
        choices=[
            questionary.Choice(title="No", value=False),
            questionary.Choice(title="Yes", value=True),
        ],
        default="No" if default_no else "Yes",
    ).ask()
    return answer


def _print_recap(args: dict) -> None:
    """Print the equivalent `expense log` command line for audit."""
    lines = ["About to call:", "  expense log \\"]
    pieces: list[str] = []
    pieces.append(f'    --title "{args["title"]}"')
    pieces.append(f"    --amount {args['amount']}")
    pieces.append(f"    --account-id {args['account_id']}")
    pieces.append(f"    --category-id {args['category_id']}")
    if args.get("date") is not None:
        pieces.append(f'    --date "{args["date"]}"')
    if args.get("description") is not None:
        pieces.append(f'    --description "{args["description"]}"')
    if args.get("cleared") is True:
        pieces.append("    --cleared")
    elif args.get("cleared") is False:
        pieces.append("    --no-cleared")
    if args.get("exchange_rate") is not None:
        pieces.append(f"    --exchange-rate {args['exchange_rate']}")
    if args.get("transfer"):
        pieces.append("    --transfer")
        pieces.append(f"    --to-account-id {args['to_account_id']}")
        pieces.append(f"    --to-amount {args['to_amount']}")
    for i, piece in enumerate(pieces):
        if i == len(pieces) - 1:
            lines.append(piece)
        else:
            lines.append(piece + " \\")
    typer.echo("")
    for line in lines:
        typer.echo(line)
    typer.echo("")


def _pause() -> None:
    questionary.text("Press Enter to return to main menu").ask()


def run_log_flow(ctx: typer.Context) -> None:
    """Menu entry point — wraps `expense log` with interactive prompts."""
    title = _prompt_title()
    if title is None:
        return

    amount = prompts.prompt_signed_amount("Amount in cents (negative = expense)")
    if amount is None:
        return

    account_id = prompts.pick_account()
    if account_id is prompts.BACK:
        return

    category_id = prompts.pick_category()
    if category_id is prompts.BACK:
        return

    args: dict = {
        "title": title,
        "amount": amount,
        "account_id": account_id,
        "category_id": category_id,
        "date": None,
        "description": None,
        "cleared": None,
        "exchange_rate": None,
        "transfer": False,
        "to_account_id": None,
        "to_amount": None,
    }

    set_optional = _prompt_yes_no("Set additional optional fields?", default_no=True)
    if set_optional is None:
        return
    if set_optional:
        ok, date_value = _prompt_date_optional()
        if not ok:
            return
        args["date"] = date_value

        args["description"] = _prompt_optional_text("Description")

        ok, cleared = _prompt_cleared_tri()
        if not ok:
            return
        args["cleared"] = cleared

        ok, exchange_rate = _prompt_exchange_rate()
        if not ok:
            return
        args["exchange_rate"] = exchange_rate

        make_transfer = _prompt_yes_no("Create as a transfer pair?", default_no=True)
        if make_transfer is None:
            return
        if make_transfer:
            to_account_id = prompts.pick_account(prompt="To account")
            if to_account_id is prompts.BACK:
                return
            to_amount = prompts.prompt_signed_amount("To amount in cents (must be opposite sign)")
            if to_amount is None:
                return
            args["transfer"] = True
            args["to_account_id"] = to_account_id
            args["to_amount"] = to_amount

    _print_recap(args)
    confirm = _prompt_yes_no("Confirm and submit?", default_no=True)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        return

    try:
        log_cmd.log(ctx, json_output=False, **args)
    except typer.Exit:
        pass

    _pause()
