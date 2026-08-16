import json
from uuid import uuid4

import typer

from expense import config as config_module
from expense.commands._resource import (
    INCLUDE_DELETED_OPT,
    JSON_OPT,
    LIMIT_OPT,
    OFFSET_OPT,
    YES_OPT,
    build_update_payload,
    color_supported,
    color_swatch,
    effective_limit,
    fetch_body,
    format_bool,
    items_of,
    render_pagination_hint,
    render_record,
    render_table,
    require_yes,
    run_toggle,
)
from expense.context import get_verbose
from expense.errors import EngineError, handle_errors
from expense.http import ExpenseClient

app = typer.Typer(help="Categories.", no_args_is_help=True)

_RESOURCE = "categories"
_SYSTEM_HINT = "System categories (@Debt, @Transfer) cannot be modified."


def _render_category_list(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    items = items_of(body)
    if not items:
        typer.echo("(no categories)")
        return

    color = color_supported()
    rows = [
        {
            "name": item.get("name") or "(unnamed)",
            "color": color_swatch(item.get("color"), color=color),
            "system": format_bool(item.get("is_system")),
            "deleted": format_bool(item.get("deleted_at")),
        }
        for item in items
    ]
    render_table(
        headers={
            "name": "Name",
            "color": "Color",
            "system": "System",
            "deleted": "Deleted",
        },
        rows=rows,
    )
    render_pagination_hint(body, items)


def fetch_categories(
    cfg,
    *,
    include_deleted: bool = False,
    limit: int | None = None,
    offset: int | None = None,
    verbose: bool = False,
) -> dict:
    """GET /v1/categories → the raw engine body. Pure data, no render.

    Shared by the flat `categories list` command and the TUI's Categories screen.
    """
    params: dict = {}
    if include_deleted:
        params["include_deleted"] = "true"
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    return fetch_body(
        cfg,
        path=f"/{_RESOURCE}",
        params=params,
        verbose=verbose,
    )


@app.command("list")
@handle_errors
def list_(
    ctx: typer.Context,
    include_deleted: bool = INCLUDE_DELETED_OPT,
    limit: int | None = LIMIT_OPT,
    offset: int | None = OFFSET_OPT,
    json_output: bool = JSON_OPT,
) -> None:
    """GET /v1/categories.

    Example: expense categories list
    """
    cfg = config_module.ensure_loaded()
    limit = effective_limit(limit, json_mode=json_output)
    body = fetch_categories(
        cfg,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
        verbose=get_verbose(ctx),
    )
    _render_category_list(body, json_mode=json_output)


@app.command("get")
@handle_errors
def get(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = JSON_OPT,
) -> None:
    """GET /v1/categories/{id}.

    Example: expense categories get <category-id>
    """
    cfg = config_module.ensure_loaded()
    body = fetch_body(
        cfg,
        path=f"/{_RESOURCE}/{id_}",
        params=None,
        verbose=get_verbose(ctx),
    )
    render_record(body, json_mode=json_output)


@app.command("create")
@handle_errors
def create(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Category name (case-insensitive unique)."),
    color: str = typer.Option(..., "--color", help="6-digit hex color, e.g. #3b82f6. Required."),
    sort_order: int | None = typer.Option(None, "--sort-order"),
    json_output: bool = JSON_OPT,
) -> None:
    """POST /v1/categories.

    Example: expense categories create --name Food --color "#FF6B6B"
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    new_id = str(uuid4())
    payload: dict = {
        "id": new_id,
        "name": name,
        "color": color,
    }
    if sort_order is not None:
        payload["sort_order"] = sort_order

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.post(f"/{_RESOURCE}", json_body=payload)
    if not json_output:
        typer.echo(f"Created: {new_id}")
    render_record(body, json_mode=json_output)


@app.command("update")
@handle_errors
def update(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    name: str | None = typer.Option(None, "--name"),
    color: str | None = typer.Option(None, "--color", help="6-digit hex color, e.g. #3b82f6."),
    sort_order: int | None = typer.Option(None, "--sort-order"),
    json_output: bool = JSON_OPT,
) -> None:
    """PUT /v1/categories/{id}. System categories CAN be renamed.

    Example: expense categories update <category-id> --name "Food & Drink"
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    payload = build_update_payload({"name": name, "color": color, "sort_order": sort_order})

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.put(f"/{_RESOURCE}/{id_}", json_body=payload)
    render_record(body, json_mode=json_output)


@app.command("delete")
@handle_errors
def delete(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    yes: bool = YES_OPT,
    json_output: bool = JSON_OPT,
) -> None:
    """DELETE /v1/categories/{id}. Soft-delete, for cleanup/mistakes only.

    Example: expense categories delete <category-id> --yes
    """
    require_yes(yes, f"Delete category {id_}? This is for cleanup/mistakes only.")

    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    with ExpenseClient(cfg, verbose=verbose) as client:
        try:
            body = client.delete(f"/{_RESOURCE}/{id_}")
        except EngineError as err:
            if err.status == 403:
                typer.echo(f"Hint: {_SYSTEM_HINT}", err=True)
            elif err.status == 409:
                typer.echo(
                    "Hint: This category has transactions and cannot be deleted. "
                    "Recategorize them first if you want to retire it.",
                    err=True,
                )
            raise
    render_record(body, json_mode=json_output)


@app.command("restore")
@handle_errors
def restore(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = JSON_OPT,
) -> None:
    """POST /v1/categories/{id}/restore.

    Example: expense categories restore <category-id>
    """
    run_toggle(
        ctx,
        resource=_RESOURCE,
        id_=id_,
        verb="restore",
        json_output=json_output,
        render_human=lambda body: render_record(body, json_mode=False),
        hints={
            409: ("Hint: A category with that name already exists. Rename the existing one first."),
        },
    )
