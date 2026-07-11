import json
from datetime import UTC, datetime

import typer

from expense import cache as cache_pkg
from expense import config as config_module
from expense.cache import db as cache_db
from expense.cache.sync import RESOURCE_KEYS, SyncSummary
from expense.context import get_no_cache, get_verbose
from expense.errors import handle_errors
from expense.http import ExpenseClient


def _format_pulled_at(now: datetime) -> str:
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _render_resource_counts(body: dict) -> None:
    width = max(len(key) for key in RESOURCE_KEYS) + 1
    for key in RESOURCE_KEYS:
        items = body.get(key) or []
        count = len(items) if isinstance(items, list) else 0
        typer.echo(f"  {key + ':':<{width + 1}} {count}")
    settings = body.get("settings")
    settings_label = "present" if isinstance(settings, dict) else "(null)"
    typer.echo(f"  {'settings:':<{width + 1}} {settings_label}")


def _render_stateless(body: dict, pulled_at: datetime, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    typer.echo("Sync (full snapshot)")
    _render_resource_counts(body)
    typer.echo("")
    token = body.get("sync_token") or "(null)"
    typer.echo(f"  sync_token: {token}")
    typer.echo(f"  pulled_at:  {_format_pulled_at(pulled_at)}")


def _render_cache_cold_start(summary: SyncSummary, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(summary.raw_response, indent=2))
        return
    typer.echo("Sync (full snapshot)")
    _render_resource_counts(summary.raw_response)
    typer.echo("")
    typer.echo(f"  cache:      {cache_db.cache_path()}")
    typer.echo(f"  sync_token: {summary.sync_token or '(null)'}")
    typer.echo(f"  pulled_at:  {_format_pulled_at(summary.pulled_at)}")


def _render_cache_delta(summary: SyncSummary, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(summary.raw_response, indent=2))
        return
    typer.echo("Sync (delta)")
    typer.echo("  applied:")
    width = max(len(key) for key in RESOURCE_KEYS) + 1
    for key in RESOURCE_KEYS:
        ins = summary.inserts.get(key, 0)
        upd = summary.updates.get(key, 0)
        tomb = summary.tombstones.get(key, 0)
        typer.echo(f"    {key + ':':<{width}} +{ins}  ~{upd}  -{tomb}")
    settings_label = "replaced" if summary.settings_changed else "unchanged"
    typer.echo(f"    {'settings:':<{width}} {settings_label}")
    typer.echo("")
    typer.echo(f"  cache:      {cache_db.cache_path()}")
    typer.echo(f"  sync_token: {summary.sync_token or '(null)'}")
    typer.echo(f"  pulled_at:  {_format_pulled_at(summary.pulled_at)}")


@handle_errors
def sync(
    ctx: typer.Context,
    full: bool = typer.Option(
        False,
        "--full",
        help=(
            "Force a full pull (rebuild cache from scratch). "
            "Bare `expense sync` does a delta sync against the local replica."
        ),
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Raw engine response (verbatim, no enrichment).",
    ),
) -> None:
    """GET /v1/sync. Refresh the local replica.

    Bare `expense sync` does a delta sync (or cold-starts on first run).
    `--full` rebuilds the cache from scratch.
    Pass `--no-cache` (or `EXPENSE_STATELESS=1`) on the root command to bypass the cache.

    Example: expense sync
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)
    no_cache = get_no_cache(ctx)

    if no_cache:
        pulled_at = datetime.now(UTC)
        with ExpenseClient(cfg, verbose=verbose, cold_start_notice=True) as client:
            body = client.get(
                "/sync",
                params={"sync_token": "*", "debit_as_negative": "true"},
            )
        _render_stateless(body, pulled_at, json_mode=json_output)
        return

    with ExpenseClient(cfg, verbose=verbose, cold_start_notice=True) as client:
        if full:
            summary = cache_pkg.cold_start(client, cfg)
        else:
            summary = cache_pkg.delta_sync(client, cfg)

    if summary.kind == "cold_start":
        _render_cache_cold_start(summary, json_mode=json_output)
    else:
        _render_cache_delta(summary, json_mode=json_output)
