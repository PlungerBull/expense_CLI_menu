import json

import typer

from expense import config as config_module
from expense.commands._resource import render_pagination_hint
from expense.context import get_verbose
from expense.errors import handle_errors
from expense.http import ExpenseClient

app = typer.Typer(help="Activity log (audit trail).", no_args_is_help=True)

_RESOURCE = "activity"

_ACTION_NAMES = {1: "CREATED", 2: "UPDATED", 3: "DELETED", 4: "RESTORED"}


def _action_label(action: object) -> str:
    if isinstance(action, int) and action in _ACTION_NAMES:
        return _ACTION_NAMES[action]
    return str(action)


def _render_row(row: dict) -> None:
    typer.echo(f"  created_at  {row.get('created_at', '(null)')}")
    typer.echo(f"  action      {_action_label(row.get('action'))}")
    actor = row.get("changed_by", "(null)")
    actor_type = row.get("actor_type", "(null)")
    typer.echo(f"  actor       {actor} ({actor_type})")
    resource_type = row.get("resource_type", "(null)")
    resource_id = row.get("resource_id", "(null)")
    typer.echo(f"  resource    {resource_type} {resource_id}")
    typer.echo(f"  id          {row.get('id', '(null)')}")


def _render_list(body: object, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    items = body.get("items", body) if isinstance(body, dict) else body
    if not items:
        typer.echo("(no activity)")
        return
    for index, item in enumerate(items):
        if index > 0:
            typer.echo("")
        _render_row(item)
    render_pagination_hint(body, items)


@app.command("list")
@handle_errors
def list_(
    ctx: typer.Context,
    resource_type: str | None = typer.Option(
        None,
        "--resource-type",
        help="Filter by resource_type (e.g. expense_transactions).",
    ),
    resource_id: str | None = typer.Option(
        None,
        "--resource-id",
        help="Filter by resource_id (UUID; engine validates).",
    ),
    limit: int | None = typer.Option(None, "--limit"),
    offset: int | None = typer.Option(None, "--offset"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """GET /v1/activity. Engine-direct (not cached).

    Snapshots are omitted from the human renderer; pass --json to see
    before_snapshot / after_snapshot.

    Example: expense activity list --resource-type expense_transactions --limit 5
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    params: dict = {}
    if resource_type is not None:
        params["resource_type"] = resource_type
    if resource_id is not None:
        params["resource_id"] = resource_id
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.get(f"/{_RESOURCE}", params=params or None)

    _render_list(body, json_mode=json_output)
