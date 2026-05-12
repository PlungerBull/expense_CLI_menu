"""Menu flows for the Transactions group (Step 9.5.4).

Wraps `expense transactions list/get/update/delete/restore/batch`.
No payload construction or HTTP logic lives here — every flow gathers
prompts, recaps, confirms, and delegates to `transactions_cmd.*`.
"""

import json
import os

import questionary
import typer

from expense.cache import queries
from expense.commands import transactions_cmd
from expense.menu import prompts
from expense.menu.groups import _common as common

BACK_LABEL = "← Back"


def run_transactions_menu(ctx: typer.Context) -> None:
    """Transactions sub-menu loop."""
    while True:
        try:
            choice = questionary.select(
                "Transactions — what do you like to do?",
                choices=[
                    "List transactions",
                    "View a transaction",
                    "Edit a transaction",
                    "Delete a transaction",
                    "Restore a deleted transaction",
                    "Batch import from file",
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


# ----------------------------------------------------------- 1. List


def _prompt_cleared_filter() -> tuple[bool, bool | None]:
    answer = questionary.select(
        "Cleared?",
        choices=[
            questionary.Choice(title="Any", value="any"),
            questionary.Choice(title="Cleared only", value=True),
            questionary.Choice(title="Not cleared only", value=False),
        ],
    ).ask()
    if answer is None:
        return False, None
    return True, None if answer == "any" else bool(answer)


def _prompt_page_size(default: int = 50) -> int | None:
    def _validate(raw: str) -> bool | str:
        if raw == "":
            return True
        try:
            v = int(raw)
        except ValueError:
            return "Must be a positive integer."
        if v <= 0:
            return "Must be a positive integer."
        return True

    answer = questionary.text(f"Page size [{default}]", validate=_validate).ask()
    if answer is None:
        return None
    answer = answer.strip()
    return default if answer == "" else int(answer)


def run_list(ctx: typer.Context) -> None:
    account_id = prompts.pick_account(allow_skip=True)
    if account_id is prompts.BACK:
        return
    if account_id is prompts.SKIP:
        account_id = None

    category_id = prompts.pick_category(allow_skip=True)
    if category_id is prompts.BACK:
        return
    if category_id is prompts.SKIP:
        category_id = None

    hashtag_id = prompts.pick_hashtag(allow_skip=True)
    if hashtag_id is prompts.BACK:
        return
    if hashtag_id is prompts.SKIP:
        hashtag_id = None

    reconciliation_id = None
    if account_id is not None:
        rec = prompts.pick_reconciliation(account_id=account_id)
        # rec returns BACK if no reconciliations exist OR if user aborts.
        # Treat the empty-cache case as "skip reconciliation filter" rather
        # than aborting the whole list flow.
        if rec is not prompts.BACK:
            reconciliation_id = rec

    ok, date_from, date_to = common.prompt_date_range_preset()
    if not ok:
        return

    search = common.prompt_optional_text("Search title/description")

    ok, cleared = _prompt_cleared_filter()
    if not ok:
        return

    include_deleted = common.prompt_yes_no("Include soft-deleted?", default_no=True)
    if include_deleted is None:
        return

    limit = _prompt_page_size()
    if limit is None:
        return

    try:
        transactions_cmd.list_(
            ctx,
            account=account_id,
            category=category_id,
            hashtag=hashtag_id,
            reconciliation=reconciliation_id,
            date_from=date_from,
            date_to=date_to,
            cleared=cleared,
            search=search,
            limit=limit,
            offset=0,
            include_deleted=bool(include_deleted),
            debit_as_negative=False,
            json_output=False,
        )
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 2. Get


def run_get(ctx: typer.Context) -> None:
    item_id = prompts.pick_transaction()
    if item_id is prompts.BACK:
        return
    try:
        transactions_cmd.get(ctx, id_=item_id, debit_as_negative=False, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 3. Update


def _format_field_label(field: str, current: object) -> str:
    if current is None:
        current_s = "unset"
    elif isinstance(current, str) and len(current) > 40:
        current_s = current[:37] + "…"
    else:
        current_s = str(current)
    return f"Update {field}? (current: {current_s})"


def _resolve_hashtag_names(hashtag_ids: list[str]) -> str:
    """Resolve cached hashtag UUIDs to names; falls back to id-prefix on miss."""
    if not hashtag_ids:
        return "none"
    page = queries.list_hashtags()
    name_by_id = {item["id"]: item.get("name", "(unnamed)") for item in page.get("items", [])}
    return ", ".join(name_by_id.get(hid, f"{hid[:8]}…") for hid in hashtag_ids)


def run_update(ctx: typer.Context) -> None:
    item_id = prompts.pick_transaction()
    if item_id is prompts.BACK:
        return

    try:
        item = queries.get_transaction(item_id)
    except Exception as exc:  # pragma: no cover — picker came from cache
        typer.echo(f"Could not load transaction: {exc}", err=True)
        return

    current_hashtag_ids = item.get("hashtag_ids", []) or []
    current_hashtags_label = _resolve_hashtag_names(current_hashtag_ids)

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

    # Hashtags (full replace)
    yn = common.prompt_yes_no(_format_field_label("hashtags", current_hashtags_label))
    if yn is None:
        return
    if yn:
        new_set = prompts.pick_hashtag(multi=True, prompt="Select hashtags (full replace)")
        if new_set is prompts.BACK:
            return
        # multi=True returns a list (possibly empty); join into comma string.
        changes["hashtag_ids"] = ",".join(new_set) if isinstance(new_set, list) else ""

    # Reconciliation (scoped to current or updated account_id)
    account_for_rec = changes.get("account_id") or item.get("account_id")
    yn = common.prompt_yes_no(_format_field_label("reconciliation", item.get("reconciliation_id")))
    if yn is None:
        return
    if yn and account_for_rec is not None:
        new_rec = prompts.pick_reconciliation(account_id=account_for_rec)
        if new_rec is not prompts.BACK:
            changes["reconciliation_id"] = new_rec

    if not changes:
        typer.echo("No changes.")
        return

    flags: list[tuple[str, str | None]] = []
    if "title" in changes:
        flags.append(("--title", f'"{changes["title"]}"'))
    if "amount" in changes:
        flags.append(("--amount", str(changes["amount"])))
    if "date" in changes:
        flags.append(("--date", f'"{changes["date"]}"'))
    if "account_id" in changes:
        flags.append(("--account-id", changes["account_id"]))
    if "category_id" in changes:
        flags.append(("--category-id", changes["category_id"]))
    if "description" in changes:
        flags.append(("--description", f'"{changes["description"]}"'))
    if changes.get("cleared") is True:
        flags.append(("--cleared", ""))
    elif changes.get("cleared") is False:
        flags.append(("--no-cleared", ""))
    if "exchange_rate" in changes:
        flags.append(("--exchange-rate", str(changes["exchange_rate"])))
    if "hashtag_ids" in changes:
        flags.append(("--hashtag-ids", f'"{changes["hashtag_ids"]}"'))
    if "reconciliation_id" in changes:
        flags.append(("--reconciliation-id", changes["reconciliation_id"]))

    common.print_recap(f"transactions update {item_id}", flags)
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
        "hashtag_ids": changes.get("hashtag_ids"),
        "reconciliation_id": changes.get("reconciliation_id"),
    }
    try:
        transactions_cmd.update(ctx, id_=item_id, json_output=False, **update_kwargs)
    except typer.Exit:
        pass

    common.pause()


# ----------------------------------------------------------- 4. Delete


def run_delete(ctx: typer.Context) -> None:
    item_id = prompts.pick_transaction()
    if item_id is prompts.BACK:
        return
    confirmed = prompts.confirm_destructive(
        "Delete this transaction?",
        warning=(
            "Soft-delete. Transfer pairs delete atomically — both legs go. "
            "Restore via the Restore option."
        ),
    )
    if not confirmed:
        typer.echo("Aborted.")
        return
    try:
        transactions_cmd.delete(ctx, id_=item_id, yes=True, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 5. Restore


def run_restore(ctx: typer.Context) -> None:
    item_id = prompts.pick_transaction(only_deleted=True)
    if item_id is prompts.BACK:
        return
    try:
        transactions_cmd.restore(ctx, id_=item_id, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 6. Batch


def run_batch(ctx: typer.Context) -> None:
    path_raw = questionary.text("Path to JSON file").ask()
    if path_raw is None:
        return
    path = os.path.expanduser(path_raw.strip())
    if not path:
        typer.echo("Aborted.")
        return
    if not os.path.isfile(path):
        typer.echo(f"File not found: {path}", err=True)
        return

    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        typer.echo(f"Could not read JSON: {exc}", err=True)
        return

    if not isinstance(data, list) or not data:
        typer.echo("File must contain a non-empty JSON array.", err=True)
        return

    items_with_account = sum(1 for it in data if isinstance(it, dict) and it.get("account_id"))
    items_with_category = sum(1 for it in data if isinstance(it, dict) and it.get("category_id"))
    transfer_offenders = [
        i for i, it in enumerate(data) if isinstance(it, dict) and "transfer" in it
    ]

    typer.echo(f"Found {len(data)} transactions in file.")
    typer.echo(
        f"Validation: {items_with_account} have account_id; "
        f"{items_with_category} have category_id; "
        f"{len(transfer_offenders)} contain a 'transfer' field."
    )

    if transfer_offenders:
        typer.echo(
            f"Error: items[{transfer_offenders[0]}] has a 'transfer' field. "
            "Transfers are not supported in batch creates — "
            "use 'expense log --transfer' instead.",
            err=True,
        )
        return

    confirmed = prompts.confirm_destructive(
        f"Submit {len(data)} transactions atomically?",
        warning='Wrapped in {"transactions": [...]}. Auto-fills missing id fields.',
    )
    if not confirmed:
        typer.echo("Aborted.")
        return

    try:
        transactions_cmd.batch(ctx, file=path, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- dispatch

_HANDLERS = {
    "List transactions": run_list,
    "View a transaction": run_get,
    "Edit a transaction": run_update,
    "Delete a transaction": run_delete,
    "Restore a deleted transaction": run_restore,
    "Batch import from file": run_batch,
}
