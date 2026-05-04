"""Shared helpers for resource sub-apps (accounts, categories, hashtags)."""

import json
import sys
from collections.abc import Callable
from typing import Any

import typer

from expense import config as config_module
from expense.cache import refresh_after_write
from expense.config import Config
from expense.context import get_no_cache, get_no_sync_after, get_verbose
from expense.errors import EngineError
from expense.http import ExpenseClient


def cache_after_write(ctx: typer.Context, client: ExpenseClient, cfg: Config) -> None:
    """Post-write cache refresh — reads --no-cache / --no-sync-after off ctx."""
    refresh_after_write(
        client,
        cfg,
        no_cache=get_no_cache(ctx),
        no_sync_after=get_no_sync_after(ctx),
    )


def require_yes(yes: bool, prompt_text: str) -> None:
    """Enforce explicit confirmation for destructive operations.

    Mirrors the pattern from `auth settings`: in non-TTY mode, --yes is mandatory;
    in TTY mode, prompt the user unless --yes was already passed.
    """
    if yes:
        return
    if not sys.stdin.isatty():
        typer.echo(
            "Error: --yes is required for this operation in non-interactive mode.",
            err=True,
        )
        raise typer.Exit(code=1)
    if not typer.confirm(prompt_text):
        typer.echo("Aborted.")
        raise typer.Exit(code=1)


def build_update_payload(items: dict[str, Any]) -> dict[str, Any]:
    """Drop None values; exit if nothing is left to update."""
    payload = {key: value for key, value in items.items() if value is not None}
    if not payload:
        typer.echo("Error: No fields to update; pass at least one flag.", err=True)
        raise typer.Exit(code=1)
    return payload


def render_totals(totals: dict | None) -> None:
    """Render the canonical inflow/outflow/net block.

    Shared by `dashboard` and `reports monthly` (single-month view) — both
    surface the same `{inflow, outflow, net}_cents` + `_home_cents` shape.
    Empty/missing totals print '(no totals)'.
    """
    typer.echo("Totals:")
    if not isinstance(totals, dict):
        typer.echo("  (no totals)")
        return
    for key in ("inflow_cents", "outflow_cents", "net_cents"):
        native = totals.get(key)
        home_key = key.replace("_cents", "_home_cents")
        home = totals.get(home_key)
        native_s = native if native is not None else "(null)"
        home_s = home if home is not None else "(null)"
        label = key.replace("_cents", "")
        typer.echo(f"  {label}: {native_s} (home: {home_s})")


def render_pagination_hint(body: Any, items: list[Any]) -> None:
    """Print a `(showing N of M; pass --offset ... --limit ... for more)` hint.

    No-op when the body isn't paginated, items fit on one page, or required
    metadata is missing. Used by every paginated `list` renderer.
    """
    if not isinstance(body, dict):
        return
    total = body.get("total")
    limit = body.get("limit")
    offset = body.get("offset")
    if not (isinstance(total, int) and isinstance(limit, int) and isinstance(offset, int)):
        return
    if offset + len(items) >= total:
        return
    next_offset = offset + len(items)
    typer.echo(
        f"\n(showing {len(items)} of {total}; pass --offset {next_offset} --limit {limit} for more)"
    )


def run_toggle(
    ctx: typer.Context,
    *,
    resource: str,
    id_: str,
    verb: str,
    json_output: bool,
    render_human: Callable[[dict], None],
    hints: dict[int, str] | None = None,
) -> None:
    """Execute one of the {archive, unarchive, restore} toggle verbs.

    All three are POST /{resource}/{id}/{verb} with no body and an identical
    response shape (the resource row).

    `hints` maps HTTP status code → stderr hint string. When the engine
    raises an EngineError whose `.status` matches a key, the hint is
    printed before the error envelope renders. This lets archive/restore
    on resources with domain-specific 403/409 conditions (e.g. system
    categories, name conflicts) keep their friendly recovery prompts
    without forking the call site.
    """
    cfg: Config = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    with ExpenseClient(cfg, verbose=verbose) as client:
        try:
            body = client.post(f"/{resource}/{id_}/{verb}")
        except EngineError as err:
            if hints and err.status in hints:
                typer.echo(hints[err.status], err=True)
            raise
        cache_after_write(ctx, client, cfg)

    if json_output:
        typer.echo(json.dumps(body, indent=2))
    else:
        render_human(body)
