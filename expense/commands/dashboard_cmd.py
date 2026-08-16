import json

import typer

from expense import config as config_module
from expense.commands._resource import (
    JSON_OPT,
    format_aggregate,
    format_cents,
    format_month,
    has_aggregate,
    load_hashtag_name_map,
    render_table,
    render_totals,
    unconverted_of,
)
from expense.context import get_verbose
from expense.errors import handle_errors
from expense.http import ExpenseClient


def _render_account_table(items: list[dict] | None, *, empty_message: str) -> None:
    """Render a list of accounts (bank or people) as Name / Currency / Balance.

    Balance is the native amount in the account's currency; the home-currency
    equivalent is intentionally not shown — single-currency users see only one
    meaningful number, and multi-currency users get the value in the unit they
    actually think in for that account.
    """
    if not items:
        typer.echo(empty_message)
        return
    rows = [
        {
            "name": item.get("name") or "(unnamed)",
            "currency": item.get("currency_code") or "?",
            "balance": format_cents(item.get("current_balance_cents")),
        }
        for item in items
    ]
    render_table(
        headers={"name": "Name", "currency": "Currency", "balance": "Balance"},
        rows=rows,
        align_right={"balance"},
    )


def hashtag_label(ids: list[str], name_map: dict[str, str]) -> str:
    """Format a hashtag-combo label, resolving ids via name_map.

    Empty ids → `(no hashtags)`. Otherwise joins resolved names (or raw id
    fallback for any unresolved entry) with ` + `.
    """
    if not ids:
        return "(no hashtags)"
    return " + ".join(name_map.get(hid, hid) for hid in ids)


def _render_categories_table(categories: list[dict] | None) -> None:
    """Render the Categories block as Name / Home, with indented hashtag sub-rows.

    Hashtag breakdown (when present in the engine payload) renders as an
    indented sub-row in the Name column.

    The amount is `spent_home_cents` — the only cross-account figure that exists
    since 2026-08-05, the native `spent_cents` having been deleted engine-side.
    The column is called `Home` so this table and `reports monthly` agree
    (Phase 4 sketch, option F).

    Categories and hashtag combinations with nothing spent are **not drawn**:
    the engine returns every non-deleted category whether or not it has
    activity, and a report is not a category list. One that could not be priced
    keeps its row and says `3 unrated` (`has_aggregate`).
    """
    typer.echo("Categories:")
    if not categories:
        typer.echo("  (no categories)")
        return
    name_map = load_hashtag_name_map()
    rows: list[dict[str, str]] = []
    for cat in categories:
        cat_unconverted = unconverted_of(cat)
        if not has_aggregate(cat.get("spent_home_cents"), cat_unconverted):
            continue
        rows.append(
            {
                "name": cat.get("name") or "(unnamed)",
                "home": format_aggregate(cat.get("spent_home_cents"), cat_unconverted),
            }
        )
        for sub in cat.get("hashtag_breakdown") or []:
            sub_unconverted = unconverted_of(sub)
            if not has_aggregate(sub.get("spent_home_cents"), sub_unconverted):
                continue
            ids = sub.get("hashtag_ids") or []
            rows.append(
                {
                    "name": "  " + hashtag_label(ids, name_map),
                    "home": format_aggregate(sub.get("spent_home_cents"), sub_unconverted),
                }
            )
    if not rows:
        typer.echo("  (no categories)")
        return
    render_table(
        headers={"name": "Name", "home": "Home"},
        rows=rows,
        align_right={"home"},
    )


def _render_dashboard(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return

    typer.echo(f"Month: {format_month(body.get('month'))}")
    typer.echo("")

    typer.echo("Bank accounts:")
    _render_account_table(body.get("bank_accounts"), empty_message="  (no bank accounts)")
    typer.echo("")

    people = body.get("people") or []
    if people:
        typer.echo("People:")
        _render_account_table(people, empty_message="  (no people)")
        typer.echo("")

    _render_categories_table(body.get("categories"))
    typer.echo("")

    render_totals(body.get("totals"))

    # The archived-categories / archived-hashtags lifetime panels were deleted
    # from the engine on 2026-08-05: archiving a category was never a distinct
    # feature (soft delete already hides a row from the pickers), and those
    # panels were the `is_archived` columns' last readers. An archived *account*
    # is different — it still holds real money — so that panel stays.
    archived_accounts = body.get("archived_accounts")
    if archived_accounts is not None:
        typer.echo("")
        typer.echo("Archived accounts:")
        _render_account_table(archived_accounts, empty_message="  (no archived accounts)")


def fetch_dashboard(
    cfg,
    *,
    include_archived: bool = False,
    verbose: bool = False,
) -> dict:
    """GET /v1/dashboard → the raw engine body. Pure data, no rendering.

    Shared by the flat `dashboard` command and the TUI's Outstanding Amounts
    screen — the fetch/print split that lets both consume the same dict.
    """
    params: dict = {}
    if include_archived:
        params["include_archived"] = "true"

    with ExpenseClient(cfg, verbose=verbose) as client:
        return client.get("/dashboard", params=params or None)


@handle_errors
def dashboard(
    ctx: typer.Context,
    include_archived: bool = typer.Option(
        False,
        "--include-archived",
        help="Add the archived-accounts panel.",
    ),
    json_output: bool = JSON_OPT,
) -> None:
    """GET /v1/dashboard. Current month overview: balances, categories, totals.

    Example: expense dashboard --include-archived
    """
    cfg = config_module.ensure_loaded()
    body = fetch_dashboard(
        cfg,
        include_archived=include_archived,
        verbose=get_verbose(ctx),
    )
    _render_dashboard(body, json_mode=json_output)
