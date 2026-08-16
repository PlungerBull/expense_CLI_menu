from uuid import uuid4

import typer

from expense import config as config_module
from expense.commands._resource import JSON_OPT, render_record
from expense.context import get_verbose
from expense.dates import now_local_iso, to_canonical_aware
from expense.errors import EngineError, handle_errors
from expense.http import ExpenseClient


@handle_errors
def log(
    ctx: typer.Context,
    title: str = typer.Option(..., "--title", help="Short label for the transaction."),
    amount: int = typer.Option(
        ...,
        "--amount",
        help="Signed cents. Negative = expense, positive = income. Sign is mandatory.",
    ),
    account_id: str = typer.Option(..., "--account-id", help="Account UUID to debit/credit."),
    category_id: str = typer.Option(
        ..., "--category-id", help="Category UUID for this transaction."
    ),
    date: str | None = typer.Option(
        None,
        "--date",
        help="YYYY-MM-DD, 'YYYY-MM-DD HH:MM[:SS]', or RFC 3339 with offset. "
        "Naive forms get the local timezone attached. Defaults to now.",
    ),
    description: str | None = typer.Option(None, "--description"),
    cleared: bool | None = typer.Option(None, "--cleared/--no-cleared"),
    hashtag_ids: str | None = typer.Option(
        None,
        "--hashtag-ids",
        help="Comma-separated hashtag UUIDs to attach at creation. "
        "Engine rejects archived ids with 422.",
    ),
    json_output: bool = JSON_OPT,
) -> None:
    """POST /v1/transactions. Direct ledger entry; bypasses the inbox.

    Example: expense log --title Lunch --amount -1500 --account-id <id> --category-id <id>
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
    if hashtag_ids is not None:
        payload["hashtag_ids"] = [
            piece.strip() for piece in hashtag_ids.split(",") if piece.strip()
        ]

    with ExpenseClient(cfg, verbose=verbose) as client:
        try:
            body = client.post("/transactions", json_body=payload)
        except EngineError as err:
            if err.code == "SETTINGS_MISSING":
                typer.echo(
                    "Hint: Your user_settings row is missing. "
                    "Run 'expense auth bootstrap' to provision it.",
                    err=True,
                )
            raise

    if not json_output:
        typer.echo(f"Created: {new_id}")
    render_record(body, json_mode=json_output)
