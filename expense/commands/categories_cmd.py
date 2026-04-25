import json
from uuid import uuid4

import typer

from expense import config as config_module
from expense.commands._resource import build_update_payload, require_yes, run_toggle
from expense.context import get_verbose
from expense.errors import EngineError, handle_errors
from expense.http import ExpenseClient

app = typer.Typer(help="Categories.", no_args_is_help=True)

_RESOURCE = "categories"
_SYSTEM_HINT = "System categories (@Debt, @Transfer) cannot be modified."


def _render_category(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    for key, value in body.items():
        display = value if value is not None else "(null)"
        typer.echo(f"  {key}: {display}")


def _render_category_list(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    items = body.get("items", body) if isinstance(body, dict) else body
    if not items:
        typer.echo("(no categories)")
        return
    for index, item in enumerate(items):
        if index > 0:
            typer.echo("")
        for key, value in item.items():
            display = value if value is not None else "(null)"
            typer.echo(f"  {key}: {display}")


@app.command("list")
@handle_errors
def list_(
    ctx: typer.Context,
    include_archived: bool = typer.Option(False, "--include-archived"),
    include_deleted: bool = typer.Option(False, "--include-deleted"),
    limit: int | None = typer.Option(None, "--limit"),
    offset: int | None = typer.Option(None, "--offset"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """GET /v1/categories."""
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    params: dict = {}
    if include_archived:
        params["include_archived"] = "true"
    if include_deleted:
        params["include_deleted"] = "true"
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.get(f"/{_RESOURCE}", params=params or None)

    _render_category_list(body, json_mode=json_output)


@app.command("get")
@handle_errors
def get(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """GET /v1/categories/{id}."""
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.get(f"/{_RESOURCE}/{id_}")

    _render_category(body, json_mode=json_output)


@app.command("create")
@handle_errors
def create(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Category name (case-insensitive unique)."),
    color: str = typer.Option(..., "--color", help="Color hint (free-form string)."),
    sort_order: int | None = typer.Option(None, "--sort-order"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """POST /v1/categories."""
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
    _render_category(body, json_mode=json_output)


@app.command("update")
@handle_errors
def update(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    name: str | None = typer.Option(None, "--name"),
    color: str | None = typer.Option(None, "--color"),
    sort_order: int | None = typer.Option(None, "--sort-order"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """PUT /v1/categories/{id}. System categories CAN be renamed."""
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    payload = build_update_payload({"name": name, "color": color, "sort_order": sort_order})

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.put(f"/{_RESOURCE}/{id_}", json_body=payload)

    _render_category(body, json_mode=json_output)


@app.command("delete")
@handle_errors
def delete(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """DELETE /v1/categories/{id}. Soft-delete (use archive for categories with history)."""
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
                    f"Hint: This category has transactions and cannot be deleted. "
                    f"Try 'expense categories archive {id_}' to retire it instead.",
                    err=True,
                )
            raise

    _render_category(body, json_mode=json_output)


@app.command("restore")
@handle_errors
def restore(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """POST /v1/categories/{id}/restore."""
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    with ExpenseClient(cfg, verbose=verbose) as client:
        try:
            body = client.post(f"/{_RESOURCE}/{id_}/restore")
        except EngineError as err:
            if err.status == 409:
                typer.echo(
                    "Hint: A category with that name already exists. "
                    "Rename the existing one first.",
                    err=True,
                )
            raise

    _render_category(body, json_mode=json_output)


@app.command("archive")
@handle_errors
def archive(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """POST /v1/categories/{id}/archive."""
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    with ExpenseClient(cfg, verbose=verbose) as client:
        try:
            body = client.post(f"/{_RESOURCE}/{id_}/archive")
        except EngineError as err:
            if err.status == 403:
                typer.echo(f"Hint: {_SYSTEM_HINT}", err=True)
            raise

    _render_category(body, json_mode=json_output)


@app.command("unarchive")
@handle_errors
def unarchive(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """POST /v1/categories/{id}/unarchive."""
    run_toggle(
        ctx,
        resource=_RESOURCE,
        id_=id_,
        verb="unarchive",
        json_output=json_output,
        render_human=lambda body: _render_category(body, json_mode=False),
    )
