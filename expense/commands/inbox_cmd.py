import json
from uuid import uuid4

import typer

from expense import config as config_module
from expense.commands._resource import build_update_payload, require_yes
from expense.context import get_verbose
from expense.dates import to_canonical_aware
from expense.errors import EngineError, handle_errors
from expense.http import ExpenseClient

app = typer.Typer(
    help="Inbox: draft transactions captured before they hit the ledger.",
    no_args_is_help=True,
)

_RESOURCE = "inbox"


def _render_inbox(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    for key, value in body.items():
        display = value if value is not None else "(null)"
        typer.echo(f"  {key}: {display}")


def _render_inbox_list(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    items = body.get("items", body) if isinstance(body, dict) else body
    if not items:
        typer.echo("(no inbox items)")
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
    ready: bool = typer.Option(False, "--ready", help="Only items ready to promote."),
    include_deleted: bool = typer.Option(False, "--include-deleted"),
    overdue: bool = typer.Option(False, "--overdue", help="Only items with date in the past."),
    limit: int | None = typer.Option(None, "--limit"),
    offset: int | None = typer.Option(None, "--offset"),
    debit_as_negative: bool = typer.Option(False, "--debit-as-negative"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """GET /v1/inbox.

    Example: expense inbox list --ready
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    params: dict = {}
    if ready:
        params["ready"] = "true"
    if include_deleted:
        params["include_deleted"] = "true"
    if overdue:
        params["overdue"] = "true"
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    if debit_as_negative:
        params["debit_as_negative"] = "true"

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.get(f"/{_RESOURCE}", params=params or None)

    _render_inbox_list(body, json_mode=json_output)


@app.command("get")
@handle_errors
def get(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    debit_as_negative: bool = typer.Option(False, "--debit-as-negative"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """GET /v1/inbox/{id}.

    Example: expense inbox get <inbox-id>
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    params: dict = {}
    if debit_as_negative:
        params["debit_as_negative"] = "true"

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.get(f"/{_RESOURCE}/{id_}", params=params or None)

    _render_inbox(body, json_mode=json_output)


@app.command("add")
@handle_errors
def add(
    ctx: typer.Context,
    title: str = typer.Option(..., "--title", help="Short label for the draft."),
    amount: int = typer.Option(
        ...,
        "--amount",
        help="Signed cents. Negative = expense, positive = income. Sign is mandatory.",
    ),
    date: str | None = typer.Option(
        None,
        "--date",
        help="YYYY-MM-DD, 'YYYY-MM-DD HH:MM[:SS]', or RFC 3339 with offset. "
        "Naive forms get the local timezone attached.",
    ),
    account_id: str | None = typer.Option(
        None, "--account-id", help="Account UUID. Optional on draft; required to promote."
    ),
    category_id: str | None = typer.Option(
        None, "--category-id", help="Category UUID. Optional on draft; required to promote."
    ),
    description: str | None = typer.Option(None, "--description", help="Free-form notes."),
    cleared: bool | None = typer.Option(
        None, "--cleared/--no-cleared", help="Has the transaction posted at the bank?"
    ),
    exchange_rate: float | None = typer.Option(
        None, "--exchange-rate", help="Override engine auto-fetch."
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """POST /v1/inbox. Drop a partial draft into the inbox; fill in later, then promote.

    Example: expense inbox add --title "Lunch" --amount -1500
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    new_id = str(uuid4())
    payload: dict = {
        "id": new_id,
        "title": title,
        "amount_cents": amount,
    }
    if date is not None:
        payload["date"] = to_canonical_aware(date)
    if account_id is not None:
        payload["account_id"] = account_id
    if category_id is not None:
        payload["category_id"] = category_id
    if description is not None:
        payload["description"] = description
    if cleared is not None:
        payload["cleared"] = cleared
    if exchange_rate is not None:
        payload["exchange_rate"] = exchange_rate

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.post(f"/{_RESOURCE}", json_body=payload)

    if not json_output:
        typer.echo(f"Created: {new_id}")
    _render_inbox(body, json_mode=json_output)


@app.command("update")
@handle_errors
def update(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    title: str | None = typer.Option(None, "--title"),
    amount: int | None = typer.Option(None, "--amount"),
    date: str | None = typer.Option(None, "--date"),
    account_id: str | None = typer.Option(None, "--account-id"),
    category_id: str | None = typer.Option(None, "--category-id"),
    description: str | None = typer.Option(None, "--description"),
    cleared: bool | None = typer.Option(None, "--cleared/--no-cleared"),
    exchange_rate: float | None = typer.Option(None, "--exchange-rate"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """PUT /v1/inbox/{id}.

    Example: expense inbox update <inbox-id> --account-id <id> --category-id <id>
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    payload = build_update_payload(
        {
            "title": title,
            "amount_cents": amount,
            "date": to_canonical_aware(date) if date is not None else None,
            "account_id": account_id,
            "category_id": category_id,
            "description": description,
            "cleared": cleared,
            "exchange_rate": exchange_rate,
        }
    )

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.put(f"/{_RESOURCE}/{id_}", json_body=payload)

    _render_inbox(body, json_mode=json_output)


@app.command("delete")
@handle_errors
def delete(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """DELETE /v1/inbox/{id}. Soft-delete (dismiss the draft); restore is the inverse.

    Example: expense inbox delete <inbox-id> --yes
    """
    require_yes(yes, f"Delete inbox item {id_}?")

    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.delete(f"/{_RESOURCE}/{id_}")

    _render_inbox(body, json_mode=json_output)


@app.command("restore")
@handle_errors
def restore(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """POST /v1/inbox/{id}/restore. Undo a dismissed draft.

    Example: expense inbox restore <inbox-id>
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    with ExpenseClient(cfg, verbose=verbose) as client:
        try:
            body = client.post(f"/{_RESOURCE}/{id_}/restore")
        except EngineError as err:
            if err.status == 409:
                typer.echo(
                    "Hint: This inbox item was already promoted to a ledger transaction. "
                    "Delete the transaction directly to undo (Step 4).",
                    err=True,
                )
            raise

    _render_inbox(body, json_mode=json_output)


@app.command("promote")
@handle_errors
def promote(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """POST /v1/inbox/{id}/promote. Convert the draft into a real ledger transaction.

    Example: expense inbox promote <inbox-id>
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    new_transaction_id = str(uuid4())
    payload = {"id": new_transaction_id}

    with ExpenseClient(cfg, verbose=verbose) as client:
        try:
            body = client.post(f"/{_RESOURCE}/{id_}/promote", json_body=payload)
        except EngineError as err:
            if err.status == 422:
                typer.echo(
                    f"Hint: Inbox item is missing required fields. Fill them in with "
                    f"'expense inbox update {id_} --<field> ...' then promote again.",
                    err=True,
                )
            raise

    if not json_output:
        typer.echo(f"Created transaction: {new_transaction_id}")
    _render_inbox(body, json_mode=json_output)
