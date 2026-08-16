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
    format_bool,
    format_cents,
    format_field_value,
    items_of,
    load_account_name_map,
    render_pagination_hint,
    render_record,
    render_table,
    require_yes,
    resolve_name,
    run_toggle,
)
from expense.context import get_verbose
from expense.dates import to_canonical_aware
from expense.errors import EngineError, error_haystack, handle_errors
from expense.http import ExpenseClient

app = typer.Typer(help="Reconciliations.", no_args_is_help=True)

_RESOURCE = "reconciliations"


STATUS_LABELS = {1: "draft", 2: "completed"}


def format_status(value: object) -> str:
    """Human label for the engine's integer status. Shared by flat table + TUI."""
    if value is None:
        return "—"
    return STATUS_LABELS.get(value, str(value))


def format_period(item: dict) -> str:
    """`date_start → date_end` (date parts only). Shared by flat table + TUI."""
    ds = (item.get("date_start") or "")[:10]
    de = (item.get("date_end") or "")[:10]
    if ds and de:
        return f"{ds} → {de}"
    if ds:
        return f"{ds} → …"
    if de:
        return f"… → {de}"
    return "—"


def fetch_reconciliations(
    cfg,
    *,
    account_id: str | None = None,
    include_deleted: bool = False,
    limit: int | None = None,
    offset: int | None = None,
    verbose: bool = False,
) -> dict:
    """GET /v1/reconciliations → the raw engine body. Pure data, no render.

    Shared by the flat `reconcile list` command and the TUI's Reconciliations
    screen. Account-scoped reads come back `date_start ASC NULLS LAST,
    created_at ASC`; the cross-account list stays `created_at DESC`.
    """
    params: dict = {}
    if account_id is not None:
        params["account_id"] = account_id
    if include_deleted:
        params["include_deleted"] = "true"
    if limit is not None:
        params["limit"] = str(limit)
    if offset is not None:
        params["offset"] = str(offset)
    return fetch_body(
        cfg,
        path=f"/{_RESOURCE}",
        params=params,
        verbose=verbose,
    )


def fetch_reconciliation(
    cfg,
    id_: str,
    *,
    limit: int | None = None,
    offset: int | None = None,
    verbose: bool = False,
) -> dict:
    """GET /v1/reconciliations/{id} → the raw engine body. Pure data.

    Shared by the flat `reconcile get` command and the TUI detail screen's
    refresh, which must fetch by id — scanning the collection stops at one
    page and falsely reported later records as deleted (backlog 6.2b).
    Missing record → EngineError(status=404).
    """
    params: dict = {}
    if limit is not None:
        params["limit"] = str(limit)
    if offset is not None:
        params["offset"] = str(offset)
    # Always signed: every CLI/TUI surface renders debits negative, so the
    # request pins the flag rather than depending on the engine default.
    params["debit_as_negative"] = "true"
    return fetch_body(
        cfg,
        path=f"/{_RESOURCE}/{id_}",
        params=params,
        verbose=verbose,
    )


_FIELD_LOCKED_HINT = (
    "Hint: this reconciliation is completed. "
    "Use 'expense reconcile revert <id> --yes' to unlock fields."
)
_DELETE_LOCKED_HINT = (
    "Hint: this reconciliation is completed and cannot be deleted. "
    "Use 'expense reconcile revert <id> --yes' first."
)
_COMPLETE_EMPTY_HINT = (
    "Hint: assign at least one transaction to this reconciliation before completing. "
    "Use 'expense transactions update <tx-id> --reconciliation-id <recon-id>'."
)
_RESTORE_NOTE = (
    "Note: assigned transactions were NOT re-linked. They may have moved to other "
    "batches or been edited. Reassign manually if needed."
)


