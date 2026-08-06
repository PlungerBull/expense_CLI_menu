import json

import typer

from expense import config as config_module
from expense.commands._resource import (
    JSON_OPT,
    format_cents,
    format_month,
    load_hashtag_name_map,
    render_table,
    render_totals,
)
from expense.commands.dashboard_cmd import hashtag_label
from expense.context import get_verbose
from expense.dates import parse_year_month
from expense.errors import handle_errors
from expense.http import ExpenseClient

app = typer.Typer(help="Historical reports.", no_args_is_help=True)


def _render_single_month_categories(categories: list[dict] | None, *, show_hashtags: bool) -> None:
    """Render the Categories block as an ASCII table.

    When show_hashtags is True, each category's hashtag_breakdown rows render
    as indented sub-rows in the Name column.
    """
    typer.echo("Categories:")
    if not categories:
        typer.echo("  (no categories)")
        return

    name_map = load_hashtag_name_map() if show_hashtags else {}
    rows: list[dict[str, str]] = []
    for cat in categories:
        rows.append(
            {
                "name": cat.get("name") or "(unnamed)",
                "spent": format_cents(cat.get("spent_cents")),
                "home": format_cents(cat.get("spent_home_cents")),
            }
        )
        if not show_hashtags:
            continue
        for sub in cat.get("hashtag_breakdown") or []:
            ids = sub.get("hashtag_ids") or []
            rows.append(
                {
                    "name": "  " + hashtag_label(ids, name_map),
                    "spent": format_cents(sub.get("spent_cents")),
                    "home": format_cents(sub.get("spent_home_cents")),
                }
            )

    render_table(
        headers={"name": "Name", "spent": "Spent", "home": "Home"},
        rows=rows,
        align_right={"spent", "home"},
    )


def _render_single_month(body: dict, *, json_mode: bool, show_hashtags: bool = True) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    typer.echo(f"Month: {format_month(body.get('month'))}")
    typer.echo("")
    _render_single_month_categories(body.get("categories"), show_hashtags=show_hashtags)
    typer.echo("")
    render_totals(body.get("totals"))


def build_range_grid(months: list[dict]) -> dict:
    """Merge a range payload into grid rows. Pure data; shared by flat + TUI.

    Categories (and each category's hashtag combos) keep first-appearance
    order across the window; a month where a row had no activity is a None
    cell. All amount cells are home-currency (`spent_home_cents` /
    `net_home_cents`) — the only column comparable across a multi-currency
    grid. Returns::

        {
          "labels": ["2026-04", ...],
          "rows": [{"id", "name", "cells": {label: cents|None},
                    "breakdown": [{"hashtag_ids": [...],
                                   "cells": {label: cents|None}}]}],
          "net": {label: cents|None},
        }
    """
    labels = [format_month(m.get("month")) for m in months]

    order: list[str] = []
    rows_by_id: dict[str, dict] = {}
    combo_index: dict[tuple[str, tuple[str, ...]], dict] = {}
    for label, month_payload in zip(labels, months, strict=True):
        for cat in month_payload.get("categories") or []:
            cat_id = cat.get("id")
            if not isinstance(cat_id, str):
                continue
            row = rows_by_id.get(cat_id)
            if row is None:
                row = {
                    "id": cat_id,
                    "name": cat.get("name") or "(unnamed)",
                    "cells": {},
                    "breakdown": [],
                }
                rows_by_id[cat_id] = row
                order.append(cat_id)
            row["cells"][label] = cat.get("spent_home_cents")
            for sub in cat.get("hashtag_breakdown") or []:
                ids = sub.get("hashtag_ids") or []
                combo_key = (cat_id, tuple(ids))
                combo = combo_index.get(combo_key)
                if combo is None:
                    combo = {"hashtag_ids": ids, "cells": {}}
                    combo_index[combo_key] = combo
                    row["breakdown"].append(combo)
                combo["cells"][label] = sub.get("spent_home_cents")

    net: dict[str, int | None] = {}
    for label, month_payload in zip(labels, months, strict=True):
        totals = month_payload.get("totals") or {}
        net[label] = totals.get("net_home_cents")

    return {"labels": labels, "rows": [rows_by_id[cid] for cid in order], "net": net}


