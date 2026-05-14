import json
from uuid import uuid4

import typer

from expense import cache as cache_pkg
from expense import config as config_module
from expense.commands._resource import (
    build_update_payload,
    cache_after_write,
    render_pagination_hint,
    render_table,
    require_yes,
    run_toggle,
)
from expense.context import get_no_cache, get_verbose
from expense.errors import handle_errors
from expense.http import ExpenseClient

app = typer.Typer(help="Hashtags.", no_args_is_help=True)

_RESOURCE = "hashtags"


def _render_hashtag(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    for key, value in body.items():
        display = value if value is not None else "(null)"
        typer.echo(f"  {key}: {display}")


def _fmt_bool(value: object) -> str:
    return "yes" if bool(value) else "no"


def _render_hashtag_list(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    items = body.get("items", body) if isinstance(body, dict) else body
    if not items:
        typer.echo("(no hashtags)")
        return

    rows = [
        {
            "name": item.get("name") or "(unnamed)",
            "archived": _fmt_bool(item.get("is_archived")),
            "deleted": _fmt_bool(item.get("deleted_at")),
        }
        for item in items
    ]
    render_table(
        headers={
            "name": "Name",
            "archived": "Archived",
            "deleted": "Deleted",
        },
        rows=rows,
    )
    render_pagination_hint(body, items)


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
    """GET /v1/hashtags. Reads from the local replica by default.

    Pass --no-cache (root flag) to round-trip the engine.

    Example: expense hashtags list --include-archived
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)
    no_cache = get_no_cache(ctx)

    if no_cache:
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
    else:
        with ExpenseClient(cfg, verbose=verbose, cold_start_notice=True) as client:
            cache_pkg.ensure_synced(client, cfg)
        body = cache_pkg.list_hashtags(
            include_archived=include_archived,
            include_deleted=include_deleted,
            limit=limit,
            offset=offset,
        )

    _render_hashtag_list(body, json_mode=json_output)


@app.command("get")
@handle_errors
def get(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """GET /v1/hashtags/{id}. Reads from the local replica by default.

    Pass --no-cache (root flag) to round-trip the engine.

    Example: expense hashtags get <hashtag-id>
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)
    no_cache = get_no_cache(ctx)

    if no_cache:
        with ExpenseClient(cfg, verbose=verbose) as client:
            body = client.get(f"/{_RESOURCE}/{id_}")
    else:
        with ExpenseClient(cfg, verbose=verbose, cold_start_notice=True) as client:
            cache_pkg.ensure_synced(client, cfg)
        body = cache_pkg.get_hashtag(id_)

    _render_hashtag(body, json_mode=json_output)


@app.command("create")
@handle_errors
def create(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Hashtag name (case-insensitive unique)."),
    sort_order: int | None = typer.Option(None, "--sort-order"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """POST /v1/hashtags. Hashtags are NOT auto-created on transaction use.

    Example: expense hashtags create --name lunch
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    new_id = str(uuid4())
    payload: dict = {"id": new_id, "name": name}
    if sort_order is not None:
        payload["sort_order"] = sort_order

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.post(f"/{_RESOURCE}", json_body=payload)
        cache_after_write(ctx, client, cfg)

    if not json_output:
        typer.echo(f"Created: {new_id}")
    _render_hashtag(body, json_mode=json_output)


@app.command("update")
@handle_errors
def update(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    name: str | None = typer.Option(None, "--name"),
    sort_order: int | None = typer.Option(None, "--sort-order"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """PUT /v1/hashtags/{id}.

    Example: expense hashtags update <hashtag-id> --name lunch-work
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    payload = build_update_payload({"name": name, "sort_order": sort_order})

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.put(f"/{_RESOURCE}/{id_}", json_body=payload)
        cache_after_write(ctx, client, cfg)

    _render_hashtag(body, json_mode=json_output)


@app.command("delete")
@handle_errors
def delete(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """DELETE /v1/hashtags/{id}. Cascades soft-delete to junction rows; restore does NOT undo.

    Example: expense hashtags delete <hashtag-id> --yes
    """
    require_yes(
        yes,
        f"Delete hashtag {id_}? Junction rows on transactions will be cascaded "
        "(restore does not undo this).",
    )

    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.delete(f"/{_RESOURCE}/{id_}")
        cache_after_write(ctx, client, cfg)

    _render_hashtag(body, json_mode=json_output)


@app.command("restore")
@handle_errors
def restore(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """POST /v1/hashtags/{id}/restore. Does NOT restore cascaded junction rows.

    Example: expense hashtags restore <hashtag-id>
    """
    run_toggle(
        ctx,
        resource=_RESOURCE,
        id_=id_,
        verb="restore",
        json_output=json_output,
        render_human=lambda body: _render_hashtag(body, json_mode=False),
    )


@app.command("archive")
@handle_errors
def archive(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """POST /v1/hashtags/{id}/archive. Junction rows left intact.

    Example: expense hashtags archive <hashtag-id>
    """
    run_toggle(
        ctx,
        resource=_RESOURCE,
        id_=id_,
        verb="archive",
        json_output=json_output,
        render_human=lambda body: _render_hashtag(body, json_mode=False),
    )


@app.command("unarchive")
@handle_errors
def unarchive(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """POST /v1/hashtags/{id}/unarchive.

    Example: expense hashtags unarchive <hashtag-id>
    """
    run_toggle(
        ctx,
        resource=_RESOURCE,
        id_=id_,
        verb="unarchive",
        json_output=json_output,
        render_human=lambda body: _render_hashtag(body, json_mode=False),
    )
