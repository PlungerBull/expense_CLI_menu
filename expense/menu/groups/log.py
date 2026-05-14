"""Menu flow for the root-level `Log a transaction` shortcut (Step 9.5.2).

Wraps `expense log`. Reuses the existing flat command's implementation —
no payload construction or HTTP call lives here. The flow's only job is
to gather inputs interactively, recap them for audit, confirm, and
delegate to `log_cmd.log()`.
"""

import typer

from expense.cache import queries
from expense.commands import log_cmd
from expense.menu import prompts
from expense.menu.groups import _common as common


def _cache_has_active_hashtags() -> bool:
    """Skip the hashtag picker entirely when the cache has nothing to pick.

    Avoids the noisy '(no hashtags found)' empty-hint flash for users who
    haven't started tagging yet.
    """
    try:
        page = queries.list_hashtags(include_archived=False, include_deleted=False)
    except Exception:
        return False
    items = page.get("items") if isinstance(page, dict) else None
    return bool(items)


def _recap_flags(args: dict) -> list[tuple[str, str | None]]:
    def _q(value: str | None) -> str | None:
        return f'"{value}"' if value is not None else None

    flags: list[tuple[str, str | None]] = [
        ("--title", _q(args["title"])),
        ("--amount", str(args["amount"])),
        ("--account-id", args["account_id"]),
        ("--category-id", args["category_id"]),
        ("--date", _q(args.get("date"))),
        ("--description", _q(args.get("description"))),
    ]
    if args.get("cleared") is True:
        flags.append(("--cleared", ""))
    elif args.get("cleared") is False:
        flags.append(("--no-cleared", ""))
    if args.get("exchange_rate") is not None:
        flags.append(("--exchange-rate", str(args["exchange_rate"])))
    if args.get("hashtag_ids"):
        flags.append(("--hashtag-ids", ",".join(args["hashtag_ids"])))
    if args.get("transfer"):
        flags.append(("--transfer", ""))
        flags.append(("--to-account-id", args["to_account_id"]))
        flags.append(("--to-amount", str(args["to_amount"])))
    return flags


def _print_recap(args: dict) -> None:
    """Kept as a backwards-compatible shim — tests/menu logs hit this name."""
    common.print_recap("log", _recap_flags(args))


def run_log_flow(ctx: typer.Context) -> None:
    """Menu entry point — wraps `expense log` with interactive prompts."""
    title = common.prompt_title()
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

    # Multi-select hashtag picker; only shown if there are hashtags to pick.
    # Empty checkbox submit (Enter with nothing selected) = no hashtags.
    # Esc/Ctrl-C inside the picker returns BACK — treat as 'skip', not abort,
    # so the user can move past it without losing the title/amount they typed.
    hashtag_ids: list[str] = []
    if _cache_has_active_hashtags():
        hashtag_pick = prompts.pick_hashtag(multi=True)
        if isinstance(hashtag_pick, list):
            hashtag_ids = hashtag_pick

    args: dict = {
        "title": title,
        "amount": amount,
        "account_id": account_id,
        "category_id": category_id,
        "hashtag_ids": hashtag_ids,
        "date": None,
        "description": None,
        "cleared": None,
        "exchange_rate": None,
        "transfer": False,
        "to_account_id": None,
        "to_amount": None,
    }

    set_optional = common.prompt_yes_no("Set additional optional fields?", default_no=True)
    if set_optional is None:
        return
    if set_optional:
        ok, date_value = common.prompt_date_optional()
        if not ok:
            return
        args["date"] = date_value

        args["description"] = common.prompt_optional_text("Description")

        ok, cleared = common.prompt_cleared_tri()
        if not ok:
            return
        args["cleared"] = cleared

        ok, exchange_rate = common.prompt_exchange_rate()
        if not ok:
            return
        args["exchange_rate"] = exchange_rate

        make_transfer = common.prompt_yes_no("Create as a transfer pair?", default_no=True)
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
    confirm = common.prompt_yes_no("Confirm and submit?", default_no=True)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        common.pause()
        return

    # Flat command takes a comma-separated string; menu carries a list.
    call_args = dict(args)
    ids = call_args.pop("hashtag_ids", None) or []
    call_args["hashtag_ids"] = ",".join(ids) if ids else None
    try:
        log_cmd.log(ctx, json_output=False, **call_args)
    except typer.Exit:
        pass

    common.pause()
