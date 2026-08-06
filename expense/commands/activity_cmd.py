import json

import typer

from expense import config as config_module
from expense.commands._resource import (
    JSON_OPT,
    LIMIT_OPT,
    OFFSET_OPT,
    effective_limit,
    items_of,
    render_pagination_hint,
    render_table,
)
from expense.context import get_verbose
from expense.errors import EngineError, handle_errors
from expense.http import ExpenseClient

app = typer.Typer(help="Activity log (audit trail).", no_args_is_help=True)

_RESOURCE = "activity"

_ACTION_NAMES = {1: "CREATED", 2: "UPDATED", 3: "DELETED", 4: "RESTORED"}


def _action_label(action: object) -> str:
    if isinstance(action, int) and action in _ACTION_NAMES:
        return _ACTION_NAMES[action]
    return str(action)


def _split_date_time(created_at: object) -> tuple[str, str]:
    if not isinstance(created_at, str) or len(created_at) < 19:
        return "—", "—"
    return created_at[:10], created_at[11:19]


def _short_id(resource_id: object) -> str:
    if not isinstance(resource_id, str) or not resource_id:
        return "—"
    return resource_id[:8]


# The engine writes activity `resource_type` in the singular ("transaction",
# "account", …). Map both the engine's actual strings and the older plural
# guesses to the resource's collection path so name resolution is robust to
# either.
_RESOURCE_PATH = {
    "transaction": "transactions",
    "expense_transactions": "transactions",
    "account": "accounts",
    "accounts": "accounts",
    "category": "categories",
    "categories": "categories",
    "hashtag": "hashtags",
    "hashtags": "hashtags",
    "inbox": "inbox",
    "inbox_items": "inbox",
    "reconciliation": "reconciliations",
    "reconciliations": "reconciliations",
}


def _display_name(path: str, row: dict, resource_id: str, client: ExpenseClient) -> str:
    """The human handle for one fetched row, per resource kind."""
    if path in ("transactions", "inbox"):
        return row.get("title") or row.get("description") or _short_id(resource_id)
    if path == "hashtags":
        name = row.get("name")
        return f"#{name}" if name else _short_id(resource_id)
    if path == "reconciliations":
        date = row.get("statement_date") or row.get("date")
        account_id = row.get("account_id")
        account_name = None
        if isinstance(account_id, str):
            try:
                account_name = client.get(f"/accounts/{account_id}").get("name")
            except EngineError:
                account_name = None
        if isinstance(date, str) and account_name:
            return f"{date[:10]} / {account_name}"
        if isinstance(date, str):
            return date[:10]
        if account_name:
            return account_name
        return _short_id(resource_id)
    return row.get("name") or _short_id(resource_id)


def _resolve_resource_name(
    resource_type: object, resource_id: object, client: ExpenseClient
) -> str:
    """Look up a human name for the row via a live engine read.

    Returns the short 8-char UUID prefix on any miss / error so deleted
    records still have a usable handle.
    """
    if not isinstance(resource_id, str) or not resource_id:
        return "—"
    if not isinstance(resource_type, str):
        return _short_id(resource_id)
    path = _RESOURCE_PATH.get(resource_type)
    if path is None:
        return _short_id(resource_id)
    try:
        row = client.get(f"/{path}/{resource_id}")
    except EngineError:
        return _short_id(resource_id)
    except Exception:
        return _short_id(resource_id)
    if not isinstance(row, dict):
        return _short_id(resource_id)
    try:
        return _display_name(path, row, resource_id, client)
    except Exception:
        return _short_id(resource_id)


def activity_display_cells(item: dict, client: ExpenseClient) -> list[str]:
    """The 6 human cells for one activity row: date, time, action, actor, type, resource.

    Shared by the CLI table renderer and the TUI Activity list screen so both
    resolve resource names and map action codes identically. `client` is an
    open engine client — callers rendering many rows share one connection.
    """
    date_part, time_part = _split_date_time(item.get("created_at"))
    return [
        date_part,
        time_part,
        _action_label(item.get("action")),
        str(item.get("actor_type") or "—"),
        str(item.get("resource_type") or "—"),
        _resolve_resource_name(item.get("resource_type"), item.get("resource_id"), client),
    ]


def _render_activity_rows(items: list[dict], client: ExpenseClient) -> None:
    """Render activity rows as a 6-column table (Date · Time · Action · Actor · Type · Resource).

    Module-level so alternate front doors (e.g. the TUI) can reuse it. Snapshots
    and `changed_by` are deliberately omitted from the table; both remain
    accessible via --json.
    """
    keys = ("date", "time", "action", "actor", "type", "resource")
    rows: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rows.append(dict(zip(keys, activity_display_cells(item, client), strict=True)))
    render_table(
        headers={
            "date": "Date",
            "time": "Time",
            "action": "Action",
            "actor": "Actor",
            "type": "Type",
            "resource": "Resource",
        },
        rows=rows,
    )


def _render_list(body: object, *, json_mode: bool, cfg, verbose: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    items = items_of(body)
    if not items:
        typer.echo("(no activity)")
        return
    with ExpenseClient(cfg, verbose=verbose) as client:
        _render_activity_rows(items, client)
    render_pagination_hint(body, items)


def fetch_activity(
    cfg,
    *,
    resource_type: str | None = None,
    resource_id: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    verbose: bool = False,
) -> dict:
    """GET /v1/activity (engine-direct). Returns the raw response body.

    Extracted so the TUI Activity screen and the typer command share one
    fetch path — the CLI thin-wrapper rule (no logic duplicated in the TUI).
    """
    params: dict = {}
    if resource_type is not None:
        params["resource_type"] = resource_type
    if resource_id is not None:
        params["resource_id"] = resource_id
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset

    with ExpenseClient(cfg, verbose=verbose) as client:
        return client.get(f"/{_RESOURCE}", params=params or None)


@app.command("list")
@handle_errors
def list_(
    ctx: typer.Context,
    resource_type: str | None = typer.Option(
        None,
        "--resource-type",
        help="Filter by resource_type (e.g. transaction).",
    ),
    resource_id: str | None = typer.Option(
        None,
        "--resource-id",
        help="Filter by resource_id (UUID; engine validates).",
    ),
    limit: int | None = LIMIT_OPT,
    offset: int | None = OFFSET_OPT,
    json_output: bool = JSON_OPT,
) -> None:
    """GET /v1/activity. Engine-direct (not cached).

    Snapshots are omitted from the human renderer; pass --json to see
    before_snapshot / after_snapshot.

    Example: expense activity list --resource-type transaction --limit 5
    """
    cfg = config_module.ensure_loaded()
    limit = effective_limit(limit, json_mode=json_output)
    body = fetch_activity(
        cfg,
        resource_type=resource_type,
        resource_id=resource_id,
        limit=limit,
        offset=offset,
        verbose=get_verbose(ctx),
    )
    _render_list(body, json_mode=json_output, cfg=cfg, verbose=get_verbose(ctx))
