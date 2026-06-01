import json

import typer

from expense import config as config_module
from expense.context import get_verbose
from expense.errors import handle_errors
from expense.http import ExpenseClient

app = typer.Typer(help="Exchange rates.", no_args_is_help=True)


def _render_rate(body: object) -> None:
    """Human-mode renderer for /v1/exchange-rates responses.

    Generic key/value iteration so additional engine fields (provider,
    source, fetched_at, …) render without a code change. Shared with the
    9.5.15 menu surface.
    """
    if isinstance(body, dict):
        for key, value in body.items():
            display = value if value is not None else "(null)"
            typer.echo(f"  {key}: {display}")
    else:
        typer.echo(json.dumps(body, indent=2))


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
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """GET /v1/exchange-rates. Engine-direct (not cached).

    Example: expense rates get --target EUR --date 2026-04-01
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    params: dict = {"target": target}
    if base is not None:
        params["base"] = base
    if date is not None:
        params["date"] = date

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.get("/exchange-rates", params=params)

    if json_output:
        typer.echo(json.dumps(body, indent=2))
        return
    _render_rate(body)
