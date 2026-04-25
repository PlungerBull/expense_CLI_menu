import json
from uuid import uuid4

import typer

from expense import config as config_module
from expense.context import get_verbose
from expense.dates import now_local_iso, to_canonical_aware
from expense.errors import EngineError, handle_errors
from expense.http import ExpenseClient


def _render_transaction(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    for key, value in body.items():
        display = value if value is not None else "(null)"
        typer.echo(f"  {key}: {display}")


@handle_errors
def log(
    ctx: typer.Context,
    title: str = typer.Option(..., "--title", help="Short label for the transaction."),
    amount: int = typer.Option(
        ...,
        "--amount",
        help="Signed cents. Negative = expense, positive = income. Sign is mandatory.",
    ),
    account_id: str = typer.Option(..., "--account-id"),
    category_id: str = typer.Option(..., "--category-id"),
    date: str | None = typer.Option(
        None,
        "--date",
        help="YYYY-MM-DD, 'YYYY-MM-DD HH:MM[:SS]', or RFC 3339 with offset. "
        "Naive forms get the local timezone attached. Defaults to now.",
    ),
    description: str | None = typer.Option(None, "--description"),
    cleared: bool | None = typer.Option(None, "--cleared/--no-cleared"),
    exchange_rate: float | None = typer.Option(
        None, "--exchange-rate", help="Override engine auto-fetch."
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """POST /v1/transactions. Direct ledger entry; bypasses the inbox.

    Transfers (--transfer --to-account) are deferred to Step 4.
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    new_id = str(uuid4())
    payload: dict = {
        "id": new_id,
        "title": title,
        "amount_cents": amount,
        "account_id": account_id,
        "category_id": category_id,
        "date": to_canonical_aware(date) if date is not None else now_local_iso(),
    }
    if description is not None:
        payload["description"] = description
    if cleared is not None:
        payload["cleared"] = cleared
    if exchange_rate is not None:
        payload["exchange_rate"] = exchange_rate

    with ExpenseClient(cfg, verbose=verbose) as client:
        try:
            body = client.post("/transactions", json_body=payload)
        except EngineError as err:
            if err.code == "RATE_UNAVAILABLE":
                typer.echo(
                    "Hint: No FX rate available for the requested date and currency. "
                    "Wait for the daily rate fetch, or pass --exchange-rate <float> to supply one.",
                    err=True,
                )
            elif err.code == "SETTINGS_MISSING":
                typer.echo(
                    "Hint: Your user_settings row is missing. "
                    "Run 'expense auth bootstrap' to provision it.",
                    err=True,
                )
            raise

    if not json_output:
        typer.echo(f"Created: {new_id}")
    _render_transaction(body, json_mode=json_output)
