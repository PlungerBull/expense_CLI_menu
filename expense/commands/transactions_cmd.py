import json
import sys
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
    effective_limit,
    fetch_body,
    format_cents,
    format_hashtag_cell,
    format_short_date,
    items_of,
    load_account_name_map,
    load_category_name_map,
    load_hashtag_name_map,
    render_pagination_hint,
    render_record,
    render_table,
    require_yes,
    resolve_name,
    truncate,
)
from expense.context import get_verbose
from expense.dates import to_canonical_aware
from expense.errors import EngineError, error_haystack, handle_errors
from expense.http import ExpenseClient

app = typer.Typer(
    help="Ledger transactions: list, view, edit, delete, restore, batch.",
    no_args_is_help=True,
)

_RESOURCE = "transactions"

_RECONCILIATION_LOCK_HINT = (
    "Hint: This transaction is in a completed reconciliation. "
    "amount_cents/account_id/title/date/reconciliation_id are read-only — "
    "revert the reconciliation to draft first ('expense reconcile revert <id>')."
)


def _render_transaction_list(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    items = items_of(body)
    if not items:
        typer.echo("(no transactions)")
        return

    accounts = load_account_name_map()
    categories = load_category_name_map()
    hashtags = load_hashtag_name_map()
    rows = [
        {
            "title": truncate(item.get("title") or "—", 24),
            "description": truncate(item.get("description"), 24),
            "amount": format_cents(item.get("amount_cents")),
            "date": format_short_date(item.get("date")),
            "account": resolve_name(item.get("account_id"), accounts),
            "category": resolve_name(item.get("category_id"), categories),
            "hashtags": format_hashtag_cell(item.get("hashtag_ids"), hashtags, max_width=24),
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
            "hashtags": "Hashtags",
        },
        rows=rows,
        align_right={"amount"},
    )
    render_pagination_hint(body, items)


def _print_warnings(body: dict) -> None:
    warnings = body.get("warnings") if isinstance(body, dict) else None
    if isinstance(warnings, list):
        for warning in warnings:
            typer.echo(f"Warning: {warning}", err=True)


def _update_hint_for(err: EngineError) -> str | None:
    haystack = error_haystack(err)
    if "reconciliation" in haystack and (
        "complete" in haystack or "lock" in haystack or "read-only" in haystack
    ):
        return _RECONCILIATION_LOCK_HINT
    return None


def _parse_hashtag_ids(raw: str) -> list[str]:
    return [piece.strip() for piece in raw.split(",") if piece.strip()]


def fetch_transactions(
    cfg,
    *,
    account: str | None = None,
    category: str | None = None,
    hashtag: str | None = None,
    reconciliation: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    cleared: bool | None = None,
    search: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    include_deleted: bool = False,
    verbose: bool = False,
) -> dict:
    """GET /v1/transactions → the raw engine body. Pure data, no render.

    Shared by the flat `transactions list` command and the TUI's Transactions
    screen.
    """
    params: dict = {}
    if account is not None:
        params["account_id"] = account
    if category is not None:
        params["category_id"] = category
    if hashtag is not None:
        params["hashtag_id"] = hashtag
    if reconciliation is not None:
        params["reconciliation_id"] = reconciliation
    if date_from is not None:
        params["date_from"] = date_from
    if date_to is not None:
        params["date_to"] = date_to
    if cleared is not None:
        params["cleared"] = "true" if cleared else "false"
    if search is not None:
        params["search"] = search
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    if include_deleted:
        params["include_deleted"] = "true"
    # Always signed: every CLI/TUI surface renders debits negative, so the
    # request pins the flag rather than depending on the engine default.
    params["debit_as_negative"] = "true"
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
    account: str | None = typer.Option(None, "--account-id", help="Filter by account_id."),
    category: str | None = typer.Option(None, "--category-id", help="Filter by category_id."),
    hashtag: str | None = typer.Option(None, "--hashtag-id", help="Filter by hashtag_id."),
    reconciliation: str | None = typer.Option(
        None, "--reconciliation-id", help="Filter by reconciliation_id."
    ),
    date_from: str | None = typer.Option(None, "--from", help="ISO 8601 lower bound (inclusive)."),
    date_to: str | None = typer.Option(None, "--to", help="ISO 8601 upper bound (inclusive)."),
    cleared: bool | None = typer.Option(
        None, "--cleared/--no-cleared", help="Filter by cleared status."
    ),
    search: str | None = typer.Option(
        None, "--search", help="Full-text search on title/description."
    ),
    limit: int | None = LIMIT_OPT,
    offset: int | None = OFFSET_OPT,
    include_deleted: bool = INCLUDE_DELETED_OPT,
    json_output: bool = JSON_OPT,
) -> None:
    """GET /v1/transactions.

    Example: expense transactions list --account-id <id> --from 2026-04-01 --to 2026-04-30
    """
    cfg = config_module.ensure_loaded()
    limit = effective_limit(limit, json_mode=json_output)
    body = fetch_transactions(
        cfg,
        account=account,
        category=category,
        hashtag=hashtag,
        reconciliation=reconciliation,
        date_from=date_from,
        date_to=date_to,
        cleared=cleared,
        search=search,
        limit=limit,
        offset=offset,
        include_deleted=include_deleted,
        verbose=get_verbose(ctx),
    )
    _render_transaction_list(body, json_mode=json_output)


