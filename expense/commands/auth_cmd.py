import json
import os
import sys
import zoneinfo
from pathlib import Path

import typer

from expense import config as config_module
from expense.config import Config
from expense.context import get_verbose
from expense.errors import EngineError, handle_errors
from expense.http import ExpenseClient

app = typer.Typer(help="Authentication, identity, and settings.", no_args_is_help=True)


def _detect_timezone() -> str:
    tz_env = os.environ.get("TZ")
    if tz_env:
        try:
            zoneinfo.ZoneInfo(tz_env)
            return tz_env
        except zoneinfo.ZoneInfoNotFoundError:
            pass

    localtime = Path("/etc/localtime")
    if localtime.is_symlink():
        target = str(localtime.resolve())
        marker = "/zoneinfo/"
        if marker in target:
            zone = target.split(marker, 1)[1]
            try:
                zoneinfo.ZoneInfo(zone)
                return zone
            except zoneinfo.ZoneInfoNotFoundError:
                pass

    raise RuntimeError("Could not detect system timezone. Pass --timezone explicitly.")


def _render_user_and_settings(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    user = body.get("user", {}) or {}
    settings = body.get("settings", {}) or {}
    typer.echo("User:")
    for key, value in user.items():
        display = value if value is not None else "(null)"
        typer.echo(f"  {key}: {display}")
    typer.echo("Settings:")
    for key, value in settings.items():
        display = value if value is not None else "(null)"
        typer.echo(f"  {key}: {display}")


def _render_settings_only(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    recalc = body.get("recalculation")
    typer.echo("Settings:")
    for key, value in body.items():
        if key == "recalculation":
            continue
        display = value if value is not None else "(null)"
        typer.echo(f"  {key}: {display}")
    if recalc:
        _render_recalc_summary(recalc)


def _render_recalc_summary(recalc: dict) -> None:
    total = recalc.get("total", 0)
    orphans = recalc.get("orphan_transfer_legs", 0)
    typer.echo("")
    typer.echo(f"Rewrote {total} transaction(s) in home currency.")
    if orphans:
        typer.secho(
            f"  ⚠ {orphans} transfer leg(s) need attention "
            f"(soft-delete orphans — resolve via the transactions API).",
            fg=typer.colors.YELLOW,
        )


def _render_user_only(body: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    typer.echo("User:")
    for key, value in body.items():
        display = value if value is not None else "(null)"
        typer.echo(f"  {key}: {display}")


def _cache_main_currency(cfg: Config, settings: dict) -> None:
    main_currency = settings.get("main_currency") if settings else None
    if main_currency and main_currency != cfg.main_currency:
        updated = cfg.model_copy(update={"main_currency": main_currency})
        config_module.save(updated)


@app.command("bootstrap")
@handle_errors
def bootstrap(
    ctx: typer.Context,
    display_name: str = typer.Option(
        ..., "--display-name", help="Your display name (required on first login)."
    ),
    timezone: str | None = typer.Option(
        None, "--timezone", help="IANA timezone (default: auto-detect from system)."
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """First-login upsert via POST /v1/auth/bootstrap.

    Idempotent within 24h — replays return the first call's response verbatim,
    not a fresh `last_login_at`.

    Example: expense auth bootstrap --display-name "Alex" --timezone America/Lima
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    if timezone is None:
        timezone = _detect_timezone()
        typer.echo(f"Using timezone: {timezone} — override with --timezone", err=True)

    payload = {"display_name": display_name, "timezone": timezone}

    with ExpenseClient(cfg, verbose=verbose, cold_start_notice=True) as client:
        body = client.post("/auth/bootstrap", json_body=payload)

    _cache_main_currency(cfg, body.get("settings", {}))
    _render_user_and_settings(body, json_mode=json_output)


def _me_impl(ctx: typer.Context, json_output: bool) -> None:
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    with ExpenseClient(cfg, verbose=verbose, cold_start_notice=True) as client:
        try:
            body = client.get("/auth/me")
        except EngineError as err:
            if err.status == 404:
                typer.echo(
                    "Run 'expense auth bootstrap' first to create your user record.",
                    err=True,
                )
            raise

    _cache_main_currency(cfg, body.get("settings", {}))
    _render_user_and_settings(body, json_mode=json_output)


@app.command("me")
@handle_errors
def me(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """GET /v1/auth/me. Alias: `whoami` (top-level).

    Example: expense auth me
    """
    _me_impl(ctx, json_output)


@handle_errors
def whoami(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Shortcut for `expense auth me`.

    Example: expense whoami
    """
    _me_impl(ctx, json_output)


@app.command("profile")
@handle_errors
def profile(
    ctx: typer.Context,
    display_name: str | None = typer.Option(
        None, "--display-name", help="New display name. Cannot be cleared (engine rejects null)."
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """PUT /v1/auth/profile. Mutate identity fields on the users row.

    Bootstrap is idempotent and won't overwrite display_name on re-login;
    this is the post-bootstrap path to change it.

    Example: expense auth profile --display-name "Alex Tern"
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    payload: dict = {}
    if display_name is not None:
        payload["display_name"] = display_name

    if not payload:
        typer.echo("Error: No profile fields to update; pass at least one flag.", err=True)
        raise typer.Exit(code=1)

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.put("/auth/profile", json_body=payload)

    _render_user_only(body, json_mode=json_output)


@app.command("settings")
@handle_errors
def settings(
    ctx: typer.Context,
    theme: int | None = typer.Option(None, "--theme", help="Theme index."),
    start_of_week: int | None = typer.Option(
        None, "--start-of-week", help="0=Sunday, 1=Monday, ..."
    ),
    main_currency: str | None = typer.Option(
        None, "--main-currency", help="USD or PEN (engine schema-locked)."
    ),
    transaction_sort_preference: int | None = typer.Option(None, "--transaction-sort-preference"),
    display_timezone: str | None = typer.Option(
        None, "--display-timezone", help="IANA timezone for rendering."
    ),
    sidebar_show_bank_accounts: bool | None = typer.Option(
        None, "--sidebar-show-bank-accounts/--no-sidebar-show-bank-accounts"
    ),
    sidebar_show_people: bool | None = typer.Option(
        None, "--sidebar-show-people/--no-sidebar-show-people"
    ),
    sidebar_show_categories: bool | None = typer.Option(
        None, "--sidebar-show-categories/--no-sidebar-show-categories"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompts."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """PUT /v1/auth/settings. Partial update; main_currency change triggers engine recalc.

    Example: expense auth settings --theme dark --start-of-week monday
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    payload: dict = {}
    for key, value in (
        ("theme", theme),
        ("start_of_week", start_of_week),
        ("main_currency", main_currency),
        ("transaction_sort_preference", transaction_sort_preference),
        ("display_timezone", display_timezone),
        ("sidebar_show_bank_accounts", sidebar_show_bank_accounts),
        ("sidebar_show_people", sidebar_show_people),
        ("sidebar_show_categories", sidebar_show_categories),
    ):
        if value is not None:
            payload[key] = value

    if not payload:
        typer.echo("Error: No settings to update; pass at least one flag.", err=True)
        raise typer.Exit(code=1)

    if main_currency is not None and not yes:
        if not sys.stdin.isatty():
            typer.echo(
                "Error: --yes is required for --main-currency changes in non-interactive mode.",
                err=True,
            )
            raise typer.Exit(code=1)
        if not typer.confirm(
            "Changing main_currency triggers synchronous home-currency "
            "recalculation on the engine. Continue?"
        ):
            typer.echo("Aborted.")
            raise typer.Exit(code=1)

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.put("/auth/settings", json_body=payload)

    if "main_currency" in payload:
        _cache_main_currency(cfg, body)

    _render_settings_only(body, json_mode=json_output)
