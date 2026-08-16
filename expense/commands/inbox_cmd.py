import json
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
    parse_hashtag_ids,
    render_pagination_hint,
    render_record,
    render_table,
    require_yes,
    resolve_name,
    truncate,
)
from expense.context import get_verbose
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
    hashtags = load_hashtag_name_map()
    rows = [
        {
            "title": truncate(item.get("title") or "—", 24),
            "description": truncate(item.get("description"), 24),
            "amount": format_cents(item.get("amount_cents")),
            "date": format_short_date(item.get("date")),
            "account": resolve_name(item.get("account_id"), accounts),
            "category": resolve_name(item.get("category_id"), categories),
            "status": _fmt_status(item.get("status")),
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
            "status": "Status",
            # Tags last, matching `transactions list` (backlog 6.1, sketch pick E).
            "hashtags": "Tags",
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
    verbose: bool = False,
) -> dict:
    """GET /v1/inbox → the raw engine body. Pure data, no rendering.

    Shared by the flat `inbox list` command and the TUI's Inbox screen.
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
    ready: bool = typer.Option(False, "--ready", help="Only items ready to promote."),
    include_deleted: bool = INCLUDE_DELETED_OPT,
    overdue: bool = typer.Option(False, "--overdue", help="Only items with date in the past."),
    limit: int | None = LIMIT_OPT,
    offset: int | None = OFFSET_OPT,
    json_output: bool = JSON_OPT,
) -> None:
    """GET /v1/inbox.

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
    """GET /v1/inbox/{id}.

    Example: expense inbox get <inbox-id>
    """
    cfg = config_module.ensure_loaded()
    body = fetch_body(
        cfg,
        path=f"/{_RESOURCE}/{id_}",
        params={"debit_as_negative": "true"},
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
    hashtag_ids: str | None = typer.Option(
        None,
        "--hashtag-ids",
        help="Comma-separated hashtag UUIDs to attach at creation. "
        "Engine rejects archived ids with 422.",
    ),
    json_output: bool = JSON_OPT,
) -> None:
    """POST /v1/inbox. Drop a partial draft into the inbox; fill in later, then promote.

    Tags survive promotion — `expense inbox promote` returns a transaction carrying
    the draft's `hashtag_ids`, so there is nothing to re-attach afterwards.

    No --cleared. `expense_transaction_inbox` has no `cleared` column and never has;
    the inbox write models are strict and accept exactly seven fields (id on create,
    title, description, amount_cents, date, account_id, category_id, hashtag_ids), so
    anything else is a 422 on the unknown field — losing the whole draft, not just
    the flag. `cleared` is a per-row boolean on a *transaction*, written only by the
    caller; promote hardcodes it false, so set it afterwards if you want it.
    (Removed 2026-08-16, backlog Phase 5 — found by the contract gate; inbox scope
    confirmed by the engine author the same day.)

    Example: expense inbox add --title "Lunch" --amount -1500 --hashtag-ids <id>,<id>
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
    if hashtag_ids is not None:
        payload["hashtag_ids"] = parse_hashtag_ids(hashtag_ids)

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.post(f"/{_RESOURCE}", json_body=payload)
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
    hashtag_ids: str | None = typer.Option(
        None, "--hashtag-ids", help="Comma-separated list; replaces the existing set."
    ),
    json_output: bool = JSON_OPT,
) -> None:
    """PUT /v1/inbox/{id}.

    No --cleared — see `add`; the inbox table has no such column.

    `--hashtag-ids` is a replacement, matching `transactions update`: omit the flag
    to leave the tags alone, pass a list to become the whole set, pass "" to clear.
    Never sends an explicit null — the engine 422s that on every inbox field.

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
            "hashtag_ids": parse_hashtag_ids(hashtag_ids) if hashtag_ids is not None else None,
        }
    )

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
    """DELETE /v1/inbox/{id}. Dismiss the draft — final; there is no restore.

    The dismiss is still a soft-delete engine-side (`--include-deleted` lists
    it), but the restore route was removed 2026-08-14, so this confirmation
    is the only safety net.

    Example: expense inbox delete <inbox-id> --yes
    """
    require_yes(yes, f"Delete inbox item {id_}? Dismissal is final — there is no restore.")

    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.delete(f"/{_RESOURCE}/{id_}")
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
    if not json_output:
        typer.echo(f"Created transaction: {new_transaction_id}")
    render_record(body, json_mode=json_output)
