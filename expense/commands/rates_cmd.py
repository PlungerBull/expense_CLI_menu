import json

import typer

from expense import config as config_module
from expense.commands._resource import (
    JSON_OPT,
    LIMIT_OPT,
    OFFSET_OPT,
    effective_limit,
    items_of,
    render_table,
)
from expense.context import get_verbose
from expense.currencies import RATE_SCALE
from expense.errors import EngineError, handle_errors
from expense.http import ExpenseClient

app = typer.Typer(help="Exchange rates.", no_args_is_help=True)


# Display precision, in decimal places. The engine stores 8 (RATE_SCALE); the
# approved mockup shows 4, which is where a USD/PEN rate stops being meaningful
# to read. Kept separate from RATE_SCALE because they answer different
# questions — one is storage fidelity, the other is how much of it is worth
# rendering.
_RATE_DISPLAY_PLACES = 4
_RATE_DISPLAY_DIVISOR = RATE_SCALE // (10**_RATE_DISPLAY_PLACES)


def format_rate(value: object) -> str:
    """4-decimal display for the engine's `rate_e8` integers: 335187273 → `3.3519`.

    Integer arithmetic throughout — no float division — matching
    `_resource.format_cents`. The engine's wire field became `rate_e8: int` in
    sql/036 (it was `rate: float`, the last float on the money path), so there is
    nothing to convert from and nothing to lose here: the halving-and-rounding
    happens on integers and the result is assembled as text.

    Rates are CHECK-positive engine-side, so no sign handling. A non-int value is
    echoed rather than guessed at — including a float, which would mean the
    engine had regressed to the old wire format and should be visible, not
    quietly formatted as if nothing were wrong.
    """
    if value is None:
        return "—"
    if isinstance(value, bool) or not isinstance(value, int):
        return str(value)
    # Round half-up to the display places, then split. `+ divisor // 2` is the
    # half-up step; it is exact because both operands are integers.
    units = (value + _RATE_DISPLAY_DIVISOR // 2) // _RATE_DISPLAY_DIVISOR
    whole, frac = divmod(units, 10**_RATE_DISPLAY_PLACES)
    return f"{whole}.{frac:0{_RATE_DISPLAY_PLACES}d}"


def _render_rate(body: object) -> None:
    """Human-mode renderer for /v1/exchange-rates responses.

    Generic key/value iteration so additional engine fields (provider,
    source, fetched_at, …) render without a code change.

    `rate_e8` is the one key that gets special handling, because it is the one
    key whose raw form is unreadable: the engine sends the rate x RATE_SCALE
    (sql/036), so generic echo would print `rate_e8: 335187273`. It renders as
    `rate: 3.3519` — the same line this command printed before the engine's wire
    format changed. `--json` is unaffected and still shows the raw integer.
    """
    if isinstance(body, dict):
        for key, value in body.items():
            if key == "rate_e8":
                typer.echo(f"  rate: {format_rate(value)}")
                continue
            display = value if value is not None else "(null)"
            typer.echo(f"  {key}: {display}")
    else:
        typer.echo(json.dumps(body, indent=2))


def fetch_rate(
    cfg,
    *,
    target: str,
    base: str | None = None,
    date: str | None = None,
    verbose: bool = False,
) -> dict:
    """GET /v1/exchange-rates (engine-direct). Returns the raw response body.

    `base` / `date` are omitted when None so the engine defaults (USD, today)
    apply. Shared by the typer command and the TUI Rates screen.
    """
    params: dict = {"target": target}
    if base is not None:
        params["base"] = base
    if date is not None:
        params["date"] = date

    with ExpenseClient(cfg, verbose=verbose) as client:
        return client.get("/exchange-rates", params=params)


def rate_is_stale(body: dict) -> bool | None:
    """True when the requested day has no rate row of its own.

    Engine contract, `engine-spec.md` "Staleness: `rate_date` is the signal":
    `GET /exchange-rates` returns both the day you asked about (`date`) and the
    day of the row it actually used (`rate_date`), and `rate_date < date` means
    the figure is being carried forward. That one comparison covers every way
    rate ingestion can fail — provider down, machine asleep, job crashed, or a
    rate refused as implausible by the engine's plausibility guard — which is
    why the engine exposes no bespoke staleness field for a client to read.

    Returns None when the body carries no usable pair of dates. That is the
    "don't know" answer, and callers must render nothing rather than guess: a
    shape change should go quiet, never cry wolf.

    String comparison is deliberate — both fields are ISO `YYYY-MM-DD`, which
    sorts lexicographically, and parsing them would only add a failure mode.
    """
    asked, used = body.get("date"), body.get("rate_date")
    if not isinstance(asked, str) or not isinstance(used, str):
        return None
    return used < asked


def fetch_rate_staleness(cfg, *, target: str, verbose: bool = False) -> bool | None:
    """Whether today's rate for `target` is missing — True/False, or None if unknown.

    A `404` is the same condition at its extreme (no rate at all on or before
    today) and counts as stale, per the engine spec. Every other engine error is
    a question about the engine rather than about the rate, so it answers None.

    Connection and config failures are deliberately not caught here: only the
    caller knows whether going quiet is the right response to being offline.
    """
    try:
        return rate_is_stale(fetch_rate(cfg, target=target, verbose=verbose))
    except EngineError as err:
        return True if err.status == 404 else None


def fetch_rates_history(
    cfg,
    *,
    date: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    verbose: bool = False,
) -> dict:
    """GET /v1/exchange-rates/history (engine-direct). Raw response body.

    Stored daily rates, newest first (`rate_date DESC, base, target`), one row
    per pair per day; `date` is an exact-day filter — no fallback semantics.
    Shared by the typer command and the TUI Rates screen.
    """
    params: dict = {}
    if date is not None:
        params["date"] = date
    if limit is not None:
        params["limit"] = str(limit)
    if offset is not None:
        params["offset"] = str(offset)

    with ExpenseClient(cfg, verbose=verbose) as client:
        return client.get("/exchange-rates/history", params=params or None)


@app.command("list")
@handle_errors
def list_(
    ctx: typer.Context,
    date: str | None = typer.Option(
        None,
        "--date",
        help="Exact ISO date (YYYY-MM-DD) to show a single day. Omit for full history.",
    ),
    limit: int | None = LIMIT_OPT,
    offset: int | None = OFFSET_OPT,
    json_output: bool = JSON_OPT,
) -> None:
    """GET /v1/exchange-rates/history. Engine-direct (not cached).

    Stored daily rates, newest first, one row per currency pair per day.

    Example: expense rates list --date 2026-07-04
    """
    cfg = config_module.ensure_loaded()
    limit = effective_limit(limit, json_mode=json_output)
    body = fetch_rates_history(cfg, date=date, limit=limit, offset=offset, verbose=get_verbose(ctx))
    if json_output:
        typer.echo(json.dumps(body, indent=2))
        return
    items = items_of(body)
    if not items:
        typer.echo(f"No rates stored for {date}." if date else "No rates stored yet.")
        return
    render_table(
        {"rate_date": "Date", "base": "Base", "target": "Target", "rate": "Rate"},
        [
            {
                "rate_date": str(it.get("rate_date") or "—"),
                "base": str(it.get("base") or "—"),
                "target": str(it.get("target") or "—"),
                "rate": format_rate(it.get("rate_e8")),
            }
            for it in items
        ],
        align_right={"rate"},
    )
    total = body.get("total")
    if isinstance(total, int):
        typer.echo(f"\nshowing {len(items)} of {total} · newest first")


@app.command("get")
@handle_errors
def get(
    ctx: typer.Context,
    target: str = typer.Option(..., "--target", help="Target currency code (e.g. EUR)."),
    base: str | None = typer.Option(
        None,
        "--base",
        help="Base currency code. Engine default is USD.",
    ),
    date: str | None = typer.Option(
        None,
        "--date",
        help=(
            "ISO date (YYYY-MM-DD). Engine defaults to today; falls back to "
            "the most recent prior rate."
        ),
    ),
    json_output: bool = JSON_OPT,
) -> None:
    """GET /v1/exchange-rates. Engine-direct (not cached).

    Example: expense rates get --target EUR --date 2026-04-01
    """
    cfg = config_module.ensure_loaded()
    body = fetch_rate(cfg, target=target, base=base, date=date, verbose=get_verbose(ctx))

    if json_output:
        typer.echo(json.dumps(body, indent=2))
        return
    _render_rate(body)
