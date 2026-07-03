import json
import sys
from uuid import uuid4

import typer

from expense import cache as cache_pkg
from expense import config as config_module
from expense.commands._resource import (
    build_update_payload,
    cache_after_write,
    format_cents,
    format_field_value,
    format_short_date,
    load_account_name_map,
    load_category_name_map,
    render_pagination_hint,
    render_table,
    require_yes,
    resolve_name,
    truncate,
)
from expense.commands.dashboard_cmd import load_hashtag_name_map
from expense.context import get_no_cache, get_verbose
from expense.dates import to_canonical_aware
from expense.errors import EngineError, handle_errors
from expense.http import ExpenseClient

app = typer.Typer(
    help="Ledger transactions: list, view, edit, delete, restore, batch.",
    no_args_is_help=True,
)

_RESOURCE = "transactions"

_RECONCILIATION_LOCK_HINT = (
    "Hint: This transaction is in a completed reconciliation. "
    "amount_cents/account_id/title/date are read-only until the reconciliation "
    "is reverted (Step 6: 'expense reconcile revert <id>')."
)
_TRANSFER_GUARD_HINT = (
    "Hint: This transaction is part of a transfer pair. "
    "amount_cents/account_id/date/exchange_rate are read-only on transfer legs — "
    "delete and recreate the transfer to change them. "
    "title/description/cleared/category_id/hashtag_ids remain editable."
)


def _render_transaction(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    for key, value in body.items():
        typer.echo(f"  {key}: {format_field_value(key, value)}")


def _fmt_amount(value: object) -> str:
    return format_cents(value)


def _fmt_hashtag_cell(ids: object, name_map: dict[str, str]) -> str:
    if not isinstance(ids, list) or not ids:
        return "—"
    names = [name_map.get(hid, hid[:8] + "…") if isinstance(hid, str) else "?" for hid in ids]
    return truncate(", ".join(names), 24)


def _render_transaction_list(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    items = body.get("items", body) if isinstance(body, dict) else body
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
            "amount": _fmt_amount(item.get("amount_cents")),
            "date": format_short_date(item.get("date")),
            "account": resolve_name(item.get("account_id"), accounts),
            "category": resolve_name(item.get("category_id"), categories),
            "hashtags": _fmt_hashtag_cell(item.get("hashtag_ids"), hashtags),
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
    haystack = (err.message or "").lower()
    if isinstance(err.fields, dict):
        haystack += (
            " " + " ".join(f"{k} {v}" for k, v in err.fields.items() if isinstance(v, str)).lower()
        )

    if "reconciliation" in haystack and (
        "complete" in haystack or "lock" in haystack or "read-only" in haystack
    ):
        return _RECONCILIATION_LOCK_HINT
    if "transfer" in haystack and ("pair" in haystack or "leg" in haystack or "guard" in haystack):
        return _TRANSFER_GUARD_HINT
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
    if no_cache:
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
        with ExpenseClient(cfg, verbose=verbose) as client:
            return client.get(f"/{_RESOURCE}", params=params)

    with ExpenseClient(cfg, verbose=verbose, cold_start_notice=cold_start_notice) as client:
        cache_pkg.ensure_synced(client, cfg, notice_stream=notice_stream)
    return cache_pkg.list_transactions(
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
    cleared: bool | None = typer.Option(None, "--cleared/--no-cleared"),
    search: str | None = typer.Option(
        None, "--search", help="Full-text search on title/description."
    ),
    limit: int | None = typer.Option(None, "--limit"),
    offset: int | None = typer.Option(None, "--offset"),
    include_deleted: bool = typer.Option(False, "--include-deleted"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """GET /v1/transactions. Reads from the local replica by default.

    Pass --no-cache (root flag) to round-trip the engine. Cached responses
    omit `hashtag_ids` (matches engine list shape; that field is /sync-only).

    Example: expense transactions list --account-id <id> --from 2026-04-01 --to 2026-04-30
    """
    cfg = config_module.ensure_loaded()
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
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """GET /v1/transactions/{id}. Reads from the local replica by default.

    Pass --no-cache (root flag) to round-trip the engine. Cached responses
    omit `hashtag_ids` (matches engine get shape).

    Activity-log entries for a transaction will be reachable via
    'expense activity list --resource-type expense_transactions --resource-id <id>'
    once Step 8 ships.

    Example: expense transactions get <transaction-id>
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)
    no_cache = get_no_cache(ctx)

    if no_cache:
        params: dict = {"debit_as_negative": "true"}
        with ExpenseClient(cfg, verbose=verbose) as client:
            body = client.get(f"/{_RESOURCE}/{id_}", params=params)
    else:
        with ExpenseClient(cfg, verbose=verbose, cold_start_notice=True) as client:
            cache_pkg.ensure_synced(client, cfg)
        body = cache_pkg.get_transaction(id_)

    _render_transaction(body, json_mode=json_output)


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
    cleared: bool | None = typer.Option(None, "--cleared/--no-cleared"),
    exchange_rate: float | None = typer.Option(None, "--exchange-rate"),
    hashtag_ids: str | None = typer.Option(
        None, "--hashtag-ids", help="Comma-separated list; replaces the existing set."
    ),
    reconciliation_id: str | None = typer.Option(None, "--reconciliation-id"),
    json_output: bool = typer.Option(False, "--json"),
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

    _render_transaction(body, json_mode=json_output)


@app.command("delete")
@handle_errors
def delete(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    json_output: bool = typer.Option(False, "--json"),
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

    _render_transaction(body, json_mode=json_output)
    if not json_output:
        _print_warnings(body)


@app.command("restore")
@handle_errors
def restore(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = typer.Option(False, "--json"),
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

    _render_transaction(body, json_mode=json_output)
    if not json_output:
        _print_warnings(body)


@app.command("batch")
@handle_errors
def batch(
    ctx: typer.Context,
    file: str | None = typer.Option(
        None, "--file", help="Path to a JSON array of transactions. Defaults to stdin."
    ),
    json_output: bool = typer.Option(False, "--json"),
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
        if "transfer" in item:
            typer.echo(
                f"Error: items[{index}] has a 'transfer' field. "
                "Transfers are not supported in batch creates — "
                "use 'expense log --transfer' instead.",
                err=True,
            )
            raise typer.Exit(code=1)
        if "id" not in item:
            item["id"] = str(uuid4())

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.post(f"/{_RESOURCE}/batch", json_body={"transactions": items})
        cache_after_write(ctx, client, cfg)

    if not json_output:
        created_items = body.get("created", []) if isinstance(body, dict) else []
        for item in created_items:
            if isinstance(item, dict) and "id" in item:
                typer.echo(f"Created: {item['id']}")
    _render_transaction(body, json_mode=json_output)


__all__ = ["app"]
