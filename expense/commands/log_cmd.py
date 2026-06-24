import json
from uuid import uuid4

import typer

from expense import config as config_module
from expense.commands._resource import cache_after_write, format_field_value
from expense.context import get_verbose
from expense.dates import now_local_iso, to_canonical_aware
from expense.errors import EngineError, handle_errors
from expense.http import ExpenseClient


def _render_transaction(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    for key, value in body.items():
        typer.echo(f"  {key}: {format_field_value(key, value)}")


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
    exchange_rate: float | None = typer.Option(
        None, "--exchange-rate", help="Override engine auto-fetch."
    ),
    transfer: bool = typer.Option(
        False,
        "--transfer",
        help="Create a paired transfer. Requires --to-account-id and --to-amount.",
    ),
    to_account_id: str | None = typer.Option(
        None, "--to-account-id", help="Sibling account for the transfer pair."
    ),
    to_amount: int | None = typer.Option(
        None,
        "--to-amount",
        help="Sibling signed-cents amount. Must be opposite sign to --amount.",
    ),
    hashtag_ids: str | None = typer.Option(
        None,
        "--hashtag-ids",
        help="Comma-separated hashtag UUIDs to attach at creation. "
        "Engine rejects archived ids with 422.",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """POST /v1/transactions. Direct ledger entry; bypasses the inbox.

    Pass --transfer with --to-account-id and --to-amount to create a paired
    transfer in a single atomic call (engine creates both legs and links them).

    Example: expense log --title Lunch --amount -1500 --account-id <id> --category-id <id>
    """
    if transfer:
        if to_account_id is None or to_amount is None:
            raise typer.BadParameter(
                "--transfer requires both --to-account-id and --to-amount.",
                param_hint="--transfer",
            )
    else:
        if to_account_id is not None or to_amount is not None:
            raise typer.BadParameter(
                "--to-account-id and --to-amount only apply with --transfer.",
                param_hint="--to-account-id/--to-amount",
            )

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
    if hashtag_ids is not None:
        payload["hashtag_ids"] = [
            piece.strip() for piece in hashtag_ids.split(",") if piece.strip()
        ]

    sibling_id: str | None = None
    if transfer:
        sibling_id = str(uuid4())
        payload["transfer"] = {
            "id": sibling_id,
            "account_id": to_account_id,
            "amount_cents": to_amount,
        }

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
        cache_after_write(ctx, client, cfg)

    if not json_output:
        typer.echo(f"Created: {new_id}")
        if sibling_id is not None:
            typer.echo(f"Created (transfer leg): {sibling_id}")
    _render_transaction(body, json_mode=json_output)
