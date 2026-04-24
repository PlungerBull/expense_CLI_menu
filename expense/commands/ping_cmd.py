import json
import time

import typer

from expense import config as config_module
from expense.context import get_verbose
from expense.errors import handle_errors
from expense.http import ExpenseClient


@handle_errors
def ping(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output raw engine response."),
) -> None:
    """Probe GET /health. Confirms the engine is reachable."""
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    start = time.monotonic()
    with ExpenseClient(cfg, verbose=verbose, cold_start_notice=True) as client:
        body = client.get("/health", auth=False)
    elapsed = time.monotonic() - start

    if json_output:
        typer.echo(json.dumps(body, indent=2))
    else:
        status = body.get("status", "?") if isinstance(body, dict) else "?"
        typer.echo(f"{status} ({elapsed:.1f}s)")
