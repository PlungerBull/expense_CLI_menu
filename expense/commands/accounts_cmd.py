import json
from uuid import uuid4

import typer

from expense import cache as cache_pkg
from expense import config as config_module
from expense.commands._resource import (
    build_update_payload,
    cache_after_write,
    color_supported,
    color_swatch,
    render_pagination_hint,
    render_table,
    require_yes,
    run_toggle,
)
from expense.context import get_no_cache, get_verbose
from expense.errors import EngineError, handle_errors
from expense.http import ExpenseClient

app = typer.Typer(help="Bank accounts.", no_args_is_help=True)

_RESOURCE = "accounts"


def _render_account(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    for key, value in body.items():
        display = value if value is not None else "(null)"
        typer.echo(f"  {key}: {display}")


def _fmt_bool(value: object) -> str:
    return "yes" if bool(value) else "no"


def _fmt_balance(cents: object) -> str:
    return "(null)" if cents is None else str(cents)


def _render_account_list(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    items = body.get("items", body) if isinstance(body, dict) else body
    if not items:
        typer.echo("(no accounts)")
        return

    color = color_supported()
    rows = [
        {
            "name": item.get("name") or "(unnamed)",
            "currency": item.get("currency_code") or "?",
            "person": _fmt_bool(item.get("is_person")),
            "color": color_swatch(item.get("color"), color=color),
            "balance": _fmt_balance(item.get("current_balance_cents")),
            "archived": _fmt_bool(item.get("is_archived")),
        }
        for item in items
    ]
    render_table(
        headers={
            "name": "Name",
            "currency": "Currency",
            "person": "Person",
            "color": "Color",
            "balance": "Balance",
            "archived": "Archived",
        },
        rows=rows,
        align_right={"balance"},
    )
    render_pagination_hint(body, items)


@app.command("list")
@handle_errors
def list_(
    ctx: typer.Context,
    include_archived: bool = typer.Option(False, "--include-archived"),
    include_deleted: bool = typer.Option(False, "--include-deleted"),
    include_people: bool = typer.Option(False, "--include-people"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """GET /v1/accounts. Reads from the local replica by default.

    Pass --no-cache (root flag) to round-trip the engine. Cached reads return
    current_balance_home_cents=null; for current home balances run
    `expense dashboard` or pass --no-cache.

    Example: expense accounts list --include-archived
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
        if include_people:
            params["include_people"] = "true"

        with ExpenseClient(cfg, verbose=verbose) as client:
            body = client.get(f"/{_RESOURCE}", params=params or None)
    else:
        with ExpenseClient(cfg, verbose=verbose, cold_start_notice=True) as client:
            cache_pkg.ensure_synced(client, cfg)
        body = cache_pkg.list_accounts(
            include_archived=include_archived,
            include_deleted=include_deleted,
            include_people=include_people,
        )

    _render_account_list(body, json_mode=json_output)


@app.command("get")
@handle_errors
def get(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """GET /v1/accounts/{id}. Reads from the local replica by default.

    Pass --no-cache (root flag) to round-trip the engine. Cached reads return
    current_balance_home_cents=null.

    Example: expense accounts get <account-id>
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
        body = cache_pkg.get_account(id_)

    _render_account(body, json_mode=json_output)


@app.command("create")
@handle_errors
def create(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Account name (unique per currency)."),
    currency_code: str = typer.Option(
        ..., "--currency-code", help="ISO 4217 currency code (e.g. USD, PEN)."
    ),
    color: str | None = typer.Option(None, "--color", help="Color hint (free-form string)."),
    sort_order: int | None = typer.Option(None, "--sort-order"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """POST /v1/accounts.

    Example: expense accounts create --name "BCP Soles" --currency-code PEN
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    new_id = str(uuid4())
    payload: dict = {
        "id": new_id,
        "name": name,
        "currency_code": currency_code,
    }
    if color is not None:
        payload["color"] = color
    if sort_order is not None:
        payload["sort_order"] = sort_order

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.post(f"/{_RESOURCE}", json_body=payload)
        cache_after_write(ctx, client, cfg)

    if not json_output:
        typer.echo(f"Created: {new_id}")
    _render_account(body, json_mode=json_output)


@app.command("update")
@handle_errors
def update(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    name: str | None = typer.Option(None, "--name"),
    color: str | None = typer.Option(None, "--color"),
    sort_order: int | None = typer.Option(None, "--sort-order"),
    currency_code: str | None = typer.Option(
        None,
        "--currency-code",
        help="Rejected: currency is immutable after creation.",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """PUT /v1/accounts/{id}.

    Example: expense accounts update <account-id> --name "BCP Soles (joint)"
    """
    if currency_code is not None:
        raise typer.BadParameter(
            "Currency cannot be changed after creation. Create a new account.",
            param_hint="--currency-code",
        )

    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    payload = build_update_payload({"name": name, "color": color, "sort_order": sort_order})

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.put(f"/{_RESOURCE}/{id_}", json_body=payload)
        cache_after_write(ctx, client, cfg)

    _render_account(body, json_mode=json_output)


@app.command("delete")
@handle_errors
def delete(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """DELETE /v1/accounts/{id}. Soft-delete (use archive for closed accounts with history).

    Example: expense accounts delete <account-id> --yes
    """
    require_yes(yes, f"Delete account {id_}? This is for cleanup/mistakes only.")

    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    with ExpenseClient(cfg, verbose=verbose) as client:
        try:
            body = client.delete(f"/{_RESOURCE}/{id_}")
        except EngineError as err:
            if err.status == 409:
                typer.echo(
                    f"Hint: This account has transactions and cannot be deleted. "
                    f"Try 'expense accounts archive {id_}' to retire it instead.",
                    err=True,
                )
            raise
        cache_after_write(ctx, client, cfg)

    _render_account(body, json_mode=json_output)


@app.command("restore")
@handle_errors
def restore(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """POST /v1/accounts/{id}/restore.

    Example: expense accounts restore <account-id>
    """
    run_toggle(
        ctx,
        resource=_RESOURCE,
        id_=id_,
        verb="restore",
        json_output=json_output,
        render_human=lambda body: _render_account(body, json_mode=False),
    )


@app.command("archive")
@handle_errors
def archive(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """POST /v1/accounts/{id}/archive. Hides from pickers; transactions remain.

    Example: expense accounts archive <account-id>
    """
    run_toggle(
        ctx,
        resource=_RESOURCE,
        id_=id_,
        verb="archive",
        json_output=json_output,
        render_human=lambda body: _render_account(body, json_mode=False),
    )


@app.command("unarchive")
@handle_errors
def unarchive(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """POST /v1/accounts/{id}/unarchive.

    Example: expense accounts unarchive <account-id>
    """
    run_toggle(
        ctx,
        resource=_RESOURCE,
        id_=id_,
        verb="unarchive",
        json_output=json_output,
        render_human=lambda body: _render_account(body, json_mode=False),
    )
