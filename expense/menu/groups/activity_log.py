"""Menu flows for the Activity log group (Step 9.5.14).

Three flag-preset wrappers over `expense activity list`:
  - List all recent activity
  - Filter by resource type
  - Filter by specific record (resource_type + resource_id)

Pagination is interactive via a `Show next page?` loop — the engine's
default page size is used (no explicit limit) and `total` from the
response drives the loop. Activity log is engine-direct (not in the
SQLite replica), so each page is a live engine call.
"""

import questionary
import typer

from expense import config as config_module
from expense.commands import activity_cmd
from expense.context import get_verbose
from expense.errors import EngineConnectionError, EngineError, render
from expense.http import ExpenseClient
from expense.menu import prompts
from expense.menu.groups import _common as common
from expense.menu.term import clear_screen

BACK_LABEL = "← Back"

_RESOURCE_TYPES = [
    "expense_transactions",
    "accounts",
    "categories",
    "hashtags",
    "inbox_items",
    "reconciliations",
]

# Subset of _RESOURCE_TYPES that have cache-backed pickers in expense.menu.prompts.
# Reconciliations are excluded because `pick_reconciliation` requires an
# account_id upfront — that's a different UX shape than the other pickers.
_RESOURCE_TYPES_WITH_PICKERS = [
    "expense_transactions",
    "accounts",
    "categories",
    "hashtags",
    "inbox_items",
]


def run_activity_log_menu(ctx: typer.Context) -> None:
    """Activity log sub-menu loop."""
    while True:
        clear_screen()
        try:
            choice = questionary.select(
                "Activity log — what do you like to do?",
                choices=[
                    "List all recent activity",
                    "Filter by resource type",
                    "Filter by specific record",
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


# --------------------------------------------------------------- helpers


def _recap_flags(
    resource_type: str | None, resource_id: str | None
) -> list[tuple[str, str | None]]:
    return [
        ("--resource-type", resource_type),
        ("--resource-id", resource_id),
    ]


def _paginated_list(
    ctx: typer.Context,
    base_params: dict,
) -> None:
    """Drive the engine-direct paginated read with an interactive `next page?` loop.

    Renders rows via `activity_cmd._render_activity_rows` so the table is
    byte-identical to `expense activity list`. Errors fall back to the
    standard error envelope.
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)
    offset = 0
    rendered_any = False

    try:
        with ExpenseClient(cfg, verbose=verbose) as client:
            while True:
                params = dict(base_params)
                if offset:
                    params["offset"] = offset
                body = client.get("/activity", params=params or None)

                items = body.get("items", body) if isinstance(body, dict) else body
                if not items:
                    if not rendered_any:
                        typer.echo("(no activity)")
                    return

                activity_cmd._render_activity_rows(items)
                rendered_any = True

                if not isinstance(body, dict):
                    # Bare list — engine didn't return pagination metadata.
                    return
                total = body.get("total")
                if not isinstance(total, int):
                    return
                shown = offset + len(items)
                typer.echo(f"\nShowing {shown} of {total}")
                if shown >= total:
                    return
                answer = common.prompt_yes_no("Show next page?", default_no=False)
                if not answer:
                    return
                offset = shown
    except (EngineError, EngineConnectionError) as err:
        output, _exit_code, use_stderr = render(err, json_mode=False)
        typer.echo(output, err=use_stderr)


# --------------------------------------------------------------- 1. List all


def run_list_all(ctx: typer.Context) -> None:
    common.print_recap("activity list", _recap_flags(None, None))
    _paginated_list(ctx, {})
    common.pause()


# --------------------------------------------------------------- 2. By type


def _prompt_resource_type(choices: list[str]) -> str | None:
    answer = questionary.select(
        "Resource type",
        choices=[*choices, BACK_LABEL],
    ).ask()
    if answer is None or answer == BACK_LABEL:
        return None
    return answer


def run_list_by_resource_type(ctx: typer.Context) -> None:
    resource_type = _prompt_resource_type(_RESOURCE_TYPES)
    if resource_type is None:
        return
    common.print_recap("activity list", _recap_flags(resource_type, None))
    _paginated_list(ctx, {"resource_type": resource_type})
    common.pause()


# --------------------------------------------------------------- 3. By record


def _pick_record_id(resource_type: str) -> object:
    """Dispatch to the matching cache-backed picker for `resource_type`.

    Returns the chosen UUID (str), or `prompts.BACK` if the user backed out.
    """
    if resource_type == "expense_transactions":
        return prompts.pick_transaction(prompt="Transaction")
    if resource_type == "accounts":
        return prompts.pick_account(include_archived=True, include_people=True, prompt="Account")
    if resource_type == "categories":
        return prompts.pick_category(include_archived=True, prompt="Category")
    if resource_type == "hashtags":
        return prompts.pick_hashtag(include_archived=True, prompt="Hashtag")
    if resource_type == "inbox_items":
        return prompts.pick_inbox(prompt="Inbox item")
    return prompts.BACK


def run_list_by_record(ctx: typer.Context) -> None:
    resource_type = _prompt_resource_type(_RESOURCE_TYPES_WITH_PICKERS)
    if resource_type is None:
        return
    record_id = _pick_record_id(resource_type)
    if record_id is prompts.BACK or record_id is prompts.SKIP or not isinstance(record_id, str):
        return
    common.print_recap("activity list", _recap_flags(resource_type, record_id))
    _paginated_list(
        ctx,
        {"resource_type": resource_type, "resource_id": record_id},
    )
    common.pause()


# --------------------------------------------------------------- dispatch

_HANDLERS = {
    "List all recent activity": run_list_all,
    "Filter by resource type": run_list_by_resource_type,
    "Filter by specific record": run_list_by_record,
}