def _render_range_table(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return

    months = body.get("months") or []
    if not months:
        typer.echo("(no months)")
        return

    grid = build_range_grid(months)
    month_labels: list[str] = grid["labels"]
    grid_rows: list[dict] = grid["rows"]
    totals_row: dict[str, int | None] = grid["net"]

    def month_cells(source: dict) -> dict[str, str]:
        return {label: format_cents(source.get(label)) for label in month_labels}

    headers = {"name": "Category", **{label: label for label in month_labels}}
    rows = [{"name": row["name"], **month_cells(row["cells"])} for row in grid_rows]
    footer = {"name": "Totals (net)", **month_cells(totals_row)}
    render_table(headers, rows, align_right=set(month_labels), footer=footer)


def fetch_single_month(
    cfg,
    *,
    year: int,
    month: int,
    verbose: bool = False,
) -> dict:
    """GET /v1/reports/monthly for one month → the raw engine body. No rendering."""
    params = {"year": str(year), "month": str(month)}
    with ExpenseClient(cfg, verbose=verbose) as client:
        return client.get("/reports/monthly", params=params)


def fetch_range(
    cfg,
    *,
    from_ym: tuple[int, int],
    to_ym: tuple[int, int],
    verbose: bool = False,
) -> dict:
    """GET /v1/reports/monthly for a month range → the raw engine body. No rendering.

    Range rules (inverted range, max span) are the engine's — invalid ranges
    are sent as-is so its 422 surfaces.
    """
    params = {
        "from_year": str(from_ym[0]),
        "from_month": str(from_ym[1]),
        "to_year": str(to_ym[0]),
        "to_month": str(to_ym[1]),
    }
    with ExpenseClient(cfg, verbose=verbose) as client:
        return client.get("/reports/monthly", params=params)


def run_single_month(
    cfg,
    *,
    year: int,
    month: int,
    verbose: bool = False,
    json_mode: bool = False,
    show_hashtags: bool = True,
) -> None:
    """Fetch + render for a single month — the flat command's whole body."""
    body = fetch_single_month(
        cfg,
        year=year,
        month=month,
        verbose=verbose,
    )
    _render_single_month(body, json_mode=json_mode, show_hashtags=show_hashtags)


def run_range(
    cfg,
    *,
    from_ym: tuple[int, int],
    to_ym: tuple[int, int],
    verbose: bool = False,
    json_mode: bool = False,
) -> None:
    """Fetch + render for a month range — the flat command's whole body."""
    body = fetch_range(cfg, from_ym=from_ym, to_ym=to_ym, verbose=verbose)
    _render_range_table(body, json_mode=json_mode)


@app.command("monthly")
@handle_errors
def monthly(
    ctx: typer.Context,
    date: str | None = typer.Option(
        None,
        "--date",
        help="Single month, YYYY-MM (e.g. 2026-04). Mutually exclusive with --from/--to.",
    ),
    date_from: str | None = typer.Option(
        None,
        "--from",
        help="Range start, YYYY-MM. Requires --to. Inclusive.",
    ),
    date_to: str | None = typer.Option(
        None,
        "--to",
        help="Range end, YYYY-MM. Requires --from. Inclusive. Max span: 24 months.",
    ),
    json_output: bool = JSON_OPT,
) -> None:
    """GET /v1/reports/monthly. Historical flow for a single month or a month range.

    Example: expense reports monthly --date 2026-03
    Example: expense reports monthly --from 2025-11 --to 2026-04
    """
    if date is not None and (date_from is not None or date_to is not None):
        raise typer.BadParameter(
            "--date is mutually exclusive with --from/--to.",
            param_hint="--date",
        )
    if (date_from is None) != (date_to is None):
        raise typer.BadParameter(
            "--from and --to must be passed together.",
            param_hint="--from/--to",
        )
    if date is None and date_from is None:
        raise typer.BadParameter(
            "Pass either --date YYYY-MM or --from YYYY-MM --to YYYY-MM.",
            param_hint="--date",
        )

    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    if date is not None:
        year, month = parse_year_month(date, param_hint="--date")
        run_single_month(
            cfg,
            year=year,
            month=month,
            verbose=verbose,
            json_mode=json_output,
        )
        return

    assert date_from is not None and date_to is not None
    from_ym = parse_year_month(date_from, param_hint="--from")
    to_ym = parse_year_month(date_to, param_hint="--to")

    run_range(
        cfg,
        from_ym=from_ym,
        to_ym=to_ym,
        verbose=verbose,
        json_mode=json_output,
    )
