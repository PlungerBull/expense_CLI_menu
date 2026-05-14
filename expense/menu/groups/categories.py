"""Menu flows for the Categories group (Step 9.5.10).

Wraps `expense categories list/get/create/update/delete/restore/archive/unarchive`.
Mirrors the Accounts submenu shape; the key difference is the system-category
guard — Archive and Delete pre-filter `@Debt`/`@Transfer` from their pickers so
users never select them as destructive candidates. The engine's 403 hint
still surfaces verbatim via `handle_errors` if it ever fires.
"""

import questionary
import typer

from expense.cache import queries
from expense.commands import categories_cmd
from expense.menu import prompts
from expense.menu.groups import _common as common
from expense.menu.term import clear_screen

BACK_LABEL = "← Back"


def run_categories_menu(ctx: typer.Context) -> None:
    """Categories sub-menu loop."""
    while True:
        clear_screen()
        try:
            choice = questionary.select(
                "Categories — what do you like to do?",
                choices=[
                    "List categories",
                    "View a category",
                    "Create a category",
                    "Update a category",
                    "Archive a category",
                    "Unarchive a category",
                    "Delete a category",
                    "Restore a deleted category",
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
    common.print_recap("categories list", flags)

    try:
        categories_cmd.list_(
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
    cat_id = prompts.pick_category(include_archived=True)
    if cat_id is prompts.BACK:
        return
    try:
        categories_cmd.get(ctx, id_=cat_id, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 3. Create


def run_create(ctx: typer.Context) -> None:
    name = common.prompt_validated_text(
        "Category name",
        lambda raw: True if raw.strip() else "Name is required.",
    )
    if name is None:
        return

    color = common.prompt_validated_text(
        "Color (free-form, e.g. #FF5733 or red)",
        lambda raw: True if raw.strip() else "Color is required.",
    )
    if color is None:
        return

    ok, sort_order = common.prompt_optional_int("Sort order")
    if not ok:
        return

    flags: list[tuple[str, str | None]] = [
        ("--name", f'"{name}"'),
        ("--color", f'"{color}"'),
    ]
    if sort_order is not None:
        flags.append(("--sort-order", str(sort_order)))
    common.print_recap("categories create", flags)

    confirm = common.prompt_yes_no("Confirm and submit?", default_no=True)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        common.pause()
        return

    try:
        categories_cmd.create(
            ctx,
            name=name,
            color=color,
            sort_order=sort_order,
            json_output=False,
        )
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 4. Update


def run_update(ctx: typer.Context) -> None:
    # System categories ARE included — engine allows rename. The picker shows
    # @Debt / @Transfer; the engine handles validation server-side.
    cat_id = prompts.pick_category(include_archived=True)
    if cat_id is prompts.BACK:
        return

    try:
        item = queries.get_category(cat_id)
    except Exception as exc:  # pragma: no cover — picker came from cache
        typer.echo(f"Could not load category: {exc}", err=True)
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
        new_color = common.prompt_validated_text(
            "New color",
            lambda raw: True if raw.strip() else "Color is required.",
        )
        if new_color is None:
            return
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
    common.print_recap(f"categories update {cat_id}", flags)

    confirm = common.prompt_yes_no("Confirm and submit?", default_no=True)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        common.pause()
        return

    try:
        categories_cmd.update(
            ctx,
            id_=cat_id,
            name=changes.get("name"),
            color=changes.get("color"),
            sort_order=changes.get("sort_order"),
            json_output=False,
        )
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 5. Archive


def run_archive(ctx: typer.Context) -> None:
    cat_id = prompts.pick_category(exclude_system=True)
    if cat_id is prompts.BACK:
        return
    confirmed = prompts.confirm_destructive(
        f"Archive category {cat_id[:8]}…?",
        warning="Hides from pickers; existing transactions keep their reference.",
    )
    if not confirmed:
        typer.echo("Aborted.")
        common.pause()
        return
    try:
        categories_cmd.archive(ctx, id_=cat_id, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 6. Unarchive


def run_unarchive(ctx: typer.Context) -> None:
    cat_id = prompts.pick_category(only_archived=True)
    if cat_id is prompts.BACK:
        return
    confirm = common.prompt_yes_no("Unarchive?", default_no=False)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        common.pause()
        return
    try:
        categories_cmd.unarchive(ctx, id_=cat_id, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 7. Delete


def run_delete(ctx: typer.Context) -> None:
    cat_id = prompts.pick_category(include_archived=True, exclude_system=True)
    if cat_id is prompts.BACK:
        return
    confirmed = prompts.confirm_destructive(
        f"Delete category {cat_id[:8]}…?",
        warning=(
            "Soft-delete: restorable. For cleanup/mistakes only — "
            "use Archive to retire a category with transactions/history."
        ),
    )
    if not confirmed:
        typer.echo("Aborted.")
        common.pause()
        return
    try:
        categories_cmd.delete(ctx, id_=cat_id, yes=True, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- 8. Restore


def run_restore(ctx: typer.Context) -> None:
    cat_id = prompts.pick_category(only_deleted=True)
    if cat_id is prompts.BACK:
        return
    confirm = common.prompt_yes_no("Restore?", default_no=False)
    if confirm is None or not confirm:
        typer.echo("Aborted.")
        common.pause()
        return
    try:
        categories_cmd.restore(ctx, id_=cat_id, json_output=False)
    except typer.Exit:
        pass
    common.pause()


# ----------------------------------------------------------- dispatch

_HANDLERS = {
    "List categories": run_list,
    "View a category": run_get,
    "Create a category": run_create,
    "Update a category": run_update,
    "Archive a category": run_archive,
    "Unarchive a category": run_unarchive,
    "Delete a category": run_delete,
    "Restore a deleted category": run_restore,
}
