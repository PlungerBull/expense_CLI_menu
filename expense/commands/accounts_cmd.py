import json
from uuid import uuid4

import typer

from expense import config as config_module
from expense.commands._resource import (
    INCLUDE_ARCHIVED_OPT,
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
    format_cents,
    items_of,
    render_pagination_hint,
    render_record,
    render_table,
    require_yes,
    run_toggle,
)
from expense.context import get_verbose
from expense.dates import now_local_iso, to_canonical_aware
from expense.errors import EngineError, handle_errors
from expense.http import ExpenseClient

app = typer.Typer(help="Bank accounts.", no_args_is_help=True)

_RESOURCE = "accounts"


def _render_account_list(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    items = items_of(body)
    if not items:
        typer.echo("(no accounts)")
        return

    color = color_supported()
    rows = [
        {
            "name": item.get("name") or "(unnamed)",
            "currency": item.get("currency_code") or "?",
            "person": format_bool(item.get("is_person")),
            "color": color_swatch(item.get("color"), color=color),
            "balance": format_cents(item.get("current_balance_cents")),
            "archived": format_bool(item.get("is_archived")),
            "deleted": format_bool(item.get("deleted_at")),
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
            "deleted": "Deleted",
        },
        rows=rows,
        align_right={"balance"},
    )
    render_pagination_hint(body, items)


def fetch_accounts(
    cfg,
    *,
    include_archived: bool = False,
    include_deleted: bool = False,
    include_people: bool = False,
    limit: int | None = None,
    offset: int | None = None,
    verbose: bool = False,
):
    """GET /v1/accounts → the raw engine body. Pure data.

    Shared by the flat `accounts list` command and the TUI's Accounts screen.
    Without limit/offset the body is the flat list internal consumers rely on;
    with either set it's the standard {items,total,limit,offset} envelope.
    """
    params: dict = {}
    if include_archived:
        params["include_archived"] = "true"
    if include_deleted:
        params["include_deleted"] = "true"
    if include_people:
        params["include_people"] = "true"
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
    include_archived: bool = INCLUDE_ARCHIVED_OPT,
    include_deleted: bool = INCLUDE_DELETED_OPT,
    include_people: bool = typer.Option(
        False, "--include-people", help="Include person (payable/receivable) accounts."
    ),
    limit: int | None = LIMIT_OPT,
    offset: int | None = OFFSET_OPT,
    json_output: bool = JSON_OPT,
) -> None:
    """GET /v1/accounts.

    Example: expense accounts list --include-archived
    """
    cfg = config_module.ensure_loaded()
    limit = effective_limit(limit, json_mode=json_output)
    body = fetch_accounts(
        cfg,
        include_archived=include_archived,
        include_deleted=include_deleted,
        include_people=include_people,
        limit=limit,
        offset=offset,
        verbose=get_verbose(ctx),
    )
    _render_account_list(body, json_mode=json_output)


@app.command("get")
@handle_errors
def get(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = JSON_OPT,
) -> None:
    """GET /v1/accounts/{id}.

    Example: expense accounts get <account-id>
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
    name: str = typer.Option(..., "--name", help="Account name (unique per currency)."),
    currency_code: str = typer.Option(
        ..., "--currency-code", help="ISO 4217 currency code (e.g. USD, PEN)."
    ),
    color: str | None = typer.Option(
        None, "--color", help="6-digit hex color, e.g. #3b82f6. Omit for the default blue."
    ),
    sort_order: int | None = typer.Option(None, "--sort-order"),
    json_output: bool = JSON_OPT,
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
    if not json_output:
        typer.echo(f"Created: {new_id}")
    render_record(body, json_mode=json_output)


@app.command("opening-balance")
@handle_errors
def opening_balance(
    ctx: typer.Context,
    account_id: str = typer.Argument(..., help="Account UUID to seed."),
    amount: int = typer.Option(
        ...,
        "--amount",
        help="Signed cents. Positive = money you had, negative = starting debt.",
    ),
    date: str | None = typer.Option(
        None,
        "--date",
        help="YYYY-MM-DD, 'YYYY-MM-DD HH:MM[:SS]', or RFC 3339 with offset. "
        "Naive forms get the local timezone attached. Defaults to now.",
    ),
    title: str | None = typer.Option(
        None, "--title", help='Seed transaction title. Engine defaults to "Opening balance".'
    ),
    json_output: bool = JSON_OPT,
) -> None:
    """POST /v1/accounts/{id}/opening-balance.

    Seeds the account's starting balance as a transaction under the @Opening
    system category. The seed counts toward the account balance but is
    excluded from flow reports (dashboard month panel, monthly report) — an
    opening balance is where tracking starts, not money that moved. One active
    opening balance per account; to adjust it, edit or delete the existing
    seed transaction (it is an ordinary transaction).

    Example: expense accounts opening-balance <id> --amount 1250000 --date 2026-01-01
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    new_id = str(uuid4())
    payload: dict = {
        "transaction_id": new_id,
        "amount_cents": amount,
        "date": to_canonical_aware(date) if date is not None else now_local_iso(),
    }
    if title is not None:
        payload["title"] = title

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.post(f"/{_RESOURCE}/{account_id}/opening-balance", json_body=payload)
    if not json_output:
        typer.echo(f"Seeded opening balance: {new_id}")
    render_record(body, json_mode=json_output)


@app.command("update")
@handle_errors
def update(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    name: str | None = typer.Option(None, "--name"),
    color: str | None = typer.Option(None, "--color", help="6-digit hex color, e.g. #3b82f6."),
    sort_order: int | None = typer.Option(None, "--sort-order"),
    currency_code: str | None = typer.Option(
        None,
        "--currency-code",
        help="Rejected: currency is immutable after creation.",
    ),
    json_output: bool = JSON_OPT,
) -> None:
    """PUT /v1/accounts/{id}.

    Example: expense accounts update <account-id> --name "BCP Soles (joint)"
    """
    # sanctioned exception — see cli-spec.md "Sanctioned exceptions": the flag
    # exists solely to fail fast with honest help text (engine would 422).
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
    render_record(body, json_mode=json_output)


@app.command("delete")
@handle_errors
def delete(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    yes: bool = YES_OPT,
    json_output: bool = JSON_OPT,
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
    render_record(body, json_mode=json_output)


@app.command("restore")
@handle_errors
def restore(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = JSON_OPT,
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
        render_human=lambda body: render_record(body, json_mode=False),
    )


@app.command("archive")
@handle_errors
def archive(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = JSON_OPT,
) -> None:
    """POST /v1/accounts/{id}/archive. Hides from pickers; transactions remain.

    Prompt-free: archive is a reversible toggle (unarchive undoes it).

    Example: expense accounts archive <account-id>
    """
    run_toggle(
        ctx,
        resource=_RESOURCE,
        id_=id_,
        verb="archive",
        json_output=json_output,
        render_human=lambda body: render_record(body, json_mode=False),
    )


@app.command("unarchive")
@handle_errors
def unarchive(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = JSON_OPT,
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
        render_human=lambda body: render_record(body, json_mode=False),
    )
