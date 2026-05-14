"""Menu flows for the Hashtags group (Step 9.5.11).

Wraps `expense hashtags list/get/create/update/delete/restore/archive/unarchive`.
Mirrors the Categories submenu shape; the key difference is the Delete warning,
which calls out junction-row cascade and that Restore does NOT re-link
transactions to the hashtag.
"""

import questionary
import typer

from expense.cache import queries
from expense.commands import hashtags_cmd
from expense.menu import prompts
from expense.menu.groups import _common as common
from expense.menu.term import clear_screen

BACK_LABEL = "← Back"


def run_hashtags_menu(ctx: typer.Context) -> None:
    """Hashtags sub-menu loop."""
    while True:
        clear_screen()
        try:
            choice = questionary.select(
                "Hashtags — what do you like to do?",
                choices=[
                    "List hashtags",
                    "View a hashtag",
                    "Create a hashtag",
                    "Update a hashtag",
                    "Archive a hashtag",
                    "Unarchive a hashtag",
                    "Delete a hashtag",
                    "Restore a deleted hashtag",
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

    flags: list[tuple[str, str | None]] = []
    if include_archived:
        flags.append(("--include-archived", ""))
    if include_deleted:
        flags.append(("--include-deleted", ""))
    common.print_recap("hashtags list", flags)

    try:
        hashtags_cmd.list_(
            ctx,
            include_archived=bool(include_archived),
            include_deleted=bool(include_deleted),
            limit=None,
            offset=None,
            json_output=False,
        )
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 2. Get


def run_get(ctx: typer.Context) -> None:
    tag_id = prompts.pick_hashtag(include_archived=True)
    if tag_id is prompts.BACK:
        return
    try:
        hashtags_cmd.get(ctx, id_=tag_id, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 3. Create


def run_create(ctx: typer.Context) -> None:
    name = common.prompt_validated_text(
        "Hashtag name",
        lambda raw: True if raw.strip() else "Name is required.",
    )
    if name is None:
        return

    ok, sort_order = common.prompt_optional_int("Sort order")
    if not ok:
        return

    flags: list[tuple[str, str | None]] = [("--name", f'"{name}"')]
    if sort_order is not None:
        flags.append(("--sort-order", str(sort_order)))
    common.print_recap("hashtags create", flags)

    confirm = common.prompt_yes_no("Confirm and submit?", default_no=True)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        common.pause()
        return

    try:
        hashtags_cmd.create(
            ctx,
            name=name,
            sort_order=sort_order,
            json_output=False,
        )
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 4. Update


def run_update(ctx: typer.Context) -> None:
    tag_id = prompts.pick_hashtag(include_archived=True)
    if tag_id is prompts.BACK:
        return

    try:
        item = queries.get_hashtag(tag_id)
    except Exception as exc:  # pragma: no cover — picker came from cache
        typer.echo(f"Could not load hashtag: {exc}", err=True)
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
    if "sort_order" in changes:
        flags.append(("--sort-order", str(changes["sort_order"])))
    common.print_recap(f"hashtags update {tag_id}", flags)

    confirm = common.prompt_yes_no("Confirm and submit?", default_no=True)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        common.pause()
        return

    try:
        hashtags_cmd.update(
            ctx,
            id_=tag_id,
            name=changes.get("name"),
            sort_order=changes.get("sort_order"),
            json_output=False,
        )
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 5. Archive


def run_archive(ctx: typer.Context) -> None:
    tag_id = prompts.pick_hashtag()
    if tag_id is prompts.BACK:
        return
    confirmed = prompts.confirm_destructive(
        f"Archive hashtag {tag_id[:8]}…?",
        warning="Hides from pickers; existing transactions keep their reference.",
    )
    if not confirmed:
        typer.echo("Aborted.")
        common.pause()
        return
    try:
        hashtags_cmd.archive(ctx, id_=tag_id, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 6. Unarchive


def run_unarchive(ctx: typer.Context) -> None:
    tag_id = prompts.pick_hashtag(only_archived=True)
    if tag_id is prompts.BACK:
        return
    confirm = common.prompt_yes_no("Unarchive?", default_no=False)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        common.pause()
        return
    try:
        hashtags_cmd.unarchive(ctx, id_=tag_id, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 7. Delete


def run_delete(ctx: typer.Context) -> None:
    tag_id = prompts.pick_hashtag(include_archived=True)
    if tag_id is prompts.BACK:
        return
    confirmed = prompts.confirm_destructive(
        f"Delete hashtag {tag_id[:8]}…?",
        warning=(
            "Soft-delete: restorable. Junction rows on existing transactions will be "
            "cascade-deleted, and Restore does NOT re-link them."
        ),
    )
    if not confirmed:
        typer.echo("Aborted.")
        common.pause()
        return
    try:
        hashtags_cmd.delete(ctx, id_=tag_id, yes=True, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 8. Restore


def run_restore(ctx: typer.Context) -> None:
    tag_id = prompts.pick_hashtag(only_deleted=True)
    if tag_id is prompts.BACK:
        return
    confirm = common.prompt_yes_no("Restore?", default_no=False)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        common.pause()
        return
    try:
        hashtags_cmd.restore(ctx, id_=tag_id, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- dispatch

_HANDLERS = {
    "List hashtags": run_list,
    "View a hashtag": run_get,
    "Create a hashtag": run_create,
    "Update a hashtag": run_update,
    "Archive a hashtag": run_archive,
    "Unarchive a hashtag": run_unarchive,
    "Delete a hashtag": run_delete,
    "Restore a deleted hashtag": run_restore,
}