def _render_reconciliation_list(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    items = items_of(body)
    if not items:
        typer.echo("(no reconciliations)")
        return

    account_names = load_account_name_map()
    rows = [
        {
            "account": resolve_name(item.get("account_id"), account_names),
            "name": item.get("name") or "(unnamed)",
            "period": format_period(item),
            "begin": format_cents(item.get("beginning_balance_cents")),
            "end": format_cents(item.get("ending_balance_cents")),
            "diff": format_cents(item.get("difference_cents")),
            "status": format_status(item.get("status")),
            "deleted": format_bool(item.get("deleted_at")),
            "id": item.get("id") or "—",
        }
        for item in items
    ]
    render_table(
        headers={
            "account": "Account",
            "name": "Name",
            "period": "Period",
            "begin": "Begin",
            "end": "End",
            "diff": "Diff",
            "status": "Status",
            "deleted": "Deleted",
            "id": "Id",
        },
        rows=rows,
        align_right={"begin", "end", "diff"},
    )
    render_pagination_hint(body, items)


def _render_reconciliation_detail(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return

    render_record(body, json_mode=False, skip=("transactions",))

    transactions_total = body.get("transactions_total")
    transactions = body.get("transactions") or []
    typer.echo("")
    typer.echo("Transactions:")
    if transactions_total == 0 or not transactions:
        typer.echo("  (no transactions assigned)")
        recon_id = body.get("id", "<id>")
        typer.echo(
            "  Hint: attach transactions with "
            f"'expense transactions update <tx-id> --reconciliation-id {recon_id}'"
        )
        return

    for index, tx in enumerate(transactions):
        if index > 0:
            typer.echo("")
        for key, value in tx.items():
            typer.echo(f"    {key}: {format_field_value(key, value)}")

    if body.get("transactions_truncated"):
        recon_id = body.get("id", "<id>")
        shown = len(transactions)
        if isinstance(transactions_total, int):
            typer.echo(
                f"\n  ({transactions_total - shown} more transactions; "
                f"use 'expense transactions list --reconciliation-id {recon_id}' for full view)"
            )
        else:
            typer.echo(
                f"\n  (more transactions; use 'expense transactions list "
                f"--reconciliation-id {recon_id}' for full view)"
            )


def _is_field_locked_422(err: EngineError) -> bool:
    if err.status != 422 or not isinstance(err.fields, dict):
        return False
    return any(
        isinstance(message, str) and "locked" in message.lower() for message in err.fields.values()
    )


@app.command("list")
@handle_errors
def list_(
    ctx: typer.Context,
    account: str | None = typer.Option(
        None,
        "--account-id",
        help="Filter by account_id (orders by statement start date, undated last).",
    ),
    include_deleted: bool = INCLUDE_DELETED_OPT,
    limit: int | None = LIMIT_OPT,
    offset: int | None = OFFSET_OPT,
    json_output: bool = JSON_OPT,
) -> None:
    """GET /v1/reconciliations.

    Example: expense reconcile list --account-id <account-id>
    """
    cfg = config_module.ensure_loaded()
    limit = effective_limit(limit, json_mode=json_output)
    body = fetch_reconciliations(
        cfg,
        account_id=account,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
        verbose=get_verbose(ctx),
    )
    _render_reconciliation_list(body, json_mode=json_output)


@app.command("get")
@handle_errors
def get(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    limit: int | None = typer.Option(
        None,
        "--limit",
        help="Max transactions in the embedded window (engine default 50, max 200).",
    ),
    offset: int | None = OFFSET_OPT,
    json_output: bool = JSON_OPT,
) -> None:
    """GET /v1/reconciliations/{id}.

    Example: expense reconcile get <id> --limit 100
    """
    cfg = config_module.ensure_loaded()
    body = fetch_reconciliation(
        cfg,
        id_,
        limit=limit,
        offset=offset,
        verbose=get_verbose(ctx),
    )
    _render_reconciliation_detail(body, json_mode=json_output)


@app.command("create")
@handle_errors
def create(
    ctx: typer.Context,
    account_id: str = typer.Option(..., "--account-id", help="Owning account UUID."),
    name: str = typer.Option(..., "--name", help="Human-readable label (e.g. 'April 2026')."),
    date_start: str = typer.Option(
        ...,
        "--date-start",
        help="Required — the statement's first day; it orders the batch. "
        "YYYY-MM-DD or RFC 3339; naive forms get the local timezone attached.",
    ),
    date_end: str | None = typer.Option(
        None,
        "--date-end",
        help="YYYY-MM-DD or RFC 3339; naive forms get the local timezone attached.",
    ),
    beginning_balance: int = typer.Option(
        ...,
        "--beginning-balance",
        help="Required — signed cents, the statement's opening balance.",
    ),
    ending_balance: int | None = typer.Option(None, "--ending-balance", help="Signed cents."),
    json_output: bool = JSON_OPT,
) -> None:
    """POST /v1/reconciliations. Create a draft reconciliation batch.

    Both balances are typed off the statement — the engine deleted derived
    (chained) beginning balances on 2026-08-06, so `beginning_balance_cents` is
    required. `--date-start` is required too: it is what orders the batch.

    Example: expense reconcile create --account-id <id> --name "April 2026"
             --date-start 2026-04-01 --date-end 2026-04-30
             --beginning-balance 958000 --ending-balance 946000
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    new_id = str(uuid4())
    payload: dict = {
        "id": new_id,
        "account_id": account_id,
        "name": name,
        "date_start": to_canonical_aware(date_start),
        "beginning_balance_cents": beginning_balance,
    }
    if date_end is not None:
        payload["date_end"] = to_canonical_aware(date_end)
    if ending_balance is not None:
        payload["ending_balance_cents"] = ending_balance

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.post(f"/{_RESOURCE}", json_body=payload)
    if not json_output:
        typer.echo(f"Created: {new_id}")
    render_record(body, json_mode=json_output, skip=("transactions",))
    if not json_output:
        typer.echo(
            "\nNext: attach transactions with "
            f"'expense transactions update <tx-id> --reconciliation-id {new_id}'"
        )


@app.command("update")
@handle_errors
def update(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    name: str | None = typer.Option(None, "--name"),
    date_start: str | None = typer.Option(None, "--date-start"),
    date_end: str | None = typer.Option(None, "--date-end"),
    beginning_balance: int | None = typer.Option(None, "--beginning-balance", help="Signed cents."),
    ending_balance: int | None = typer.Option(None, "--ending-balance"),
    json_output: bool = JSON_OPT,
) -> None:
    """PUT /v1/reconciliations/{id}. Partial update.

    `--date-start` is also how you reposition a batch: since the 2026-08-06
    de-chaining, an account's batches are ordered by their statement start date.

    Example: expense reconcile update <id> --name "March 2026" --ending-balance 12500
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    payload = build_update_payload(
        {
            "name": name,
            "date_start": to_canonical_aware(date_start) if date_start is not None else None,
            "date_end": to_canonical_aware(date_end) if date_end is not None else None,
            "beginning_balance_cents": beginning_balance,
            "ending_balance_cents": ending_balance,
        }
    )

    with ExpenseClient(cfg, verbose=verbose) as client:
        try:
            body = client.put(f"/{_RESOURCE}/{id_}", json_body=payload)
        except EngineError as err:
            if _is_field_locked_422(err):
                typer.echo(_FIELD_LOCKED_HINT, err=True)
            raise
    render_record(body, json_mode=json_output, skip=("transactions",))


@app.command("delete")
@handle_errors
def delete(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    yes: bool = YES_OPT,
    json_output: bool = JSON_OPT,
) -> None:
    """DELETE /v1/reconciliations/{id}. Soft-delete; cascade-unassigns attached transactions.

    Only allowed in draft. Completed reconciliations must be reverted first.

    Example: expense reconcile delete <id> --yes
    """
    require_yes(
        yes,
        f"Delete reconciliation {id_}? This cascade-unassigns all attached transactions.",
    )

    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    with ExpenseClient(cfg, verbose=verbose) as client:
        try:
            body = client.delete(f"/{_RESOURCE}/{id_}")
        except EngineError as err:
            if err.status == 409:
                typer.echo(_DELETE_LOCKED_HINT, err=True)
            raise
    render_record(body, json_mode=json_output, skip=("transactions",))


def _render_after_state_change(body: dict, *, lock_verb: str) -> None:
    render_record(body, json_mode=False, skip=("transactions",))
    transactions_total = body.get("transactions_total")
    if isinstance(transactions_total, int):
        typer.echo(f"\n{lock_verb} {transactions_total} transactions.")


@app.command("restore")
@handle_errors
def restore(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = JSON_OPT,
) -> None:
    """POST /v1/reconciliations/{id}/restore.

    The restored reconciliation comes back empty — the engine does NOT re-link
    transactions that were unassigned during delete.

    Example: expense reconcile restore <id>
    """

    def _render(body: dict) -> None:
        render_record(body, json_mode=False, skip=("transactions",))
        typer.echo(f"\n{_RESTORE_NOTE}")

    run_toggle(
        ctx,
        resource=_RESOURCE,
        id_=id_,
        verb="restore",
        json_output=json_output,
        render_human=_render,
    )


@app.command("complete")
@handle_errors
def complete(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = JSON_OPT,
) -> None:
    """POST /v1/reconciliations/{id}/complete.

    Locks amount_cents/account_id/title/date on every assigned transaction and
    locks the reconciliation's own balance/date fields. 422 if no transactions
    are assigned.

    Example: expense reconcile complete <id>
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    with ExpenseClient(cfg, verbose=verbose) as client:
        try:
            body = client.post(f"/{_RESOURCE}/{id_}/complete")
        except EngineError as err:
            if err.status == 422:
                haystack = error_haystack(err)
                if "transaction" in haystack and (
                    "no " in haystack or "empty" in haystack or "at least" in haystack
                ):
                    typer.echo(_COMPLETE_EMPTY_HINT, err=True)
            raise
    if json_output:
        typer.echo(json.dumps(body, indent=2))
    else:
        _render_after_state_change(body, lock_verb="Locked")


@app.command("revert")
@handle_errors
def revert(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    yes: bool = YES_OPT,
    json_output: bool = JSON_OPT,
) -> None:
    """POST /v1/reconciliations/{id}/revert.

    Unlocks all assigned transactions and the reconciliation's own balance/date
    fields. A meaningful audit event — requires --yes.

    Example: expense reconcile revert <id> --yes
    """
    require_yes(
        yes,
        f"Revert reconciliation {id_}? This unlocks all assigned transactions "
        "and is a meaningful audit event.",
    )

    def _render(body: dict) -> None:
        _render_after_state_change(body, lock_verb="Unlocked")

    run_toggle(
        ctx,
        resource=_RESOURCE,
        id_=id_,
        verb="revert",
        json_output=json_output,
        render_human=_render,
    )
