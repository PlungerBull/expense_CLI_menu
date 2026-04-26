import json

import typer

from expense import config as config_module
from expense.commands.dashboard_cmd import render_category_section
from expense.context import get_verbose
from expense.dates import parse_year_month
from expense.errors import handle_errors
from expense.http import ExpenseClient

app = typer.Typer(help="Historical reports.", no_args_is_help=True)


_MAX_RANGE_MONTHS = 24


def _format_month(month: dict | None) -> str:
    if not isinstance(month, dict):
        return "(unknown)"
    year = month.get("year")
    m = month.get("month")
    if isinstance(year, int) and isinstance(m, int):
        return f"{year:04d}-{m:02d}"
    return "(unknown)"


def _months_between(from_ym: tuple[int, int], to_ym: tuple[int, int]) -> int:
    return (to_ym[0] - from_ym[0]) * 12 + (to_ym[1] - from_ym[1]) + 1


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


def _render_single_month(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    typer.echo(f"Month: {_format_month(body.get('month'))}")
    typer.echo("")
    render_category_section(body.get("categories"))
    typer.echo("")
    _render_totals(body.get("totals"))


def _render_range_table(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return

    months = body.get("months") or []
    if not months:
        typer.echo("(no months)")
        return

    month_labels = [_format_month(m.get("month")) for m in months]

    category_order: list[str] = []
    seen: set[str] = set()
    cat_names: dict[str, str] = {}
    for month_payload in months:
        for cat in month_payload.get("categories") or []:
            cat_id = cat.get("id")
            if not isinstance(cat_id, str) or cat_id in seen:
                continue
            seen.add(cat_id)
            category_order.append(cat_id)
            cat_names[cat_id] = cat.get("name") or "(unnamed)"

    cells: dict[tuple[str, str], int | None] = {}
    for label, month_payload in zip(month_labels, months, strict=True):
        for cat in month_payload.get("categories") or []:
            cat_id = cat.get("id")
            if isinstance(cat_id, str):
                cells[(cat_id, label)] = cat.get("spent_home_cents")

    totals_row: dict[str, int | None] = {}
    for label, month_payload in zip(month_labels, months, strict=True):
        totals = month_payload.get("totals") or {}
        totals_row[label] = totals.get("net_home_cents")

    name_col_w = max(
        [len("Category")] + [len(cat_names[cid]) for cid in category_order] + [len("Totals (net)")]
    )

    def fmt_cell(val: int | None) -> str:
        return "(null)" if val is None else str(val)

    col_widths: list[int] = []
    for label in month_labels:
        widest = len(label)
        for cid in category_order:
            widest = max(widest, len(fmt_cell(cells.get((cid, label)))))
        widest = max(widest, len(fmt_cell(totals_row.get(label))))
        col_widths.append(widest)

    header_parts = [f"{'Category':<{name_col_w}}"] + [
        f"{label:>{w}}" for label, w in zip(month_labels, col_widths, strict=True)
    ]
    typer.echo("  ".join(header_parts))
    typer.echo("  ".join(["-" * name_col_w] + ["-" * w for w in col_widths]))

    for cid in category_order:
        row_parts = [f"{cat_names[cid]:<{name_col_w}}"]
        for label, w in zip(month_labels, col_widths, strict=True):
            row_parts.append(f"{fmt_cell(cells.get((cid, label))):>{w}}")
        typer.echo("  ".join(row_parts))

    typer.echo("  ".join(["-" * name_col_w] + ["-" * w for w in col_widths]))
    totals_parts = [f"{'Totals (net)':<{name_col_w}}"]
    for label, w in zip(month_labels, col_widths, strict=True):
        totals_parts.append(f"{fmt_cell(totals_row.get(label)):>{w}}")
    typer.echo("  ".join(totals_parts))


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
    json_output: bool = typer.Option(False, "--json", help="Raw engine response."),
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
        params = {"year": str(year), "month": str(month)}
        with ExpenseClient(cfg, verbose=verbose) as client:
            body = client.get("/reports/monthly", params=params)
        _render_single_month(body, json_mode=json_output)
        return

    assert date_from is not None and date_to is not None
    from_ym = parse_year_month(date_from, param_hint="--from")
    to_ym = parse_year_month(date_to, param_hint="--to")
    span = _months_between(from_ym, to_ym)
    if span < 1:
        raise typer.BadParameter(
            f"--from ({date_from}) must be on or before --to ({date_to}).",
            param_hint="--from/--to",
        )
    if span > _MAX_RANGE_MONTHS:
        raise typer.BadParameter(
            f"Range span is {span} months; max is {_MAX_RANGE_MONTHS}.",
            param_hint="--from/--to",
        )

    params = {
        "from_year": str(from_ym[0]),
        "from_month": str(from_ym[1]),
        "to_year": str(to_ym[0]),
        "to_month": str(to_ym[1]),
    }
    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.get("/reports/monthly", params=params)
    _render_range_table(body, json_mode=json_output)
