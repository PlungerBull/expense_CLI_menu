"""Menu flows for the Inbox group (Step 9.5.3).

Wraps `expense inbox add/list/get/update/delete/restore/promote`.
No payload construction or HTTP logic lives here — every flow calls
into `inbox_cmd.*` after gathering prompts and printing a recap.
"""

import questionary
import typer

from expense.cache import queries
from expense.commands import inbox_cmd
from expense.menu import prompts
from expense.menu.groups import _common as common

BACK_LABEL = "← Back"


def run_inbox_menu(ctx: typer.Context) -> None:
    """Inbox sub-menu loop."""
    while True:
        try:
            choice = questionary.select(
                "Inbox — what do you like to do?",
                choices=[
                    "Add to inbox",
                    "List inbox items",
                    "View an inbox item",
                    "Edit an inbox item",
                    "Promote to ledger",
                    "Delete an inbox item",
                    "Restore a deleted item",
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


# --------------------------------------------------------------- 1. Add


def _recap_flags_add(args: dict) -> list[tuple[str, str | None]]:
    def _q(value: str | None) -> str | None:
        return f'"{value}"' if value is not None else None

    flags: list[tuple[str, str | None]] = [
        ("--title", _q(args["title"])),
        ("--amount", str(args["amount"])),
        ("--account-id", args.get("account_id")),
        ("--category-id", args.get("category_id")),
        ("--date", _q(args.get("date"))),
        ("--description", _q(args.get("description"))),
    ]
    if args.get("cleared") is True:
        flags.append(("--cleared", ""))
    elif args.get("cleared") is False:
        flags.append(("--no-cleared", ""))
    if args.get("exchange_rate") is not None:
        flags.append(("--exchange-rate", str(args["exchange_rate"])))
    return flags


def run_add(ctx: typer.Context) -> None:
    title = common.prompt_title()
    if title is None:
        return
    amount = prompts.prompt_signed_amount("Amount in cents (negative = expense)")
    if amount is None:
        return

    args: dict = {
        "title": title,
        "amount": amount,
        "account_id": None,
        "category_id": None,
        "date": None,
        "description": None,
        "cleared": None,
        "exchange_rate": None,
    }

    set_optional = common.prompt_yes_no("Set additional fields?", default_no=True)
    if set_optional is None:
        return
    if set_optional:
        account_id = prompts.pick_account(allow_skip=True)
        if account_id is prompts.BACK:
            return
        if account_id is not prompts.SKIP:
            args["account_id"] = account_id

        category_id = prompts.pick_category(allow_skip=True)
        if category_id is prompts.BACK:
            return
        if category_id is not prompts.SKIP:
            args["category_id"] = category_id

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

    common.print_recap("inbox add", _recap_flags_add(args))
    confirm = common.prompt_yes_no("Confirm and submit?", default_no=True)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        return

    try:
        inbox_cmd.add(ctx, json_output=False, **args)
    except typer.Exit:
        pass

    common.pause()


# --------------------------------------------------------------- 2. List


def run_list(ctx: typer.Context) -> None:
    filter_choice = questionary.select(
        "Filter?",
        choices=[
            questionary.Choice(title="All", value="all"),
            questionary.Choice(title="Ready only", value="ready"),
            questionary.Choice(title="Overdue only", value="overdue"),
        ],
    ).ask()
    if filter_choice is None:
        return

    include_deleted = common.prompt_yes_no("Include soft-deleted?", default_no=True)
    if include_deleted is None:
        return

    try:
        inbox_cmd.list_(
            ctx,
            ready=(filter_choice == "ready"),
            overdue=(filter_choice == "overdue"),
            include_deleted=bool(include_deleted),
            limit=None,
            offset=None,
            debit_as_negative=False,
            json_output=False,
        )
    except typer.Exit:
        pass
    common.pause()


# --------------------------------------------------------------- 3. Get


def run_get(ctx: typer.Context) -> None:
    item_id = prompts.pick_inbox()
    if item_id is prompts.BACK:
        return
    try:
        inbox_cmd.get(ctx, id_=item_id, debit_as_negative=False, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# --------------------------------------------------------------- 4. Update


def _format_field_label(field: str, current: object) -> str:
    if current is None:
        current_s = "unset"
    elif isinstance(current, str) and len(current) > 40:
        current_s = current[:37] + "…"
    else:
        current_s = str(current)
    return f"Update {field}? (current: {current_s})"


def run_update(ctx: typer.Context) -> None:
    item_id = prompts.pick_inbox()
    if item_id is prompts.BACK:
        return

    try:
        item = queries.get_inbox(item_id)
    except Exception as exc:  # pragma: no cover — picker came from cache
        typer.echo(f"Could not load inbox item: {exc}", err=True)
        return

    changes: dict = {}

    # Title
    yn = common.prompt_yes_no(_format_field_label("title", item.get("title")))
    if yn is None:
        return
    if yn:
        new_title = common.prompt_title()
        if new_title is None:
            return
        changes["title"] = new_title

    # Amount
    yn = common.prompt_yes_no(_format_field_label("amount", item.get("amount_cents")))
    if yn is None:
        return
    if yn:
        new_amount = prompts.prompt_signed_amount("New amount in cents")
        if new_amount is None:
            return
        changes["amount"] = new_amount

    # Account
    yn = common.prompt_yes_no(_format_field_label("account", item.get("account_id")))
    if yn is None:
        return
    if yn:
        new_account = prompts.pick_account(prompt="New account")
        if new_account is prompts.BACK:
            return
        changes["account_id"] = new_account

    # Category
    yn = common.prompt_yes_no(_format_field_label("category", item.get("category_id")))
    if yn is None:
        return
    if yn:
        new_category = prompts.pick_category(prompt="New category")
        if new_category is prompts.BACK:
            return
        changes["category_id"] = new_category

    # Date
    yn = common.prompt_yes_no(_format_field_label("date", item.get("date")))
    if yn is None:
        return
    if yn:
        ok, new_date = common.prompt_date_optional()
        if not ok:
            return
        if new_date is not None:
            changes["date"] = new_date

    # Description
    yn = common.prompt_yes_no(_format_field_label("description", item.get("description")))
    if yn is None:
        return
    if yn:
        new_desc = common.prompt_optional_text("New description")
        if new_desc is not None:
            changes["description"] = new_desc

    # Cleared
    yn = common.prompt_yes_no(_format_field_label("cleared", item.get("cleared")))
    if yn is None:
        return
    if yn:
        ok, new_cleared = common.prompt_cleared_tri()
        if not ok:
            return
        if new_cleared is not None:
            changes["cleared"] = new_cleared

    # Exchange rate
    yn = common.prompt_yes_no(_format_field_label("exchange rate", item.get("exchange_rate")))
    if yn is None:
        return
    if yn:
        ok, new_rate = common.prompt_exchange_rate()
        if not ok:
            return
        if new_rate is not None:
            changes["exchange_rate"] = new_rate

    if not changes:
        typer.echo("No changes.")
        return

    flags: list[tuple[str, str | None]] = []
    if "title" in changes:
        flags.append(("--title", f'"{changes["title"]}"'))
    if "amount" in changes:
        flags.append(("--amount", str(changes["amount"])))
    if "account_id" in changes:
        flags.append(("--account-id", changes["account_id"]))
    if "category_id" in changes:
        flags.append(("--category-id", changes["category_id"]))
    if "date" in changes:
        flags.append(("--date", f'"{changes["date"]}"'))
    if "description" in changes:
        flags.append(("--description", f'"{changes["description"]}"'))
    if changes.get("cleared") is True:
        flags.append(("--cleared", ""))
    elif changes.get("cleared") is False:
        flags.append(("--no-cleared", ""))
    if "exchange_rate" in changes:
        flags.append(("--exchange-rate", str(changes["exchange_rate"])))

    common.print_recap(f"inbox update {item_id}", flags)
    confirm = common.prompt_yes_no("Confirm and submit?", default_no=True)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        return

    update_kwargs = {
        "title": changes.get("title"),
        "amount": changes.get("amount"),
        "date": changes.get("date"),
        "account_id": changes.get("account_id"),
        "category_id": changes.get("category_id"),
        "description": changes.get("description"),
        "cleared": changes.get("cleared"),
        "exchange_rate": changes.get("exchange_rate"),
    }
    try:
        inbox_cmd.update(ctx, id_=item_id, json_output=False, **update_kwargs)
    except typer.Exit:
        pass

    common.pause()


# --------------------------------------------------------------- 5. Promote


def run_promote(ctx: typer.Context) -> None:
    item_id = prompts.pick_inbox()
    if item_id is prompts.BACK:
        return
    confirmed = prompts.confirm_destructive(
        "Promote this inbox item to the ledger?",
        warning=(
            "This creates a real transaction. The inbox item is soft-deleted on success. "
            "Engine 422 will list any missing required fields."
        ),
    )
    if not confirmed:
        typer.echo("Aborted.")
        return
    try:
        inbox_cmd.promote(ctx, id_=item_id, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# --------------------------------------------------------------- 6. Delete


def run_delete(ctx: typer.Context) -> None:
    item_id = prompts.pick_inbox()
    if item_id is prompts.BACK:
        return
    confirmed = prompts.confirm_destructive(
        "Delete this inbox item?",
        warning="This soft-deletes the draft. Restore via the Restore option.",
    )
    if not confirmed:
        typer.echo("Aborted.")
        return
    try:
        inbox_cmd.delete(ctx, id_=item_id, yes=True, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# --------------------------------------------------------------- 7. Restore


def run_restore(ctx: typer.Context) -> None:
    item_id = prompts.pick_inbox(only_deleted=True)
    if item_id is prompts.BACK:
        return
    try:
        inbox_cmd.restore(ctx, id_=item_id, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# --------------------------------------------------------------- dispatch

_HANDLERS = {
    "Add to inbox": run_add,
    "List inbox items": run_list,
    "View an inbox item": run_get,
    "Edit an inbox item": run_update,
    "Promote to ledger": run_promote,
    "Delete an inbox item": run_delete,
    "Restore a deleted item": run_restore,
}
