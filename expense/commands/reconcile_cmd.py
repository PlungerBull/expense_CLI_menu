import json
from uuid import uuid4

import typer

from expense import config as config_module
from expense.commands._resource import build_update_payload, require_yes, run_toggle
from expense.context import get_verbose
from expense.dates import to_canonical_aware
from expense.errors import EngineError, handle_errors
from expense.http import ExpenseClient

app = typer.Typer(help="Reconciliations.", no_args_is_help=True)

_RESOURCE = "reconciliations"

_SOURCE_CHOICES = ("manual", "chained")

_CHAINED_AMBIGUITY_HINT = (
    "Hint: --source chained cannot be combined with --beginning-balance.\n"
    "Chained mode derives the value from the previous reconciliation.\n"
    "Try one of:\n"
    "  --source chained                            # let engine derive\n"
    "  --source manual --beginning-balance <cents> # set explicit value"
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


def _format_source_marker(item: dict) -> str:
    source = item.get("beginning_balance_source")
    if source == "chained":
        upstream = item.get("chained_from_reconciliation_id")
        if upstream:
            return f"[chained from {upstream}]"
        return "[chained, no upstream]"
    if source == "manual":
        return "[manual]"
    return ""


def _render_reconciliation(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    for key, value in body.items():
        if key == "transactions":
            continue
        display = value if value is not None else "(null)"
        typer.echo(f"  {key}: {display}")


def _render_reconciliation_list(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    items = body.get("items", body) if isinstance(body, dict) else body
    if not items:
        typer.echo("(no reconciliations)")
        return
    for index, item in enumerate(items):
        if index > 0:
            typer.echo("")
        for key, value in item.items():
            display = value if value is not None else "(null)"
            typer.echo(f"  {key}: {display}")
        marker = _format_source_marker(item)
        if marker:
            typer.echo(f"  {marker}")

    if isinstance(body, dict):
        total = body.get("total")
        limit = body.get("limit")
        offset = body.get("offset")
        if (
            isinstance(total, int)
            and isinstance(limit, int)
            and isinstance(offset, int)
            and offset + len(items) < total
        ):
            next_offset = offset + len(items)
            typer.echo(
                f"\n(showing {len(items)} of {total}; "
                f"pass --offset {next_offset} --limit {limit} for more)"
            )


def _render_reconciliation_detail(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return

    _render_reconciliation(body, json_mode=False)
    marker = _format_source_marker(body)
    if marker:
        typer.echo(f"  {marker}")

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
            display = value if value is not None else "(null)"
            typer.echo(f"    {key}: {display}")

    if body.get("transactions_truncated"):
        recon_id = body.get("id", "<id>")
        shown = len(transactions)
        if isinstance(transactions_total, int):
            typer.echo(
                f"\n  ({transactions_total - shown} more transactions; "
                f"use 'expense transactions list --reconciliation {recon_id}' for full view)"
            )
        else:
            typer.echo(
                f"\n  (more transactions; use 'expense transactions list "
                f"--reconciliation {recon_id}' for full view)"
            )


def _is_chained_ambiguity_422(err: EngineError) -> bool:
    if err.status != 422 or not isinstance(err.fields, dict):
        return False
    return "beginning_balance_cents" in err.fields and "beginning_balance_source" in err.fields


def _is_field_locked_422(err: EngineError) -> bool:
    if err.status != 422 or not isinstance(err.fields, dict):
        return False
    return any(
        isinstance(message, str) and "locked" in message.lower() for message in err.fields.values()
    )


def _validate_source_choice(value: str | None) -> str | None:
    if value is None:
        return None
    if value not in _SOURCE_CHOICES:
        raise typer.BadParameter(
            f"Invalid value {value!r}. Choose one of: {', '.join(_SOURCE_CHOICES)}.",
            param_hint="--source",
        )
    return value


@app.command("list")
@handle_errors
def list_(
    ctx: typer.Context,
    account: str | None = typer.Option(
        None,
        "--account",
        help="Filter by account_id (sorts the chain by sort_order ASC).",
    ),
    include_deleted: bool = typer.Option(False, "--include-deleted"),
    limit: int | None = typer.Option(None, "--limit"),
    offset: int | None = typer.Option(None, "--offset"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """GET /v1/reconciliations.

    Example: expense reconcile list --account chase-checking
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    params: dict = {}
    if account is not None:
        params["account_id"] = account
    if include_deleted:
        params["include_deleted"] = "true"
    if limit is not None:
        params["limit"] = str(limit)
    if offset is not None:
        params["offset"] = str(offset)

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.get(f"/{_RESOURCE}", params=params or None)

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
    offset: int | None = typer.Option(None, "--offset"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """GET /v1/reconciliations/{id}.

    Example: expense reconcile get <id> --limit 100
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    params: dict = {}
    if limit is not None:
        params["limit"] = str(limit)
    if offset is not None:
        params["offset"] = str(offset)

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.get(f"/{_RESOURCE}/{id_}", params=params or None)

    _render_reconciliation_detail(body, json_mode=json_output)


@app.command("create")
@handle_errors
def create(
    ctx: typer.Context,
    account_id: str = typer.Option(..., "--account", help="Owning account UUID."),
    name: str = typer.Option(..., "--name"),
    date_start: str | None = typer.Option(
        None,
        "--date-start",
        help="YYYY-MM-DD or RFC 3339; naive forms get the local timezone attached.",
    ),
    date_end: str | None = typer.Option(
        None,
        "--date-end",
        help="YYYY-MM-DD or RFC 3339; naive forms get the local timezone attached.",
    ),
    beginning_balance: int | None = typer.Option(
        None,
        "--beginning-balance",
        help="Signed cents. Omit to chain from the previous reconciliation in this account.",
    ),
    ending_balance: int | None = typer.Option(None, "--ending-balance", help="Signed cents."),
    source: str | None = typer.Option(
        None,
        "--source",
        help="manual | chained. Mutually exclusive with --beginning-balance for 'chained'.",
    ),
    sort_order: int | None = typer.Option(
        None,
        "--sort-order",
        help="1-based slot in the account chain. Omit to append at the end.",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """POST /v1/reconciliations. Create a draft reconciliation batch.

    Example: expense reconcile create --account <id> --name "April 2026"
             --date-start 2026-04-01 --date-end 2026-04-30 --ending-balance 12345600
    """
    source = _validate_source_choice(source)
    if source == "chained" and beginning_balance is not None:
        raise typer.BadParameter(
            _CHAINED_AMBIGUITY_HINT,
            param_hint="--source/--beginning-balance",
        )

    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    new_id = str(uuid4())
    payload: dict = {
        "id": new_id,
        "account_id": account_id,
        "name": name,
    }
    if date_start is not None:
        payload["date_start"] = to_canonical_aware(date_start)
    if date_end is not None:
        payload["date_end"] = to_canonical_aware(date_end)
    if beginning_balance is not None:
        payload["beginning_balance_cents"] = beginning_balance
    if ending_balance is not None:
        payload["ending_balance_cents"] = ending_balance
    if source is not None:
        payload["beginning_balance_source"] = source
    if sort_order is not None:
        payload["sort_order"] = sort_order

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.post(f"/{_RESOURCE}", json_body=payload)

    if not json_output:
        typer.echo(f"Created: {new_id}")
    _render_reconciliation(body, json_mode=json_output)
    if not json_output:
        marker = _format_source_marker(body)
        if marker:
            typer.echo(f"  {marker}")
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
    beginning_balance: int | None = typer.Option(
        None, "--beginning-balance", help="Signed cents. Implicitly switches source to 'manual'."
    ),
    ending_balance: int | None = typer.Option(None, "--ending-balance"),
    source: str | None = typer.Option(
        None,
        "--source",
        help="manual | chained. Mutually exclusive with --beginning-balance for 'chained'.",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """PUT /v1/reconciliations/{id}. Partial update."""
    source = _validate_source_choice(source)
    if source == "chained" and beginning_balance is not None:
        raise typer.BadParameter(
            _CHAINED_AMBIGUITY_HINT,
            param_hint="--source/--beginning-balance",
        )

    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    payload = build_update_payload(
        {
            "name": name,
            "date_start": to_canonical_aware(date_start) if date_start is not None else None,
            "date_end": to_canonical_aware(date_end) if date_end is not None else None,
            "beginning_balance_cents": beginning_balance,
            "ending_balance_cents": ending_balance,
            "beginning_balance_source": source,
        }
    )

    with ExpenseClient(cfg, verbose=verbose) as client:
        try:
            body = client.put(f"/{_RESOURCE}/{id_}", json_body=payload)
        except EngineError as err:
            if _is_chained_ambiguity_422(err):
                typer.echo(_CHAINED_AMBIGUITY_HINT, err=True)
            elif _is_field_locked_422(err):
                typer.echo(_FIELD_LOCKED_HINT, err=True)
            raise

    _render_reconciliation(body, json_mode=json_output)


@app.command("delete")
@handle_errors
def delete(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """DELETE /v1/reconciliations/{id}. Soft-delete; cascade-unassigns attached transactions.

    Only allowed in draft. Completed reconciliations must be reverted first.
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

    _render_reconciliation(body, json_mode=json_output)


def _render_after_state_change(body: dict, *, lock_verb: str) -> None:
    _render_reconciliation(body, json_mode=False)
    marker = _format_source_marker(body)
    if marker:
        typer.echo(f"  {marker}")
    transactions_total = body.get("transactions_total")
    if isinstance(transactions_total, int):
        typer.echo(f"\n{lock_verb} {transactions_total} transactions.")


@app.command("restore")
@handle_errors
def restore(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """POST /v1/reconciliations/{id}/restore.

    The restored reconciliation comes back empty — the engine does NOT re-link
    transactions that were unassigned during delete.
    """

    def _render(body: dict) -> None:
        _render_reconciliation(body, json_mode=False)
        marker = _format_source_marker(body)
        if marker:
            typer.echo(f"  {marker}")
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
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """POST /v1/reconciliations/{id}/complete.

    Locks amount_cents/account_id/title/date on every assigned transaction and
    locks the reconciliation's own balance/date fields. 422 if no transactions
    are assigned.
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    with ExpenseClient(cfg, verbose=verbose) as client:
        try:
            body = client.post(f"/{_RESOURCE}/{id_}/complete")
        except EngineError as err:
            if err.status == 422:
                haystack = (err.message or "").lower()
                if isinstance(err.fields, dict):
                    haystack += (
                        " "
                        + " ".join(
                            f"{k} {v}" for k, v in err.fields.items() if isinstance(v, str)
                        ).lower()
                    )
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
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """POST /v1/reconciliations/{id}/revert.

    Unlocks all assigned transactions and the reconciliation's own balance/date
    fields. A meaningful audit event — requires --yes.
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
