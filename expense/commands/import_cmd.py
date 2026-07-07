"""`expense import <file>` — bulk-import transactions from an .xlsx.

Dry-run by default: parses the sheet and prints what it would do, writing
nothing. With --apply, resolves-or-creates accounts/categories/hashtags by name
and writes transactions through the atomic batch endpoint.
"""

import json
from collections import Counter, defaultdict

import typer

from expense import config as config_module
from expense.commands._resource import cache_after_write
from expense.context import get_verbose
from expense.errors import handle_errors
from expense.http import ExpenseClient
from expense.import_ import apply as apply_mod
from expense.import_ import plan as plan_mod
from expense.import_.parse import ImportFormatError, parse_sheet
from expense.import_.reader import ImportDependencyError, ImportFileError, read_workbook


# sanctioned exception — see cli-spec.md "Sanctioned exceptions": import's
# --json (plan and result below) is client-composed; the pipeline aggregates
# many engine calls, so there is no single engine response to pass through.
def _render_plan(plan: plan_mod.ImportPlan, *, json_output: bool) -> None:
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "valid_rows": len(plan.rows),
                    "skipped": [
                        {"line": s.line, "reason": s.reason, "detail": s.detail}
                        for s in plan.skipped
                    ],
                    "accounts": [{"name": a.name, "currency": a.currency} for a in plan.accounts],
                    "categories": plan.categories,
                    "hashtags": plan.hashtags,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    typer.echo(f"Parsed {len(plan.rows)} transactions to import.")
    if plan.skipped:
        counts = Counter(s.reason for s in plan.skipped)
        detail = ", ".join(f"{reason}: {n}" for reason, n in sorted(counts.items()))
        typer.echo(f"Skipped {len(plan.skipped)} row(s) — {detail}")

    by_name: dict[str, list[str]] = defaultdict(list)
    for spec in plan.accounts:
        by_name[spec.name].append(spec.currency)
    typer.echo(f"\nAccounts to ensure ({len(plan.accounts)}):")
    for name in sorted(by_name):
        currencies = sorted(by_name[name])
        flag = "  (split by currency)" if len(currencies) > 1 else ""
        typer.echo(f"  {name} [{', '.join(currencies)}]{flag}")

    typer.echo(f"\nCategories to ensure ({len(plan.categories)}):")
    typer.echo(f"  {', '.join(sorted(plan.categories))}")
    typer.echo(f"\nHashtags to ensure ({len(plan.hashtags)}):")
    typer.echo(f"  {', '.join(sorted(plan.hashtags))}")


def _render_result(result: apply_mod.ApplyResult, *, json_output: bool) -> None:
    res = result.resolve
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "accounts_created": res.accounts_created,
                    "accounts_reused": res.accounts_reused,
                    "categories_created": res.categories_created,
                    "categories_reused": res.categories_reused,
                    "hashtags_created": res.hashtags_created,
                    "hashtags_reused": res.hashtags_reused,
                    "tx_created": result.tx_created,
                    "tx_skipped_existing": result.tx_skipped_existing,
                    "tx_failed": result.tx_failed,
                    "failures": [{"chunk": c, "error": m} for c, m in result.failures],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    typer.echo(f"Accounts:   created {res.accounts_created}, reused {res.accounts_reused}")
    typer.echo(f"Categories: created {res.categories_created}, reused {res.categories_reused}")
    typer.echo(f"Hashtags:   created {res.hashtags_created}, reused {res.hashtags_reused}")
    typer.echo(
        f"Transactions: created {result.tx_created}, "
        f"already-present {result.tx_skipped_existing}, failed {result.tx_failed}"
    )
    if result.failures:
        typer.echo("Failures:")
        for chunk_index, message in result.failures:
            typer.echo(f"  chunk {chunk_index}: {message}")


@handle_errors
def run_import(
    ctx: typer.Context,
    file: str = typer.Argument(..., help="Path to the .xlsx spreadsheet to import."),
    apply: bool = typer.Option(
        False, "--apply", help="Actually write to the engine. Default is a dry-run preview."
    ),
    chunk_size: int = typer.Option(
        200, "--chunk-size", min=1, max=500, help="Transactions per batch request."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit the plan/result as JSON."),
) -> None:
    """Import transactions from an .xlsx spreadsheet (dry-run by default).

    Parses the sheet, then resolves-or-creates accounts/categories/hashtags by
    name and writes transactions in atomic batches. Without --apply it only
    prints what it would do and writes nothing.

    Re-running --apply is safe for unchanged and appended sheets: transaction
    ids derive from each row's content plus its line number, so already-imported
    rows are skipped and new rows still land (a chunk mixing both falls back to
    row-by-row posts). Inserting or deleting rows mid-sheet shifts every later
    line number — shifted rows get new ids and re-import as duplicates; append
    new rows at the bottom instead. Full re-runs of large already-imported
    sheets are slower (one request per row).

    Example: expense import ~/Downloads/Presupuesto.xlsx
    """
    try:
        sheet = read_workbook(file)
        parsed, skipped = parse_sheet(sheet)
    except (ImportDependencyError, ImportFileError, ImportFormatError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    plan = plan_mod.build_plan(parsed, skipped)

    if not apply:
        _render_plan(plan, json_output=json_output)
        if not json_output:
            typer.echo("\nDry run — nothing written. Re-run with --apply to write.")
        return

    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)
    # Batches of up to `chunk_size` rows can take a while on a cold/slow engine;
    # give the read timeout plenty of headroom beyond the 60s default.
    with ExpenseClient(cfg, verbose=verbose, cold_start_notice=True, timeout_read=300.0) as client:
        res = apply_mod.resolve_or_create(client, plan)
        result = apply_mod.apply_plan(client, plan, res, chunk_size=chunk_size)
        cache_after_write(ctx, client, cfg)

    _render_result(result, json_output=json_output)
    if result.tx_failed > 0:
        raise typer.Exit(code=1)
