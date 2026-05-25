import json

import typer

from expense import config as config_module
from expense.commands._resource import render_table, render_totals
from expense.commands.dashboard_cmd import (
    hashtag_label,
    load_hashtag_name_map,
)
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


def _fmt_amount(cents: object) -> str:
    return "(null)" if cents is None else str(cents)


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
                "spent": _fmt_amount(cat.get("spent_cents")),
                "home": _fmt_amount(cat.get("spent_home_cents")),
            }
        )
        if not show_hashtags:
            continue
        for sub in cat.get("hashtag_breakdown") or []:
            ids = sub.get("hashtag_ids") or []
            rows.append(
                {
                    "name": "  " + hashtag_label(ids, name_map),
                    "spent": _fmt_amount(sub.get("spent_cents")),
                    "home": _fmt_amount(sub.get("spent_home_cents")),
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
    typer.echo(f"Month: {_format_month(body.get('month'))}")
    typer.echo("")
    _render_single_month_categories(body.get("categories"), show_hashtags=show_hashtags)
    typer.echo("")
    render_totals(body.get("totals"))


def _render_range_table(body: dict, *, json_mode: bool, expand_hashtags: bool = False) -> None:
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

    # Per-category sub-row plan: for each category, collect the ordered set of
    # hashtag-combo keys (tuple of ids) seen across months, plus per-month cell
    # values. Only built when expand_hashtags=True.
    name_map: dict[str, str] = {}
    sub_keys: dict[str, list[tuple[str, ...]]] = {}
    sub_cells: dict[tuple[str, tuple[str, ...], str], int | None] = {}
    if expand_hashtags:
        name_map = load_hashtag_name_map()
        for cid in category_order:
            sub_keys[cid] = []
        seen_keys: dict[str, set[tuple[str, ...]]] = {cid: set() for cid in category_order}
        for label, month_payload in zip(month_labels, months, strict=True):
            for cat in month_payload.get("categories") or []:
                cid = cat.get("id")
                if not isinstance(cid, str) or cid not in seen_keys:
                    continue
                for row in cat.get("hashtag_breakdown") or []:
                    ids = row.get("hashtag_ids") or []
                    key = tuple(ids)
                    if key not in seen_keys[cid]:
                        seen_keys[cid].add(key)
                        sub_keys[cid].append(key)
                    sub_cells[(cid, key, label)] = row.get("spent_home_cents")

    name_widths = [len("Category"), len("Totals (net)")]
    name_widths.extend(len(cat_names[cid]) for cid in category_order)
    if expand_hashtags:
        for cid in category_order:
            for key in sub_keys.get(cid, []):
                name_widths.append(len("  " + hashtag_label(list(key), name_map)))
    name_col_w = max(name_widths)

    def fmt_cell(val: int | None) -> str:
        return "(null)" if val is None else str(val)

    col_widths: list[int] = []
    for label in month_labels:
        widest = len(label)
        for cid in category_order:
            widest = max(widest, len(fmt_cell(cells.get((cid, label)))))
            if expand_hashtags:
                for key in sub_keys.get(cid, []):
                    widest = max(widest, len(fmt_cell(sub_cells.get((cid, key, label)))))
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
        if expand_hashtags:
            for key in sub_keys.get(cid, []):
                sub_label = "  " + hashtag_label(list(key), name_map)
                sub_parts = [f"{sub_label:<{name_col_w}}"]
                for label, w in zip(month_labels, col_widths, strict=True):
                    sub_parts.append(f"{fmt_cell(sub_cells.get((cid, key, label))):>{w}}")
                typer.echo("  ".join(sub_parts))

    typer.echo("  ".join(["-" * name_col_w] + ["-" * w for w in col_widths]))
    totals_parts = [f"{'Totals (net)':<{name_col_w}}"]
    for label, w in zip(month_labels, col_widths, strict=True):
        totals_parts.append(f"{fmt_cell(totals_row.get(label)):>{w}}")
    typer.echo("  ".join(totals_parts))


def run_single_month(
    cfg,
    *,
    year: int,
    month: int,
    verbose: bool = False,
    json_mode: bool = False,
    show_hashtags: bool = True,
) -> None:
    """Engine round-trip + render for a single month. Shared by flat + menu."""
    params = {"year": str(year), "month": str(month)}
    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.get("/reports/monthly", params=params)
    _render_single_month(body, json_mode=json_mode, show_hashtags=show_hashtags)


def run_range(
    cfg,
    *,
    from_ym: tuple[int, int],
    to_ym: tuple[int, int],
    verbose: bool = False,
    json_mode: bool = False,
    expand_hashtags: bool = False,
) -> None:
    """Engine round-trip + render for a month range. Shared by flat + menu.

    Caller is responsible for span validation (use _months_between + _MAX_RANGE_MONTHS).
    """
    params = {
        "from_year": str(from_ym[0]),
        "from_month": str(from_ym[1]),
        "to_year": str(to_ym[0]),
        "to_month": str(to_ym[1]),
    }
    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.get("/reports/monthly", params=params)
    _render_range_table(body, json_mode=json_mode, expand_hashtags=expand_hashtags)


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
        run_single_month(cfg, year=year, month=month, verbose=verbose, json_mode=json_output)
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

    run_range(cfg, from_ym=from_ym, to_ym=to_ym, verbose=verbose, json_mode=json_output)