@app.command("get")
@handle_errors
def get(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = JSON_OPT,
) -> None:
    """GET /v1/transactions/{id}.

    See a transaction's activity history via
    'expense activity list --resource-type transaction --resource-id <id>'.

    Example: expense transactions get <transaction-id>
    """
    cfg = config_module.ensure_loaded()
    body = fetch_body(
        cfg,
        path=f"/{_RESOURCE}/{id_}",
        params={"debit_as_negative": "true"},
        verbose=get_verbose(ctx),
    )
    render_record(body, json_mode=json_output)


@app.command("update")
@handle_errors
def update(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    title: str | None = typer.Option(None, "--title"),
    amount: int | None = typer.Option(None, "--amount", help="Signed cents."),
    date: str | None = typer.Option(None, "--date"),
    account_id: str | None = typer.Option(None, "--account-id"),
    category_id: str | None = typer.Option(None, "--category-id"),
    description: str | None = typer.Option(None, "--description"),
    cleared: bool | None = typer.Option(
        None, "--cleared/--no-cleared", help="Set the cleared status."
    ),
    hashtag_ids: str | None = typer.Option(
        None, "--hashtag-ids", help="Comma-separated list; replaces the existing set."
    ),
    reconciliation_id: str | None = typer.Option(None, "--reconciliation-id"),
    json_output: bool = JSON_OPT,
) -> None:
    """PUT /v1/transactions/{id}. Partial update.

    Example: expense transactions update <transaction-id> --title "Renamed" --cleared
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
            "hashtag_ids": _parse_hashtag_ids(hashtag_ids) if hashtag_ids is not None else None,
            "reconciliation_id": reconciliation_id,
        }
    )

    with ExpenseClient(cfg, verbose=verbose) as client:
        try:
            body = client.put(f"/{_RESOURCE}/{id_}", json_body=payload)
        except EngineError as err:
            if err.status == 422:
                hint = _update_hint_for(err)
                if hint is not None:
                    typer.echo(hint, err=True)
            raise
    render_record(body, json_mode=json_output)


@app.command("delete")
@handle_errors
def delete(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    yes: bool = YES_OPT,
    json_output: bool = JSON_OPT,
) -> None:
    """DELETE /v1/transactions/{id}. Soft-delete.

    Example: expense transactions delete <transaction-id> --yes
    """
    require_yes(yes, f"Delete transaction {id_}?")

    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    with ExpenseClient(cfg, verbose=verbose) as client:
        try:
            body = client.delete(f"/{_RESOURCE}/{id_}")
        except EngineError as err:
            if err.status == 409:
                typer.echo(
                    "Hint: This transaction is assigned to a completed reconciliation "
                    "and cannot be deleted — revert the reconciliation to draft first "
                    "('expense reconcile revert <id>').",
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
    """POST /v1/transactions/{id}/restore.

    Re-applies the balance impact.

    Example: expense transactions restore <transaction-id>
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    with ExpenseClient(cfg, verbose=verbose) as client:
        try:
            body = client.post(f"/{_RESOURCE}/{id_}/restore")
        except EngineError as err:
            if err.status == 422:
                typer.echo(
                    "Hint: An account, category, or hashtag referenced by this transaction "
                    "is no longer active. Unarchive or restore the offending row, then retry.",
                    err=True,
                )
            raise
    render_record(body, json_mode=json_output)
    if not json_output:
        _print_warnings(body)


@app.command("batch")
@handle_errors
def batch(
    ctx: typer.Context,
    file: str | None = typer.Option(
        None, "--file", help="Path to a JSON array of transactions. Defaults to stdin."
    ),
    json_output: bool = JSON_OPT,
) -> None:
    """POST /v1/transactions/batch. Atomic multi-create.

    Example: cat transactions.json | expense transactions batch
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    if file is not None:
        with open(file, encoding="utf-8") as handle:
            raw = handle.read()
    else:
        raw = sys.stdin.read()

    if not raw.strip():
        typer.echo("Error: No input. Pipe a JSON array to stdin or pass --file.", err=True)
        raise typer.Exit(code=1)

    try:
        items = json.loads(raw)
    except json.JSONDecodeError as exc:
        typer.echo(f"Error: Invalid JSON input: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not isinstance(items, list) or not items:
        typer.echo("Error: Input must be a non-empty JSON array of transaction objects.", err=True)
        raise typer.Exit(code=1)

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            typer.echo(f"Error: items[{index}] is not an object.", err=True)
            raise typer.Exit(code=1)
        if "id" not in item:
            item["id"] = str(uuid4())

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.post(f"/{_RESOURCE}/batch", json_body={"transactions": items})
    if json_output:
        typer.echo(json.dumps(body, indent=2))
        return

    created_items = body.get("created", []) if isinstance(body, dict) else []
    for item in created_items:
        if isinstance(item, dict) and "id" in item:
            typer.echo(f"Created: {item['id']}")
    count = len(created_items)
    typer.echo(f"Created {count} transaction{'s' if count != 1 else ''}.")


__all__ = ["app"]
