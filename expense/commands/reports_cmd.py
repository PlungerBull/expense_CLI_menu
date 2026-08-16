import json

import typer

from expense import config as config_module
from expense.commands._resource import (
    JSON_OPT,
    format_aggregate,
    format_month,
    has_aggregate,
    load_hashtag_name_map,
    render_table,
    render_totals,
    unconverted_of,
)
from expense.commands.dashboard_cmd import hashtag_label
from expense.context import get_verbose
from expense.dates import parse_year_month
from expense.errors import handle_errors
from expense.http import ExpenseClient

app = typer.Typer(help="Historical reports.", no_args_is_help=True)

#: A month in which a row had no activity at all. Distinct from `3 unrated`,
#: which means there *was* activity the engine could not price.
NO_ACTIVITY_MARK = "—"


def _render_single_month_categories(categories: list[dict] | None, *, show_hashtags: bool) -> None:
    """Render the Categories block as an ASCII table.

    When show_hashtags is True, each category's hashtag_breakdown rows render
    as indented sub-rows in the Name column.

    One amount column, `Home`: the native `spent_cents` was deleted engine-side
    on 2026-08-05 (a sum across currencies is a number in no currency), so the
    converted figure is the only one that exists. Rows with nothing spent are
    dropped; rows the engine could not price say `3 unrated`. Same rules and
    same column name as `dashboard` — the two tables are read side by side.
    """
    typer.echo("Categories:")
    if not categories:
        typer.echo("  (no categories)")
        return

    name_map = load_hashtag_name_map() if show_hashtags else {}
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
        if not show_hashtags:
            continue
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


def _render_single_month(body: dict, *, json_mode: bool, show_hashtags: bool = True) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    typer.echo(f"Month: {format_month(body.get('month'))}")
    typer.echo("")
    _render_single_month_categories(body.get("categories"), show_hashtags=show_hashtags)
    typer.echo("")
    render_totals(body.get("totals"))


def _grid_cell_value(payload: dict) -> dict:
    """One grid cell: the home figure plus the count that explains a missing one.

    Kept as a dict rather than a bare int because `None` alone cannot carry the
    difference between "nothing happened" and "the engine refused to price
    this" — the conflation Phase 4 exists to remove.
    """
    return {
        "cents": payload.get("spent_home_cents"),
        "unconverted": unconverted_of(payload),
    }


def cell_is_empty(cell: object) -> bool:
    """True for a cell with no activity — nothing spent, and nothing unpriced."""
    if not isinstance(cell, dict):
        return True
    return not has_aggregate(cell.get("cents"), cell.get("unconverted"))


def build_range_grid(months: list[dict]) -> dict:
    """Merge a range payload into grid rows. Pure data; shared by flat + TUI.

    Categories (and each category's hashtag combos) keep first-appearance order
    across the window. All amount cells are home-currency (`spent_home_cents` /
    `net_home_cents`) — the only figures that exist since 2026-08-05, the native
    aggregates having been deleted engine-side.

    A cell carries its `unconverted_count` alongside the figure, because three
    states have to stay distinguishable: a number, *no activity that month*, and
    *the engine could not price this* (`cents: None` with a non-zero count). A
    month a row is absent from has no cell at all, which reads as no activity.

    Rows (and combos) with nothing spent in **any** month of the window are
    dropped entirely — the engine returns every non-deleted category for every
    month, so keeping them would fill the grid with blank lines. Returns::

        {
          "labels": ["2026-04", ...],
          "rows": [{"id", "name",
                    "cells": {label: {"cents": int|None, "unconverted": int}},
                    "breakdown": [{"hashtag_ids": [...], "cells": {...}}]}],
          "net": {label: {"cents": int|None, "unconverted": int}},
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
            row["cells"][label] = _grid_cell_value(cat)
            for sub in cat.get("hashtag_breakdown") or []:
                ids = sub.get("hashtag_ids") or []
                combo_key = (cat_id, tuple(ids))
                combo = combo_index.get(combo_key)
                if combo is None:
                    combo = {"hashtag_ids": ids, "cells": {}}
                    combo_index[combo_key] = combo
                    row["breakdown"].append(combo)
                combo["cells"][label] = _grid_cell_value(sub)

    net: dict[str, dict] = {}
    for label, month_payload in zip(labels, months, strict=True):
        totals = month_payload.get("totals") or {}
        net[label] = {
            "cents": totals.get("net_home_cents"),
            "unconverted": unconverted_of(totals),
        }

    rows = []
    for cid in order:
        row = rows_by_id[cid]
        if all(cell_is_empty(c) for c in row["cells"].values()):
            continue
        row["breakdown"] = [
            combo
            for combo in row["breakdown"]
            if not all(cell_is_empty(c) for c in combo["cells"].values())
        ]
        rows.append(row)

    return {"labels": labels, "rows": rows, "net": net}


def format_grid_cell(cell: object) -> str:
    """A grid cell as text — shared by the flat table and the TUI grid.

    A dim `—` means nothing happened that month; `3 unrated` means there was
    activity the engine could not price. Keeping the two apart is the point of
    the cell dict (`build_range_grid`).
    """
    if cell_is_empty(cell):
        return NO_ACTIVITY_MARK
    assert isinstance(cell, dict)
    return format_aggregate(cell.get("cents"), cell.get("unconverted"))


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
    totals_row: dict[str, dict] = grid["net"]

    def month_cells(source: dict) -> dict[str, str]:
        return {label: format_grid_cell(source.get(label)) for label in month_labels}

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
