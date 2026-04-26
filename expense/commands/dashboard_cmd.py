import json

import typer

from expense import config as config_module
from expense.context import get_verbose
from expense.errors import handle_errors
from expense.http import ExpenseClient


def _format_month(month: dict | None) -> str:
    if not isinstance(month, dict):
        return "(unknown)"
    year = month.get("year")
    m = month.get("month")
    if isinstance(year, int) and isinstance(m, int):
        return f"{year:04d}-{m:02d}"
    return "(unknown)"


def _render_account_row(item: dict) -> None:
    name = item.get("name", "(unnamed)")
    currency = item.get("currency_code", "?")
    native = item.get("current_balance_cents")
    home = item.get("current_balance_home_cents")
    native_s = native if native is not None else "(null)"
    home_s = home if home is not None else "(null)"
    typer.echo(f"  {name} ({currency})")
    typer.echo(f"    balance: {native_s} (home: {home_s})")


def render_category_section(categories: list[dict] | None, *, header: str = "Categories") -> None:
    """Render the categories + hashtag-breakdown block. Shared with reports_cmd."""
    typer.echo(f"{header}:")
    if not categories:
        typer.echo("  (none)")
        return
    for cat in categories:
        name = cat.get("name", "(unnamed)")
        spent = cat.get("spent_cents")
        spent_home = cat.get("spent_home_cents")
        spent_s = spent if spent is not None else "(null)"
        home_s = spent_home if spent_home is not None else "(null)"
        typer.echo(f"  {name}")
        typer.echo(f"    spent: {spent_s} (home: {home_s})")
        breakdown = cat.get("hashtag_breakdown") or []
        if breakdown:
            typer.echo("    breakdown:")
            for row in breakdown:
                ids = row.get("hashtag_ids") or []
                row_amount = row.get("spent_cents")
                row_home = row.get("spent_home_cents")
                row_amount_s = row_amount if row_amount is not None else "(null)"
                row_home_s = row_home if row_home is not None else "(null)"
                label = "[" + ", ".join(ids) + "]" if ids else "(no hashtags)"
                typer.echo(f"      {label}: {row_amount_s} (home: {row_home_s})")


def _render_totals(totals: dict | None) -> None:
    typer.echo("Totals:")
    if not isinstance(totals, dict):
        typer.echo("  (none)")
        return
    for key in ("inflow_cents", "outflow_cents", "net_cents"):
        native = totals.get(key)
        home_key = key.replace("_cents", "_home_cents")
        home = totals.get(home_key)
        native_s = native if native is not None else "(null)"
        home_s = home if home is not None else "(null)"
        label = key.replace("_cents", "")
        typer.echo(f"  {label}: {native_s} (home: {home_s})")


def _render_archived_accounts(items: list[dict] | None) -> None:
    typer.echo("Archived accounts:")
    if not items:
        typer.echo("  (none)")
        return
    for item in items:
        _render_account_row(item)


def _render_archived_lifetime(items: list[dict] | None, *, header: str) -> None:
    typer.echo(f"{header}:")
    if not items:
        typer.echo("  (none)")
        return
    for item in items:
        name = item.get("name", "(unnamed)")
        lifetime = item.get("lifetime_spent_cents")
        lifetime_home = item.get("lifetime_spent_home_cents")
        lifetime_s = lifetime if lifetime is not None else "(null)"
        home_s = lifetime_home if lifetime_home is not None else "(null)"
        typer.echo(f"  {name}")
        typer.echo(f"    lifetime spent: {lifetime_s} (home: {home_s})")


def _render_dashboard(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return

    typer.echo(f"Month: {_format_month(body.get('month'))}")
    typer.echo("")

    typer.echo("Bank accounts:")
    bank_accounts = body.get("bank_accounts") or []
    if not bank_accounts:
        typer.echo("  (none)")
    else:
        for item in bank_accounts:
            _render_account_row(item)
    typer.echo("")

    people = body.get("people") or []
    if people:
        typer.echo("People:")
        for item in people:
            _render_account_row(item)
        typer.echo("")

    render_category_section(body.get("categories"))
    typer.echo("")

    _render_totals(body.get("totals"))

    archived_accounts = body.get("archived_accounts")
    archived_categories = body.get("archived_categories")
    archived_hashtags = body.get("archived_hashtags")
    if (
        archived_accounts is not None
        or archived_categories is not None
        or archived_hashtags is not None
    ):
        typer.echo("")
        _render_archived_accounts(archived_accounts)
        typer.echo("")
        _render_archived_lifetime(archived_categories, header="Archived categories")
        typer.echo("")
        _render_archived_lifetime(archived_hashtags, header="Archived hashtags")


@handle_errors
def dashboard(
    ctx: typer.Context,
    include_archived: bool = typer.Option(
        False,
        "--include-archived",
        help="Include archived accounts/categories/hashtags panels (lifetime totals).",
    ),
    json_output: bool = typer.Option(False, "--json", help="Raw engine response."),
) -> None:
    """GET /v1/dashboard. Current month overview: balances, categories, totals.

    Example: expense dashboard --include-archived
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    params: dict = {}
    if include_archived:
        params["include_archived"] = "true"

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.get("/dashboard", params=params or None)

    _render_dashboard(body, json_mode=json_output)
