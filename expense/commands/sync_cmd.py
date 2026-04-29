import json
from datetime import UTC, datetime

import typer

from expense import config as config_module
from expense.context import get_verbose
from expense.errors import handle_errors
from expense.http import ExpenseClient

_RESOURCE_KEYS = (
    "accounts",
    "categories",
    "hashtags",
    "inbox",
    "transactions",
    "reconciliations",
)


def _format_pulled_at(now: datetime) -> str:
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _render_sync(body: dict, pulled_at: datetime, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return

    typer.echo("Sync (full snapshot)")
    width = max(len(key) for key in _RESOURCE_KEYS) + 1
    for key in _RESOURCE_KEYS:
        items = body.get(key) or []
        count = len(items) if isinstance(items, list) else 0
        typer.echo(f"  {key:<{width}} {count}")

    settings = body.get("settings")
    settings_label = "present" if isinstance(settings, dict) else "(null)"
    typer.echo(f"  {'settings':<{width}} {settings_label}")

    typer.echo("")
    token = body.get("sync_token") or "(null)"
    typer.echo(f"  sync_token: {token}")
    typer.echo(f"  pulled_at:  {_format_pulled_at(pulled_at)}")


@handle_errors
def sync(
    ctx: typer.Context,
    full: bool = typer.Option(
        False,
        "--full",
        help=(
            "Stateless full snapshot. Required in Step 7a; the bare "
            "`expense sync` form is reserved for delta-sync against the "
            "local replica (Step 7b)."
        ),
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Raw engine response (verbatim, no enrichment).",
    ),
) -> None:
    """GET /v1/sync. Stateless full snapshot of every resource.

    Example: expense sync --full
    """
    if not full:
        typer.echo(
            "Error: pass --full to fetch a stateless full snapshot.\n"
            "The bare `expense sync` form is reserved for delta-sync against the\n"
            "local replica (not implemented yet). See docs/cli-runtime.md.",
            err=True,
        )
        raise typer.Exit(code=2)

    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)
    pulled_at = datetime.now(UTC)

    with ExpenseClient(cfg, verbose=verbose, cold_start_notice=True) as client:
        body = client.get(
            "/sync",
            params={"sync_token": "*", "debit_as_negative": "true"},
        )

    _render_sync(body, pulled_at, json_mode=json_output)
