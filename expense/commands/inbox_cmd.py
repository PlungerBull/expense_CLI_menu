import json
from uuid import uuid4

import typer

from expense import cache as cache_pkg
from expense import config as config_module
from expense.commands._resource import (
    INCLUDE_DELETED_OPT,
    JSON_OPT,
    LIMIT_OPT,
    OFFSET_OPT,
    YES_OPT,
    build_update_payload,
    cache_after_write,
    effective_limit,
    fetch_body,
    format_cents,
    format_short_date,
    items_of,
    load_account_name_map,
    load_category_name_map,
    render_pagination_hint,
    render_record,
    render_table,
    require_yes,
    resolve_name,
    truncate,
)
from expense.context import get_no_cache, get_verbose
from expense.dates import to_canonical_aware
from expense.errors import EngineError, handle_errors
from expense.http import ExpenseClient

app = typer.Typer(
    help="Inbox: draft transactions captured before they hit the ledger.",
    no_args_is_help=True,
)

_RESOURCE = "inbox"


_INBOX_STATUS = {1: "pending", 2: "promoted"}


def _fmt_status(value: object) -> str:
    if isinstance(value, int):
        return _INBOX_STATUS.get(value, str(value))
    return "—" if value is None else str(value)


def _render_inbox_list(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    items = items_of(body)
    if not items:
        typer.echo("(no inbox items)")
        return

    accounts = load_account_name_map()
    categories = load_category_name_map()
    rows = [
        {
            "title": truncate(item.get("title") or "—", 24),
            "description": truncate(item.get("description"), 24),
            "amount": format_cents(item.get("amount_cents")),
            "date": format_short_date(item.get("date")),
            "account": resolve_name(item.get("account_id"), accounts),
            "category": resolve_name(item.get("category_id"), categories),
            "status": _fmt_status(item.get("status")),
        }
        for item in items
    ]
    render_table(
        headers={
            "title": "Title",
            "description": "Description",
            "amount": "Amount",
            "date": "Date",
            "account": "Account",
            "category": "Category",
            "status": "Status",
        },
        rows=rows,
        align_right={"amount"},
    )
    render_pagination_hint(body, items)


def fetch_inbox(
    cfg,
    *,
    ready: bool = False,
    overdue: bool = False,
    include_deleted: bool = False,
    limit: int | None = None,
    offset: int | None = None,
    no_cache: bool = False,
    verbose: bool = False,
    cold_start_notice: bool = True,
    notice_stream=None,
) -> dict:
    """GET /v1/inbox → the raw engine/replica body. Pure data, no rendering.

    Shared by the flat `inbox list` command and the TUI's Inbox screen. Reads the
    local replica by default (warming it first); `no_cache` round-trips the
    engine. `cold_start_notice`/`notice_stream` let a non-terminal caller (TUI)
    silence the stderr sync chatter.
    """
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
    # Always signed: the replica stores debit_as_negative=true, so the
    # stateless path must match or the two modes disagree on sign.
    params["debit_as_negative"] = "true"
    return fetch_body(
        cfg,
        path=f"/{_RESOURCE}",
        params=params,
        cache_read=lambda: cache_pkg.list_inbox(
            ready=ready,
            overdue=overdue,
            limit=limit,
            offset=offset,
        ),
        no_cache=no_cache,
        force_live=include_deleted,
        verbose=verbose,
        cold_start_notice=cold_start_notice,
        notice_stream=notice_stream,
    )


@app.command("list")
@handle_errors
def list_(
    ctx: typer.Context,
    ready: bool = typer.Option(False, "--ready", help="Only items ready to promote."),
    include_deleted: bool = INCLUDE_DELETED_OPT,
    overdue: bool = typer.Option(False, "--overdue", help="Only items with date in the past."),
    limit: int | None = LIMIT_OPT,
    offset: int | None = OFFSET_OPT,
    json_output: bool = JSON_OPT,
) -> None:
    """GET /v1/inbox. Reads from the local replica by default.

    Pass --no-cache (root flag) to round-trip the engine.

    Example: expense inbox list --ready
    """
    cfg = config_module.ensure_loaded()
    limit = effective_limit(limit, json_mode=json_output)
    body = fetch_inbox(
        cfg,
        ready=ready,
        overdue=overdue,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
        no_cache=get_no_cache(ctx),
        verbose=get_verbose(ctx),
    )
    _render_inbox_list(body, json_mode=json_output)


@app.command("get")
@handle_errors
def get(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = JSON_OPT,
) -> None:
    """GET /v1/inbox/{id}. Reads from the local replica by default.

    Pass --no-cache (root flag) to round-trip the engine.

    Example: expense inbox get <inbox-id>
    """
    cfg = config_module.ensure_loaded()
    body = fetch_body(
        cfg,
        path=f"/{_RESOURCE}/{id_}",
        params={"debit_as_negative": "true"},
        cache_read=lambda: cache_pkg.get_inbox(id_),
        no_cache=get_no_cache(ctx),
        verbose=get_verbose(ctx),
    )
    render_record(body, json_mode=json_output)


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
    json_output: bool = JSON_OPT,
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
        cache_after_write(ctx, client, cfg)

    if not json_output:
        typer.echo(f"Created: {new_id}")
    render_record(body, json_mode=json_output)


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
    json_output: bool = JSON_OPT,
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
        cache_after_write(ctx, client, cfg)

    render_record(body, json_mode=json_output)


@app.command("delete")
@handle_errors
def delete(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    yes: bool = YES_OPT,
    json_output: bool = JSON_OPT,
) -> None:
    """DELETE /v1/inbox/{id}. Soft-delete (dismiss the draft); restore is the inverse.

    Example: expense inbox delete <inbox-id> --yes
    """
    require_yes(yes, f"Delete inbox item {id_}?")

    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.delete(f"/{_RESOURCE}/{id_}")
        cache_after_write(ctx, client, cfg)

    render_record(body, json_mode=json_output)


@app.command("restore")
@handle_errors
def restore(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = JSON_OPT,
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
                    "Delete the transaction directly to undo.",
                    err=True,
                )
            raise
        cache_after_write(ctx, client, cfg)

    render_record(body, json_mode=json_output)


@app.command("promote")
@handle_errors
def promote(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = JSON_OPT,
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
        cache_after_write(ctx, client, cfg)

    if not json_output:
        typer.echo(f"Created transaction: {new_transaction_id}")
    render_record(body, json_mode=json_output)
