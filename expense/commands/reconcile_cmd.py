import json
from uuid import uuid4

import typer

from expense import _editor
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
from expense.context import get_no_cache, get_verbose
from expense.dates import to_canonical_aware
from expense.errors import EngineError, handle_errors
from expense.http import ExpenseClient

app = typer.Typer(help="Reconciliations.", no_args_is_help=True)

_RESOURCE = "reconciliations"

_SOURCE_CHOICES = ("manual", "chained")

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
    no_cache: bool = False,
    verbose: bool = False,
    cold_start_notice: bool = True,
    notice_stream=None,
) -> dict:
    """GET /v1/reconciliations → the raw engine/replica body. Pure data, no render.

    Shared by the flat `reconcile list` command and the TUI's Reconciliations
    screen. Reads the local replica by default (warming it first); `no_cache`
    round-trips the engine. Rows are ordered by `sort_order` (the chain order).
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
        cache_read=lambda: cache_pkg.list_reconciliations(
            account_id=account_id,
            include_deleted=include_deleted,
            limit=limit,
            offset=offset,
        ),
        no_cache=no_cache,
        verbose=verbose,
        cold_start_notice=cold_start_notice,
        notice_stream=notice_stream,
    )


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
            "source": item.get("beginning_balance_source") or "—",
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
            "source": "Source",
            "status": "Status",
            "deleted": "Deleted",
            "id": "Id",
        },
        rows=rows,
        align_right={"begin", "end"},
    )
    render_pagination_hint(body, items)


def _render_reconciliation_detail(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return

    render_record(body, json_mode=False, skip=("transactions",))
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
        "--account-id",
        help="Filter by account_id (sorts the chain by sort_order ASC).",
    ),
    include_deleted: bool = INCLUDE_DELETED_OPT,
    limit: int | None = LIMIT_OPT,
    offset: int | None = OFFSET_OPT,
    json_output: bool = JSON_OPT,
) -> None:
    """GET /v1/reconciliations. Reads from the local replica by default.

    Pass --no-cache (root flag) to round-trip the engine.

    Example: expense reconcile list --account-id <account-id>
    """
    cfg = config_module.ensure_loaded()
    body = fetch_reconciliations(
        cfg,
        account_id=account,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
        no_cache=get_no_cache(ctx),
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
    """GET /v1/reconciliations/{id}. Reads from the local replica by default.

    Pass --no-cache (root flag) to round-trip the engine.

    Example: expense reconcile get <id> --limit 100
    """
    cfg = config_module.ensure_loaded()
    params: dict = {}
    if limit is not None:
        params["limit"] = str(limit)
    if offset is not None:
        params["offset"] = str(offset)
    # Always signed: the replica stores debit_as_negative=true, so the
    # stateless path must match or the two modes disagree on sign.
    params["debit_as_negative"] = "true"
    body = fetch_body(
        cfg,
        path=f"/{_RESOURCE}/{id_}",
        params=params,
        cache_read=lambda: cache_pkg.get_reconciliation(
            id_, embedded_limit=limit, embedded_offset=offset
        ),
        no_cache=get_no_cache(ctx),
        verbose=get_verbose(ctx),
    )
    _render_reconciliation_detail(body, json_mode=json_output)


@app.command("create")
@handle_errors
def create(
    ctx: typer.Context,
    account_id: str = typer.Option(..., "--account-id", help="Owning account UUID."),
    name: str = typer.Option(..., "--name", help="Human-readable label (e.g. 'April 2026')."),
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
    json_output: bool = JSON_OPT,
) -> None:
    """POST /v1/reconciliations. Create a draft reconciliation batch.

    Example: expense reconcile create --account-id <id> --name "April 2026"
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
        cache_after_write(ctx, client, cfg)

    if not json_output:
        typer.echo(f"Created: {new_id}")
    render_record(body, json_mode=json_output, skip=("transactions",))
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
    json_output: bool = JSON_OPT,
) -> None:
    """PUT /v1/reconciliations/{id}. Partial update.

    Example: expense reconcile update <id> --name "March 2026" --ending-balance 12500
    """
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
        cache_after_write(ctx, client, cfg)

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
        cache_after_write(ctx, client, cfg)

    render_record(body, json_mode=json_output, skip=("transactions",))


def _render_after_state_change(body: dict, *, lock_verb: str) -> None:
    render_record(body, json_mode=False, skip=("transactions",))
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
    json_output: bool = JSON_OPT,
) -> None:
    """POST /v1/reconciliations/{id}/restore.

    The restored reconciliation comes back empty — the engine does NOT re-link
    transactions that were unassigned during delete.

    Example: expense reconcile restore <id>
    """

    def _render(body: dict) -> None:
        render_record(body, json_mode=False, skip=("transactions",))
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
        cache_after_write(ctx, client, cfg)

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


