import json

import typer

from expense import config as config_module
from expense.commands._resource import render_pagination_hint, render_table
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
# guesses to a canonical kind so name resolution is robust to either.
_RESOURCE_KIND = {
    "transaction": "transaction",
    "expense_transactions": "transaction",
    "account": "account",
    "accounts": "account",
    "category": "category",
    "categories": "category",
    "hashtag": "hashtag",
    "hashtags": "hashtag",
    "inbox": "inbox",
    "inbox_items": "inbox",
    "reconciliation": "reconciliation",
    "reconciliations": "reconciliation",
}


def _resolve_resource_name(resource_type: object, resource_id: object) -> str:
    """Look up a human name for the row via the local cache replica.

    Returns the short 8-char UUID prefix on any cache miss / error so deleted
    or never-synced records still have a usable handle.
    """
    if not isinstance(resource_id, str) or not resource_id:
        return "—"
    if not isinstance(resource_type, str):
        return _short_id(resource_id)
    kind = _RESOURCE_KIND.get(resource_type)
    if kind is None:
        return _short_id(resource_id)
    try:
        from expense.cache import queries
    except Exception:
        return _short_id(resource_id)

    try:
        if kind == "transaction":
            row = queries.get_transaction(resource_id)
            return row.get("title") or row.get("description") or _short_id(resource_id)
        if kind == "account":
            row = queries.get_account(resource_id)
            return row.get("name") or _short_id(resource_id)
        if kind == "category":
            row = queries.get_category(resource_id)
            return row.get("name") or _short_id(resource_id)
        if kind == "hashtag":
            row = queries.get_hashtag(resource_id)
            name = row.get("name")
            return f"#{name}" if name else _short_id(resource_id)
        if kind == "inbox":
            row = queries.get_inbox(resource_id)
            return row.get("title") or row.get("description") or _short_id(resource_id)
        if kind == "reconciliation":
            row = queries.get_reconciliation(resource_id)
            date = row.get("statement_date") or row.get("date")
            account_id = row.get("account_id")
            account_name = None
            if isinstance(account_id, str):
                try:
                    account_row = queries.get_account(account_id)
                    account_name = account_row.get("name")
                except EngineError:
                    account_name = None
            if isinstance(date, str) and account_name:
                return f"{date[:10]} / {account_name}"
            if isinstance(date, str):
                return date[:10]
            if account_name:
                return account_name
            return _short_id(resource_id)
    except EngineError:
        return _short_id(resource_id)
    except Exception:
        return _short_id(resource_id)

    return _short_id(resource_id)


def activity_display_cells(item: dict) -> list[str]:
    """The 6 human cells for one activity row: date, time, action, actor, type, resource.

    Shared by the CLI table renderer and the TUI Activity list screen so both
    resolve resource names and map action codes identically.
    """
    date_part, time_part = _split_date_time(item.get("created_at"))
    return [
        date_part,
        time_part,
        _action_label(item.get("action")),
        str(item.get("actor_type") or "—"),
        str(item.get("resource_type") or "—"),
        _resolve_resource_name(item.get("resource_type"), item.get("resource_id")),
    ]


def _render_activity_rows(items: list[dict]) -> None:
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
        rows.append(dict(zip(keys, activity_display_cells(item), strict=True)))
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


def _render_list(body: object, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    items = body.get("items", body) if isinstance(body, dict) else body
    if not items:
        typer.echo("(no activity)")
        return
    _render_activity_rows(items)
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
        help="Filter by resource_type (e.g. expense_transactions).",
    ),
    resource_id: str | None = typer.Option(
        None,
        "--resource-id",
        help="Filter by resource_id (UUID; engine validates).",
    ),
    limit: int | None = typer.Option(None, "--limit"),
    offset: int | None = typer.Option(None, "--offset"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """GET /v1/activity. Engine-direct (not cached).

    Snapshots are omitted from the human renderer; pass --json to see
    before_snapshot / after_snapshot.

    Example: expense activity list --resource-type expense_transactions --limit 5
    """
    cfg = config_module.ensure_loaded()
    body = fetch_activity(
        cfg,
        resource_type=resource_type,
        resource_id=resource_id,
        limit=limit,
        offset=offset,
        verbose=get_verbose(ctx),
    )
    _render_list(body, json_mode=json_output)
