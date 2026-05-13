import json

import typer

from expense import config as config_module
from expense.cache import queries
from expense.commands._resource import render_totals
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


def load_hashtag_name_map() -> dict[str, str]:
    """Return {hashtag_id: name} from the local cache, or {} on any failure.

    The engine returns hashtag UUIDs in `hashtag_breakdown` rows; the renderer
    joins against this map to display human names like `Food + Club`. Empty
    map is safe — callers fall back to raw ids.
    """
    try:
        page = queries.list_hashtags(include_archived=True, include_deleted=False)
    except Exception:
        return {}
    out: dict[str, str] = {}
    for item in page.get("items") or []:
        hid = item.get("id")
        name = item.get("name")
        if isinstance(hid, str) and isinstance(name, str):
            out[hid] = name
    return out


def hashtag_label(ids: list[str], name_map: dict[str, str]) -> str:
    """Format a hashtag-combo label, resolving ids via name_map.

    Empty ids → `(no hashtags)`. Otherwise joins resolved names (or raw id
    fallback for any unresolved entry) with ` + `.
    """
    if not ids:
        return "(no hashtags)"
    return " + ".join(name_map.get(hid, hid) for hid in ids)


def render_category_section(
    categories: list[dict] | None,
    *,
    header: str = "Categories",
    show_hashtags: bool = True,
    name_map: dict[str, str] | None = None,
) -> None:
    """Render the categories + hashtag-breakdown block. Shared with reports_cmd."""
    typer.echo(f"{header}:")
    if not categories:
        typer.echo("  (no categories)")
        return
    if name_map is not None:
        resolved = name_map
    elif show_hashtags:
        resolved = load_hashtag_name_map()
    else:
        resolved = {}
    for cat in categories:
        name = cat.get("name", "(unnamed)")
        spent = cat.get("spent_cents")
        spent_home = cat.get("spent_home_cents")
        spent_s = spent if spent is not None else "(null)"
        home_s = spent_home if spent_home is not None else "(null)"
        typer.echo(f"  {name}")
        typer.echo(f"    spent: {spent_s} (home: {home_s})")
        if not show_hashtags:
            continue
        breakdown = cat.get("hashtag_breakdown") or []
        if breakdown:
            typer.echo("    breakdown:")
            for row in breakdown:
                ids = row.get("hashtag_ids") or []
                row_amount = row.get("spent_cents")
                row_home = row.get("spent_home_cents")
                row_amount_s = row_amount if row_amount is not None else "(null)"
                row_home_s = row_home if row_home is not None else "(null)"
                label = hashtag_label(ids, resolved)
                typer.echo(f"      {label}: {row_amount_s} (home: {row_home_s})")


def _render_archived_accounts(items: list[dict] | None) -> None:
    typer.echo("Archived accounts:")
    if not items:
        typer.echo("  (no archived accounts)")
        return
    for item in items:
        _render_account_row(item)


def _render_archived_lifetime(items: list[dict] | None, *, header: str) -> None:
    typer.echo(f"{header}:")
    if not items:
        typer.echo(f"  (no {header.lower()})")
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
        typer.echo("  (no bank accounts)")
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

    render_totals(body.get("totals"))

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

    with ExpenseClient(cfg, verbose=verbose, cold_start_notice=True) as client:
        body = client.get("/dashboard", params=params or None)

    _render_dashboard(body, json_mode=json_output)