# ---------------------------------------------------------------------------
# Reorder helpers (used by move + reorder)
# ---------------------------------------------------------------------------


_CHAIN_PAGE_SIZE = 200


def _fetch_account_chain(client: ExpenseClient, account_id: str) -> list[dict]:
    """Return every active reconciliation for an account in sort_order ASC."""
    items: list[dict] = []
    offset = 0
    while True:
        body = client.get(
            f"/{_RESOURCE}",
            params={
                "account_id": account_id,
                "limit": str(_CHAIN_PAGE_SIZE),
                "offset": str(offset),
            },
        )
        page = items_of(body)
        items.extend(page)
        if not isinstance(body, dict):
            break
        total = body.get("total")
        if not isinstance(total, int) or len(items) >= total or not page:
            break
        offset += len(page)
    return items


def _render_reorder_response(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    items = body.get("reconciliations") or []
    if not items:
        typer.echo("(no reconciliations returned)")
    else:
        typer.echo("Updated:")
        for item in items:
            sort_order = item.get("sort_order", "?")
            name = item.get("name", "(unnamed)")
            recon_id = item.get("id", "?")
            typer.echo(f"  [{sort_order}] {name}  ({recon_id})")
            marker = _format_source_marker(item)
            if marker:
                typer.echo(f"      {marker}")
    recalculated = body.get("recalculated_count")
    if isinstance(recalculated, int):
        typer.echo(f"\n{recalculated} chained beginning balance(s) recalculated.")


@app.command("move")
@handle_errors
def move(
    ctx: typer.Context,
    id_: str = typer.Argument(..., metavar="ID"),
    to: int | None = typer.Option(
        None, "--to", help="1-based slot in the account chain (mutually exclusive)."
    ),
    before: str | None = typer.Option(
        None, "--before", help="UUID of the peer to land before (mutually exclusive)."
    ),
    after: str | None = typer.Option(
        None, "--after", help="UUID of the peer to land after (mutually exclusive)."
    ),
    json_output: bool = JSON_OPT,
) -> None:
    """Reorder a single reconciliation within its account chain.

    Composite: GET /v1/reconciliations/{id} -> GET account chain ->
    PUT /v1/accounts/{account_id}/reconciliations/order with the new ordered_ids.

    Example: expense reconcile move <feb-id> --after <jan-id>
    """
    flags_set = sum(arg is not None for arg in (to, before, after))
    if flags_set == 0:
        raise typer.BadParameter(
            "Pass exactly one of --to, --before, --after.",
            param_hint="--to/--before/--after",
        )
    if flags_set > 1:
        raise typer.BadParameter(
            "--to, --before, --after are mutually exclusive.",
            param_hint="--to/--before/--after",
        )
    if to is not None and to < 1:
        raise typer.BadParameter("Must be >= 1.", param_hint="--to")

    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    with ExpenseClient(cfg, verbose=verbose) as client:
        source = client.get(f"/{_RESOURCE}/{id_}")
        account_id = source.get("account_id")
        if not isinstance(account_id, str):
            raise typer.BadParameter(
                "Source reconciliation has no account_id; cannot reorder.",
                param_hint="ID",
            )

        chain = _fetch_account_chain(client, account_id)
        chain_ids = [item.get("id") for item in chain]
        if id_ not in chain_ids:
            raise typer.BadParameter(
                f"Reconciliation {id_} is not active in account {account_id}.",
                param_hint="ID",
            )

        if to is not None:
            if to > len(chain_ids):
                raise typer.BadParameter(
                    f"--to {to} exceeds chain length {len(chain_ids)}.",
                    param_hint="--to",
                )
            target_index = to - 1
        elif before is not None:
            if before not in chain_ids:
                raise typer.BadParameter(
                    f"--before {before} is not in account {account_id}.",
                    param_hint="--before",
                )
            if before == id_:
                raise typer.BadParameter(
                    "--before cannot reference the source itself.",
                    param_hint="--before",
                )
            target_index = chain_ids.index(before)
        else:
            assert after is not None
            if after not in chain_ids:
                raise typer.BadParameter(
                    f"--after {after} is not in account {account_id}.",
                    param_hint="--after",
                )
            if after == id_:
                raise typer.BadParameter(
                    "--after cannot reference the source itself.",
                    param_hint="--after",
                )
            target_index = chain_ids.index(after) + 1

        current_index = chain_ids.index(id_)
        new_order = list(chain_ids)
        new_order.pop(current_index)
        if current_index < target_index:
            target_index -= 1
        new_order.insert(target_index, id_)

        if new_order == chain_ids:
            if not json_output:
                typer.echo("No changes.")
            return

        body = client.put(
            f"/accounts/{account_id}/reconciliations/order",
            json_body={"ordered_ids": new_order},
        )
        cache_after_write(ctx, client, cfg)

    _render_reorder_response(body, json_mode=json_output)


# ---------------------------------------------------------------------------
# Phase 3b: bulk editor reorder (reconcile reorder)
# ---------------------------------------------------------------------------


_REORDER_EDITOR_HEADER = (
    "# Reorder reconciliations for account {account_id}.\n"
    "# One line per reconciliation, in current order.\n"
    "# Rearrange lines, save, and exit to apply.\n"
    "# Empty the file or exit without changes to abort.\n"
    "# Lines starting with '#' are ignored.\n"
    "\n"
)


def _format_chain_for_editor(chain: list[dict], account_id: str) -> str:
    lines = [_REORDER_EDITOR_HEADER.format(account_id=account_id)]
    for item in chain:
        recon_id = item.get("id", "?")
        date_start = (item.get("date_start") or "")[:10] or "(no start)"
        date_end = (item.get("date_end") or "")[:10] or "(no end)"
        name = item.get("name", "(unnamed)")
        lines.append(f"{recon_id}  {date_start}..{date_end}  {name}\n")
    return "".join(lines)


def _parse_editor_output(text: str) -> list[str]:
    """Strip comments / blank lines; return the first whitespace token of each."""
    ids: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        token = line.split()[0]
        ids.append(token)
    return ids


def _filter_chain_by_year(chain: list[dict], year: int) -> list[dict]:
    prefix = f"{year:04d}-"
    out: list[dict] = []
    for item in chain:
        for field in ("date_start", "date_end"):
            value = item.get(field)
            if isinstance(value, str) and value.startswith(prefix):
                out.append(item)
                break
    return out


@app.command("reorder")
@handle_errors
def reorder(
    ctx: typer.Context,
    account_id: str = typer.Option(..., "--account-id", help="Owning account UUID."),
    year: int | None = typer.Option(
        None,
        "--year",
        help="Scope the editor list to a single year (filters by date_start/date_end).",
    ),
    editor: str | None = typer.Option(
        None,
        "--editor",
        help="Override $EDITOR for this invocation. Default: $EDITOR or 'vi'.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Skip the editor; print the current order as JSON.",
    ),
) -> None:
    """Bulk reorder reconciliations via $EDITOR (git-rebase-i style).

    Fetches the current account chain, opens the user's editor on a temp file
    with one line per reconciliation, parses the saved result, and sends one
    PUT /v1/accounts/{account_id}/reconciliations/order.

    Example: expense reconcile reorder --account-id <id>
    Example: expense reconcile reorder --account-id <id> --year 2025
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    with ExpenseClient(cfg, verbose=verbose) as client:
        chain = _fetch_account_chain(client, account_id)
        if year is not None:
            chain = _filter_chain_by_year(chain, year)
        chain_ids = [item.get("id") for item in chain if isinstance(item.get("id"), str)]

        if not chain_ids:
            typer.echo("(no reconciliations to reorder)")
            return

        if json_output:
            typer.echo(json.dumps({"ordered_ids": chain_ids}, indent=2))
            return

        initial_text = _format_chain_for_editor(chain, account_id)
        edited = _editor.edit_text(initial_text, suffix=".reorder", editor=editor)
        if edited is None:
            typer.echo("Aborted.")
            return

        new_order = _parse_editor_output(edited)

        original_set = set(chain_ids)
        new_set = set(new_order)
        seen: set[str] = set()
        for token in new_order:
            if token in seen:
                raise typer.BadParameter(
                    f"Duplicate id in editor output: {token!r}",
                    param_hint="editor file",
                )
            seen.add(token)
            if token not in original_set:
                raise typer.BadParameter(
                    f"Unknown reconciliation id in editor output: {token!r}",
                    param_hint="editor file",
                )
        missing = original_set - new_set
        if missing:
            raise typer.BadParameter(
                f"Missing ids in editor output: {sorted(missing)}. "
                "This command reorders, it doesn't delete.",
                param_hint="editor file",
            )

        if new_order == chain_ids:
            typer.echo("No changes.")
            return

        body = client.put(
            f"/accounts/{account_id}/reconciliations/order",
            json_body={"ordered_ids": new_order},
        )
        cache_after_write(ctx, client, cfg)

    _render_reorder_response(body, json_mode=False)
