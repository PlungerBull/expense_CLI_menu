"""Menu flows for the Reconciliations group (Step 9.5.12).

Wraps `expense reconcile list/get/create/update/delete/restore/complete/
revert/move/reorder`. Mirrors the hashtags submenu shape. The `$EDITOR`
reorder flow reuses `expense._editor.edit_text` via the underlying
`reconcile_cmd.reorder` command — no editor logic lives here.
"""

import questionary
import typer

from expense import cache as cache_pkg
from expense.commands import reconcile_cmd
from expense.dates import to_canonical_aware
from expense.menu import prompts
from expense.menu.groups import _common as common
from expense.menu.term import clear_screen

BACK_LABEL = "← Back"


def run_reconciliations_menu(ctx: typer.Context) -> None:
    """Reconciliations sub-menu loop."""
    while True:
        clear_screen()
        try:
            choice = questionary.select(
                "Reconciliations — what do you like to do?",
                choices=[
                    "List reconciliations",
                    "View a reconciliation",
                    "Create a reconciliation",
                    "Update a reconciliation",
                    "Complete a reconciliation",
                    "Revert a completed reconciliation",
                    "Move a reconciliation in the chain",
                    "Reorder reconciliations ($EDITOR)",
                    "Delete a reconciliation",
                    "Restore a deleted reconciliation",
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


# --------------------------------------------------------------- shared


def _prompt_optional_date(label: str) -> tuple[bool, str | None]:
    raw = questionary.text(f"{label} (skip)").ask()
    if raw is None:
        return False, None
    raw = raw.strip()
    if raw == "":
        return True, None
    try:
        return True, to_canonical_aware(raw)
    except typer.BadParameter as exc:
        typer.echo(f"  {exc.message}", err=True)
        common.pause()
        return False, None


def _validate_signed_cents(raw: str, *, allow_empty: bool) -> bool | str:
    value = raw.strip()
    if value == "":
        return True if allow_empty else "Required (signed cents, e.g. 150000 or -2500)."
    try:
        int(value)
    except ValueError:
        return "Must be an integer in signed cents (e.g. 150000 or -2500)."
    return True


def _prompt_optional_balance(label: str) -> tuple[bool, int | None]:
    raw = questionary.text(
        f"{label} (signed cents, skip)",
        validate=lambda v: _validate_signed_cents(v, allow_empty=True),
    ).ask()
    if raw is None:
        return False, None
    raw = raw.strip()
    return True, (int(raw) if raw else None)


def _prompt_required_balance(label: str) -> int | None:
    raw = questionary.text(
        f"{label} (signed cents)",
        validate=lambda v: _validate_signed_cents(v, allow_empty=False),
    ).ask()
    if raw is None:
        return None
    return int(raw.strip())


def _prompt_source(*, default: str | None = None) -> str | None:
    """Single-select between 'manual' and 'chained'. None on Ctrl-C."""
    choices = [
        questionary.Choice(title="manual — set beginning balance explicitly", value="manual"),
        questionary.Choice(title="chained — derive from previous reconciliation", value="chained"),
    ]
    return questionary.select("Source", choices=choices, default=default).ask()


# --------------------------------------------------------------- 1. List


def run_list(ctx: typer.Context) -> None:
    account_picked = prompts.pick_account(include_archived=True, allow_skip=True)
    if account_picked is prompts.BACK:
        return
    account_id: str | None = None if account_picked is prompts.SKIP else account_picked  # type: ignore[assignment]

    include_deleted = common.prompt_yes_no("Include soft-deleted?", default_no=True)
    if include_deleted is None:
        return

    flags: list[tuple[str, str | None]] = []
    if account_id:
        flags.append(("--account-id", account_id))
    if include_deleted:
        flags.append(("--include-deleted", ""))
    common.print_recap("reconcile list", flags)

    try:
        reconcile_cmd.list_(
            ctx,
            account=account_id,
            include_deleted=bool(include_deleted),
            limit=None,
            offset=None,
            json_output=False,
        )
    except typer.Exit:
        pass
    common.pause()


# --------------------------------------------------------------- 2. View (get)


def run_get(ctx: typer.Context) -> None:
    account_id = prompts.pick_account(include_archived=True)
    if account_id is prompts.BACK:
        return
    recon_id = prompts.pick_reconciliation(account_id=account_id)  # type: ignore[arg-type]
    if recon_id is prompts.BACK:
        return
    try:
        reconcile_cmd.get(ctx, id_=recon_id, limit=None, offset=None, json_output=False)  # type: ignore[arg-type]
    except typer.Exit:
        pass
    common.pause()


# --------------------------------------------------------------- 3. Create


def run_create(ctx: typer.Context) -> None:
    account_id = prompts.pick_account()
    if account_id is prompts.BACK:
        return

    name = common.prompt_validated_text(
        "Name (e.g. 'April 2026')",
        lambda raw: True if raw.strip() else "Name is required.",
    )
    if name is None:
        return

    ok, date_start = _prompt_optional_date("Date start")
    if not ok:
        return
    ok, date_end = _prompt_optional_date("Date end")
    if not ok:
        return

    source = _prompt_source()
    if source is None:
        return

    beginning_balance: int | None = None
    if source == "manual":
        beginning_balance = _prompt_required_balance("Beginning balance")
        if beginning_balance is None:
            return

    ok, ending_balance = _prompt_optional_balance("Ending balance")
    if not ok:
        return

    ok, sort_order = common.prompt_optional_int("Sort order")
    if not ok:
        return

    flags: list[tuple[str, str | None]] = [
        ("--account-id", account_id),  # type: ignore[list-item]
        ("--name", f'"{name}"'),
    ]
    if date_start:
        flags.append(("--date-start", date_start))
    if date_end:
        flags.append(("--date-end", date_end))
    flags.append(("--source", source))
    if beginning_balance is not None:
        flags.append(("--beginning-balance", str(beginning_balance)))
    if ending_balance is not None:
        flags.append(("--ending-balance", str(ending_balance)))
    if sort_order is not None:
        flags.append(("--sort-order", str(sort_order)))
    common.print_recap("reconcile create", flags)

    confirm = common.prompt_yes_no("Confirm and submit?", default_no=True)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        common.pause()
        return

    try:
        reconcile_cmd.create(
            ctx,
            account_id=account_id,  # type: ignore[arg-type]
            name=name,
            date_start=date_start,
            date_end=date_end,
            beginning_balance=beginning_balance,
            ending_balance=ending_balance,
            source=source,
            sort_order=sort_order,
            json_output=False,
        )
    except typer.Exit:
        pass
    common.pause()


# --------------------------------------------------------------- 4. Update


def run_update(ctx: typer.Context) -> None:
    account_id = prompts.pick_account(include_archived=True)
    if account_id is prompts.BACK:
        return
    recon_id = prompts.pick_reconciliation(account_id=account_id)  # type: ignore[arg-type]
    if recon_id is prompts.BACK:
        return

    try:
        item = cache_pkg.get_reconciliation(recon_id)  # type: ignore[arg-type]
    except Exception as exc:  # pragma: no cover — picker came from cache
        typer.echo(f"Could not load reconciliation: {exc}", err=True)
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

    yn = common.prompt_yes_no(common.format_field_label("date start", item.get("date_start")))
    if yn is None:
        return
    if yn:
        ok, new_ds = _prompt_optional_date("New date start")
        if not ok:
            return
        if new_ds is not None:
            changes["date_start"] = new_ds

    yn = common.prompt_yes_no(common.format_field_label("date end", item.get("date_end")))
    if yn is None:
        return
    if yn:
        ok, new_de = _prompt_optional_date("New date end")
        if not ok:
            return
        if new_de is not None:
            changes["date_end"] = new_de

    current_source = item.get("beginning_balance_source")
    yn = common.prompt_yes_no(common.format_field_label("source", current_source))
    if yn is None:
        return
    new_source = changes.get("source") if "source" in changes else current_source
    if yn:
        default_source = current_source if current_source in {"manual", "chained"} else None
        picked = _prompt_source(default=default_source)
        if picked is None:
            return
        changes["source"] = picked
        new_source = picked

    # If source is (or will be) "chained", the engine rejects an explicit beginning
    # balance. Skip the prompt to keep the mutex clean.
    if new_source != "chained":
        yn = common.prompt_yes_no(
            common.format_field_label(
                "beginning balance (cents)", item.get("beginning_balance_cents")
            )
        )
        if yn is None:
            return
        if yn:
            new_bb = _prompt_required_balance("New beginning balance")
            if new_bb is None:
                return
            changes["beginning_balance"] = new_bb

    yn = common.prompt_yes_no(
        common.format_field_label("ending balance (cents)", item.get("ending_balance_cents"))
    )
    if yn is None:
        return
    if yn:
        new_eb = _prompt_required_balance("New ending balance")
        if new_eb is None:
            return
        changes["ending_balance"] = new_eb

    if not changes:
        typer.echo("No changes.")
        common.pause()
        return

    flags: list[tuple[str, str | None]] = []
    if "name" in changes:
        flags.append(("--name", f'"{changes["name"]}"'))
    if "date_start" in changes:
        flags.append(("--date-start", changes["date_start"]))
    if "date_end" in changes:
        flags.append(("--date-end", changes["date_end"]))
    if "source" in changes:
        flags.append(("--source", changes["source"]))
    if "beginning_balance" in changes:
        flags.append(("--beginning-balance", str(changes["beginning_balance"])))
    if "ending_balance" in changes:
        flags.append(("--ending-balance", str(changes["ending_balance"])))
    common.print_recap(f"reconcile update {recon_id}", flags)

    confirm = common.prompt_yes_no("Confirm and submit?", default_no=True)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        common.pause()
        return

    try:
        reconcile_cmd.update(
            ctx,
            id_=recon_id,  # type: ignore[arg-type]
            name=changes.get("name"),
            date_start=changes.get("date_start"),
            date_end=changes.get("date_end"),
            beginning_balance=changes.get("beginning_balance"),
            ending_balance=changes.get("ending_balance"),
            source=changes.get("source"),
            json_output=False,
        )
    except typer.Exit:
        pass
    common.pause()


# --------------------------------------------------------------- 5. Complete


def run_complete(ctx: typer.Context) -> None:
    account_id = prompts.pick_account(include_archived=True)
    if account_id is prompts.BACK:
        return
    recon_id = prompts.pick_reconciliation(account_id=account_id)  # type: ignore[arg-type]
    if recon_id is prompts.BACK:
        return
    confirmed = prompts.confirm_destructive(
        f"Complete reconciliation {recon_id[:8]}…?",  # type: ignore[index]
        warning=(
            "Locks amount, account, title, and date on every assigned transaction, "
            "plus this reconciliation's balance/date fields. Reversible only via Revert."
        ),
    )
    if not confirmed:
        typer.echo("Aborted.")
        common.pause()
        return
    try:
        reconcile_cmd.complete(ctx, id_=recon_id, json_output=False)  # type: ignore[arg-type]
    except typer.Exit:
        pass
    common.pause()


# --------------------------------------------------------------- 6. Revert


def run_revert(ctx: typer.Context) -> None:
    account_id = prompts.pick_account(include_archived=True)
    if account_id is prompts.BACK:
        return
    recon_id = prompts.pick_reconciliation(account_id=account_id)  # type: ignore[arg-type]
    if recon_id is prompts.BACK:
        return
    confirmed = prompts.confirm_destructive(
        f"Revert completed reconciliation {recon_id[:8]}…?",  # type: ignore[index]
        warning=(
            "AUDIT EVENT: unlocks every assigned transaction's amount/account/title/date "
            "and this reconciliation's balance/date fields. Recorded in the activity log."
        ),
    )
    if not confirmed:
        typer.echo("Aborted.")
        common.pause()
        return
    try:
        reconcile_cmd.revert(ctx, id_=recon_id, yes=True, json_output=False)  # type: ignore[arg-type]
    except typer.Exit:
        pass
    common.pause()


# --------------------------------------------------------------- 7. Move


def run_move(ctx: typer.Context) -> None:
    account_id = prompts.pick_account(include_archived=True)
    if account_id is prompts.BACK:
        return
    recon_id = prompts.pick_reconciliation(  # type: ignore[arg-type]
        account_id=account_id, prompt="Reconciliation to move"
    )
    if recon_id is prompts.BACK:
        return

    mode = questionary.select(
        "How would you like to move it?",
        choices=[
            questionary.Choice(title="To a position number", value="to"),
            questionary.Choice(title="Before another reconciliation", value="before"),
            questionary.Choice(title="After another reconciliation", value="after"),
        ],
    ).ask()
    if mode is None:
        return

    to: int | None = None
    before: str | None = None
    after: str | None = None

    if mode == "to":

        def _validate_pos(raw: str) -> bool | str:
            value = raw.strip()
            if value == "":
                return "Position is required."
            try:
                n = int(value)
            except ValueError:
                return "Must be an integer."
            if n < 1:
                return "Must be >= 1."
            return True

        raw = questionary.text("Position (1-based)", validate=_validate_pos).ask()
        if raw is None:
            return
        to = int(raw.strip())
    else:
        peer = prompts.pick_reconciliation(  # type: ignore[arg-type]
            account_id=account_id, prompt=f"Reconciliation to land {mode}"
        )
        if peer is prompts.BACK:
            return
        if peer == recon_id:
            typer.echo(f"--{mode} cannot reference the source itself.", err=True)
            common.pause()
            return
        if mode == "before":
            before = peer  # type: ignore[assignment]
        else:
            after = peer  # type: ignore[assignment]

    flags: list[tuple[str, str | None]] = []
    if to is not None:
        flags.append(("--to", str(to)))
    if before is not None:
        flags.append(("--before", before))
    if after is not None:
        flags.append(("--after", after))
    common.print_recap(f"reconcile move {recon_id}", flags)

    confirm = common.prompt_yes_no("Confirm and submit?", default_no=True)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        common.pause()
        return

    try:
        reconcile_cmd.move(
            ctx,
            id_=recon_id,  # type: ignore[arg-type]
            to=to,
            before=before,
            after=after,
            json_output=False,
        )
    except typer.Exit:
        pass
    common.pause()


# --------------------------------------------------------------- 8. Reorder ($EDITOR)


def run_reorder(ctx: typer.Context) -> None:
    account_id = prompts.pick_account(include_archived=True)
    if account_id is prompts.BACK:
        return

    def _validate_year(raw: str) -> bool | str:
        value = raw.strip()
        if value == "":
            return True
        try:
            int(value)
        except ValueError:
            return "Must be a 4-digit year (e.g. 2026) or empty to skip."
        return True

    raw = questionary.text("Year filter (blank = all years)", validate=_validate_year).ask()
    if raw is None:
        return
    year = int(raw.strip()) if raw.strip() else None

    flags: list[tuple[str, str | None]] = [("--account-id", account_id)]  # type: ignore[list-item]
    if year is not None:
        flags.append(("--year", str(year)))
    common.print_recap("reconcile reorder", flags)

    typer.echo("Opening $EDITOR on the current chain — save and quit to apply.")
    try:
        reconcile_cmd.reorder(
            ctx,
            account_id=account_id,  # type: ignore[arg-type]
            year=year,
            editor=None,
            json_output=False,
        )
    except typer.Exit:
        pass
    common.pause()


# --------------------------------------------------------------- 9. Delete


def run_delete(ctx: typer.Context) -> None:
    account_id = prompts.pick_account(include_archived=True)
    if account_id is prompts.BACK:
        return
    recon_id = prompts.pick_reconciliation(account_id=account_id)  # type: ignore[arg-type]
    if recon_id is prompts.BACK:
        return
    confirmed = prompts.confirm_destructive(
        f"Delete reconciliation {recon_id[:8]}…?",  # type: ignore[index]
        warning=(
            "Soft-delete; cascade-unassigns every attached transaction. Draft only — "
            "completed reconciliations must be Reverted first. Restore does NOT re-link "
            "the transactions."
        ),
    )
    if not confirmed:
        typer.echo("Aborted.")
        common.pause()
        return
    try:
        reconcile_cmd.delete(ctx, id_=recon_id, yes=True, json_output=False)  # type: ignore[arg-type]
    except typer.Exit:
        pass
    common.pause()


# --------------------------------------------------------------- 10. Restore


def run_restore(ctx: typer.Context) -> None:
    account_id = prompts.pick_account(include_archived=True)
    if account_id is prompts.BACK:
        return
    page = cache_pkg.list_reconciliations(account_id=account_id, include_deleted=True)  # type: ignore[arg-type]
    items = [it for it in page.get("items", []) if it.get("deleted_at") is not None]
    if not items:
        typer.echo("No deleted reconciliations found for this account.", err=True)
        common.pause()
        return
    choices = [
        questionary.Choice(
            title=f"{item.get('name') or '(unnamed)'}  · {item['id'][:8]}…",
            value=item["id"],
        )
        for item in items
    ]
    recon_id = questionary.select("Deleted reconciliation", choices=choices).ask()
    if recon_id is None:
        return
    confirm = common.prompt_yes_no("Restore?", default_no=False)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        common.pause()
        return
    try:
        reconcile_cmd.restore(ctx, id_=recon_id, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# --------------------------------------------------------------- dispatch


_HANDLERS = {
    "List reconciliations": run_list,
    "View a reconciliation": run_get,
    "Create a reconciliation": run_create,
    "Update a reconciliation": run_update,
    "Complete a reconciliation": run_complete,
    "Revert a completed reconciliation": run_revert,
    "Move a reconciliation in the chain": run_move,
    "Reorder reconciliations ($EDITOR)": run_reorder,
    "Delete a reconciliation": run_delete,
    "Restore a deleted reconciliation": run_restore,
}
