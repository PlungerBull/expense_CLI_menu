import json
import sys
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
from expense.context import get_no_cache, get_verbose
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
    "amount_cents/account_id/title/date are read-only until the reconciliation "
    "is reverted ('expense reconcile revert <id>')."
)
_TRANSFER_GUARD_HINT = (
    "Hint: This transaction is part of a transfer pair. "
    "amount_cents/account_id/date/exchange_rate are read-only on transfer legs — "
    "delete and recreate the transfer to change them. "
    "title/description/cleared/category_id/hashtag_ids remain editable."
)
_BATCH_TRANSFER_HINT = (
    "Hint: transfers are not supported in batch creates. "
    "Log each transfer individually with "
    "'expense log --transfer --to-account-id <id> --to-amount <cents>'."
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
    if "transfer" in haystack and ("pair" in haystack or "leg" in haystack or "guard" in haystack):
        return _TRANSFER_GUARD_HINT
    return None


def _is_batch_transfer_422(err: EngineError) -> bool:
    if err.status != 422:
        return False
    # verified engine shape: fields = {"transactions[i].transfer": "Must not be present in batch."}
    if isinstance(err.fields, dict) and any(key.endswith(".transfer") for key in err.fields):
        return True
    message = (err.message or "").lower()
    return "transfer" in message and "batch" in message


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
    no_cache: bool = False,
    verbose: bool = False,
    cold_start_notice: bool = True,
    notice_stream=None,
) -> dict:
    """GET /v1/transactions → the raw engine/replica body. Pure data, no render.

    Shared by the flat `transactions list` command and the TUI's Transactions
    screen. Reads the local replica by default (warming it first); `no_cache`
    round-trips the engine. `cold_start_notice`/`notice_stream` let a
    non-terminal caller (TUI) silence the stderr sync chatter.
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
    # Always signed: the replica stores debit_as_negative=true, so the
    # stateless path must match or the two modes disagree on sign.
    params["debit_as_negative"] = "true"
    return fetch_body(
        cfg,
        path=f"/{_RESOURCE}",
        params=params,
        cache_read=lambda: cache_pkg.list_transactions(
            account_id=account,
            category_id=category,
            hashtag_id=hashtag,
            reconciliation_id=reconciliation,
            date_from=date_from,
            date_to=date_to,
            cleared=cleared,
            search=search,
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
    """GET /v1/transactions. Reads from the local replica by default.

    Pass --no-cache (root flag) to round-trip the engine. Cached responses
    omit `hashtag_ids` (matches engine list shape; that field is /sync-only).

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
        no_cache=get_no_cache(ctx),
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
    """GET /v1/transactions/{id}. Reads from the local replica by default.

    Pass --no-cache (root flag) to round-trip the engine. Cached responses
    omit `hashtag_ids` (matches engine get shape).

    See a transaction's activity history via
    'expense activity list --resource-type transaction --resource-id <id>'.

    Example: expense transactions get <transaction-id>
    """
    cfg = config_module.ensure_loaded()
    body = fetch_body(
        cfg,
        path=f"/{_RESOURCE}/{id_}",
        params={"debit_as_negative": "true"},
        cache_read=lambda: cache_pkg.get_transaction(id_),
        no_cache=get_no_cache(ctx),
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
    exchange_rate: float | None = typer.Option(None, "--exchange-rate"),
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
            "exchange_rate": exchange_rate,
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
    """DELETE /v1/transactions/{id}. Soft-delete; transfer pairs delete atomically.

    Example: expense transactions delete <transaction-id> --yes
    """
    require_yes(yes, f"Delete transaction {id_}?")

    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.delete(f"/{_RESOURCE}/{id_}")
        cache_after_write(ctx, client, cfg)

    render_record(body, json_mode=json_output)
    if not json_output:
        _print_warnings(body)


@app.command("restore")
@handle_errors
def restore(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = JSON_OPT,
) -> None:
    """POST /v1/transactions/{id}/restore.

    Re-applies balance impact and re-links transfer pair atomically.

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
            elif err.status == 409:
                typer.echo(
                    "Hint: This transaction is part of a transfer pair whose sibling is "
                    "missing or already active. Restore both legs together, or delete the "
                    "remaining sibling.",
                    err=True,
                )
            raise
        cache_after_write(ctx, client, cfg)

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
    """POST /v1/transactions/batch. Atomic multi-create. Transfers not supported in batch.

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
        try:
            body = client.post(f"/{_RESOURCE}/batch", json_body={"transactions": items})
        except EngineError as err:
            if _is_batch_transfer_422(err):
                typer.echo(_BATCH_TRANSFER_HINT, err=True)
            raise
        cache_after_write(ctx, client, cfg)

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
