import json

import typer

from expense import config as config_module
from expense.commands._resource import JSON_OPT, LIMIT_OPT, OFFSET_OPT, items_of, render_table
from expense.context import get_verbose
from expense.errors import handle_errors
from expense.http import ExpenseClient

app = typer.Typer(help="Exchange rates.", no_args_is_help=True)


def format_rate(value: object) -> str:
    """4-decimal display for the engine's JSON-number rates (approved mockup)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value) if value is not None else "—"
    return f"{value:.4f}"


def _render_rate(body: object) -> None:
    """Human-mode renderer for /v1/exchange-rates responses.

    Generic key/value iteration so additional engine fields (provider,
    source, fetched_at, …) render without a code change.
    """
    if isinstance(body, dict):
        for key, value in body.items():
            display = value if value is not None else "(null)"
            typer.echo(f"  {key}: {display}")
    else:
        typer.echo(json.dumps(body, indent=2))


def fetch_rate(
    cfg,
    *,
    target: str,
    base: str | None = None,
    date: str | None = None,
    verbose: bool = False,
) -> dict:
    """GET /v1/exchange-rates (engine-direct). Returns the raw response body.

    `base` / `date` are omitted when None so the engine defaults (USD, today)
    apply. Shared by the typer command and the TUI Rates screen.
    """
    params: dict = {"target": target}
    if base is not None:
        params["base"] = base
    if date is not None:
        params["date"] = date

    with ExpenseClient(cfg, verbose=verbose) as client:
        return client.get("/exchange-rates", params=params)


def fetch_rates_history(
    cfg,
    *,
    date: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    verbose: bool = False,
) -> dict:
    """GET /v1/exchange-rates/history (engine-direct). Raw response body.

    Stored daily rates, newest first (`rate_date DESC, base, target`), one row
    per pair per day; `date` is an exact-day filter — no fallback semantics.
    Shared by the typer command and the TUI Rates screen.
    """
    params: dict = {}
    if date is not None:
        params["date"] = date
    if limit is not None:
        params["limit"] = str(limit)
    if offset is not None:
        params["offset"] = str(offset)

    with ExpenseClient(cfg, verbose=verbose) as client:
        return client.get("/exchange-rates/history", params=params or None)


@app.command("list")
@handle_errors
def list_(
    ctx: typer.Context,
    date: str | None = typer.Option(
        None,
        "--date",
        help="Exact ISO date (YYYY-MM-DD) to show a single day. Omit for full history.",
    ),
    limit: int | None = LIMIT_OPT,
    offset: int | None = OFFSET_OPT,
    json_output: bool = JSON_OPT,
) -> None:
    """GET /v1/exchange-rates/history. Engine-direct (not cached).

    Stored daily rates, newest first, one row per currency pair per day.

    Example: expense rates list --date 2026-07-04
    """
    cfg = config_module.ensure_loaded()
    body = fetch_rates_history(cfg, date=date, limit=limit, offset=offset, verbose=get_verbose(ctx))
    if json_output:
        typer.echo(json.dumps(body, indent=2))
        return
    items = items_of(body)
    if not items:
        typer.echo(f"No rates stored for {date}." if date else "No rates stored yet.")
        return
    render_table(
        {"rate_date": "Date", "base": "Base", "target": "Target", "rate": "Rate"},
        [
            {
                "rate_date": str(it.get("rate_date") or "—"),
                "base": str(it.get("base") or "—"),
                "target": str(it.get("target") or "—"),
                "rate": format_rate(it.get("rate")),
            }
            for it in items
        ],
        align_right={"rate"},
    )
    total = body.get("total")
    if isinstance(total, int):
        typer.echo(f"\nshowing {len(items)} of {total} · newest first")


@app.command("get")
@handle_errors
def get(
    ctx: typer.Context,
    target: str = typer.Option(..., "--target", help="Target currency code (e.g. EUR)."),
    base: str | None = typer.Option(
        None,
        "--base",
        help="Base currency code. Engine default is USD.",
    ),
    date: str | None = typer.Option(
        None,
        "--date",
        help=(
            "ISO date (YYYY-MM-DD). Engine defaults to today; falls back to "
            "the most recent prior rate."
        ),
    ),
    json_output: bool = JSON_OPT,
) -> None:
    """GET /v1/exchange-rates. Engine-direct (not cached).

    Example: expense rates get --target EUR --date 2026-04-01
    """
    cfg = config_module.ensure_loaded()
    body = fetch_rate(cfg, target=target, base=base, date=date, verbose=get_verbose(ctx))

    if json_output:
        typer.echo(json.dumps(body, indent=2))
        return
    _render_rate(body)
