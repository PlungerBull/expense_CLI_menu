"""Menu flows for the Accounts group (Step 9.5.9).

Wraps `expense accounts list/get/create/update/delete/restore/archive/unarchive`.
No engine round-trip logic here — every flow gathers prompts, prints a recap,
optionally confirms, and delegates to accounts_cmd.
"""

import questionary
import typer

from expense.cache import queries
from expense.commands import accounts_cmd, transactions_cmd
from expense.menu import prompts
from expense.menu.groups import _common as common
from expense.menu.term import clear_screen

BACK_LABEL = "← Back"


def run_accounts_menu(ctx: typer.Context) -> None:
    """Accounts sub-menu loop."""
    while True:
        clear_screen()
        try:
            choice = questionary.select(
                "Accounts — what do you like to do?",
                choices=[
                    "List accounts",
                    "View an account",
                    "Create an account",
                    "Update an account",
                    "Archive an account",
                    "Unarchive an account",
                    "Delete an account",
                    "Restore a deleted account",
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


# ----------------------------------------------------------- 1. List


def run_list(ctx: typer.Context) -> None:
    include_archived = common.prompt_yes_no("Include archived?", default_no=True)
    if include_archived is None:
        return
    include_deleted = common.prompt_yes_no("Include soft-deleted?", default_no=True)
    if include_deleted is None:
        return
    include_people = common.prompt_yes_no("Include people accounts?", default_no=True)
    if include_people is None:
        return

    flags: list[tuple[str, str | None]] = []
    if include_archived:
        flags.append(("--include-archived", ""))
    if include_deleted:
        flags.append(("--include-deleted", ""))
    if include_people:
        flags.append(("--include-people", ""))
    common.print_recap("accounts list", flags)

    try:
        accounts_cmd.list_(
            ctx,
            include_archived=bool(include_archived),
            include_deleted=bool(include_deleted),
            include_people=bool(include_people),
            json_output=False,
        )
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 2. Get


def run_get(ctx: typer.Context) -> None:
    acc_id = prompts.pick_account(include_archived=True)
    if acc_id is prompts.BACK:
        return
    try:
        accounts_cmd.get(ctx, id_=acc_id, json_output=False)
    except typer.Exit:
        pass
    typer.echo("")
    typer.echo("Recent transactions (this account):")
    typer.echo("")
    try:
        transactions_cmd.list_(
            ctx,
            account=acc_id,
            category=None,
            hashtag=None,
            reconciliation=None,
            date_from=None,
            date_to=None,
            cleared=None,
            search=None,
            limit=25,
            offset=0,
            include_deleted=False,
            debit_as_negative=False,
            json_output=False,
        )
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 3. Create


def run_create(ctx: typer.Context) -> None:
    name = common.prompt_validated_text(
        "Account name",
        lambda raw: True if raw.strip() else "Name is required.",
    )
    if name is None:
        return

    typer.echo(
        "Heads up: currency cannot be changed after creation — you'd have to make a new account."
    )
    currency = common.prompt_validated_text(
        "Currency code (ISO 4217, e.g. PEN, USD)", common.validate_currency_code
    )
    if currency is None:
        return

    color = common.prompt_optional_text("Color")
    ok, sort_order = common.prompt_optional_int("Sort order")
    if not ok:
        return

    flags: list[tuple[str, str | None]] = [
        ("--name", f'"{name}"'),
        ("--currency-code", currency),
    ]
    if color is not None:
        flags.append(("--color", f'"{color}"'))
    if sort_order is not None:
        flags.append(("--sort-order", str(sort_order)))
    common.print_recap("accounts create", flags)

    confirm = common.prompt_yes_no("Confirm and submit?", default_no=True)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        common.pause()
        return

    try:
        accounts_cmd.create(
            ctx,
            name=name,
            currency_code=currency,
            color=color,
            sort_order=sort_order,
            json_output=False,
        )
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 4. Update


def run_update(ctx: typer.Context) -> None:
    acc_id = prompts.pick_account(include_archived=True)
    if acc_id is prompts.BACK:
        return

    try:
        item = queries.get_account(acc_id)
    except Exception as exc:  # pragma: no cover — picker came from cache
        typer.echo(f"Could not load account: {exc}", err=True)
        common.pause()
        return

    changes: dict = {}

    yn = common.prompt_yes_no(common.format_field_label("name", item.get("name")))
    if yn is None:
        return
    if yn:
        new_name = common.prompt_validated_text(
            "New name",
            lambda raw: True if raw.strip() else "Name is required.",
        )
        if new_name is None:
            return
        changes["name"] = new_name

    yn = common.prompt_yes_no(common.format_field_label("color", item.get("color")))
    if yn is None:
        return
    if yn:
        new_color = common.prompt_optional_text("New color")
        if new_color is not None:
            changes["color"] = new_color

    yn = common.prompt_yes_no(common.format_field_label("sort order", item.get("sort_order")))
    if yn is None:
        return
    if yn:
        ok, new_sort = common.prompt_optional_int("New sort order")
        if not ok:
            return
        if new_sort is not None:
            changes["sort_order"] = new_sort

    if not changes:
        typer.echo("No changes.")
        common.pause()
        return

    flags: list[tuple[str, str | None]] = []
    if "name" in changes:
        flags.append(("--name", f'"{changes["name"]}"'))
    if "color" in changes:
        flags.append(("--color", f'"{changes["color"]}"'))
    if "sort_order" in changes:
        flags.append(("--sort-order", str(changes["sort_order"])))
    common.print_recap(f"accounts update {acc_id}", flags)

    confirm = common.prompt_yes_no("Confirm and submit?", default_no=True)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        common.pause()
        return

    try:
        accounts_cmd.update(
            ctx,
            id_=acc_id,
            name=changes.get("name"),
            color=changes.get("color"),
            sort_order=changes.get("sort_order"),
            currency_code=None,
            json_output=False,
        )
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 5. Archive


def run_archive(ctx: typer.Context) -> None:
    acc_id = prompts.pick_account()
    if acc_id is prompts.BACK:
        return
    confirmed = prompts.confirm_destructive(
        f"Archive account {acc_id[:8]}…?",
        warning="Hides from pickers; transactions and history remain.",
    )
    if not confirmed:
        typer.echo("Aborted.")
        common.pause()
        return
    try:
        accounts_cmd.archive(ctx, id_=acc_id, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 6. Unarchive


def run_unarchive(ctx: typer.Context) -> None:
    acc_id = prompts.pick_account(only_archived=True)
    if acc_id is prompts.BACK:
        return
    confirm = common.prompt_yes_no("Unarchive?", default_no=False)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        common.pause()
        return
    try:
        accounts_cmd.unarchive(ctx, id_=acc_id, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 7. Delete


def run_delete(ctx: typer.Context) -> None:
    acc_id = prompts.pick_account(include_archived=True)
    if acc_id is prompts.BACK:
        return
    confirmed = prompts.confirm_destructive(
        f"Delete account {acc_id[:8]}…?",
        warning=(
            "Soft-delete: restorable. For cleanup/mistakes only — "
            "use Archive to retire an account with transactions/history."
        ),
    )
    if not confirmed:
        typer.echo("Aborted.")
        common.pause()
        return
    try:
        accounts_cmd.delete(ctx, id_=acc_id, yes=True, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 8. Restore


def run_restore(ctx: typer.Context) -> None:
    acc_id = prompts.pick_account(only_deleted=True)
    if acc_id is prompts.BACK:
        return
    confirm = common.prompt_yes_no("Restore?", default_no=False)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        common.pause()
        return
    try:
        accounts_cmd.restore(ctx, id_=acc_id, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- dispatch

_HANDLERS = {
    "List accounts": run_list,
    "View an account": run_get,
    "Create an account": run_create,
    "Update an account": run_update,
    "Archive an account": run_archive,
    "Unarchive an account": run_unarchive,
    "Delete an account": run_delete,
    "Restore a deleted account": run_restore,
}
