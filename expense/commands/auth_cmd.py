import json
from pathlib import Path

import typer

from expense import config as config_module
from expense import dates
from expense.commands._resource import JSON_OPT
from expense.config import Config
from expense.context import get_verbose
from expense.errors import EngineError, handle_errors
from expense.http import ExpenseClient

app = typer.Typer(help="Authentication, identity, and settings.", no_args_is_help=True)


def _detect_timezone(localtime: Path = Path("/etc/localtime")) -> str:
    # Detection lives in expense.dates (shared with the TUI, backlog 6.2d);
    # BadParameter (a click UsageError) so the CLI renders "Error: ..." and
    # exits 2 instead of a raw traceback — the remedy is a flag the user holds.
    try:
        return dates.detect_timezone(localtime)
    except dates.TimezoneDetectionError as exc:
        raise typer.BadParameter(
            "Could not detect system timezone. Pass --timezone explicitly.",
            param_hint="--timezone",
        ) from exc


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
    typer.echo("Settings:")
    for key, value in body.items():
        display = value if value is not None else "(null)"
        typer.echo(f"  {key}: {display}")


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
    json_output: bool = JSON_OPT,
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

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.post("/auth/bootstrap", json_body=payload)

    _cache_main_currency(cfg, body.get("settings", {}))
    _render_user_and_settings(body, json_mode=json_output)


def _me_impl(ctx: typer.Context, json_output: bool) -> None:
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    with ExpenseClient(cfg, verbose=verbose) as client:
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
    json_output: bool = JSON_OPT,
) -> None:
    """GET /v1/auth/me. Alias: `whoami` (top-level).

    Example: expense auth me
    """
    _me_impl(ctx, json_output)


@handle_errors
def whoami(
    ctx: typer.Context,
    json_output: bool = JSON_OPT,
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
    json_output: bool = JSON_OPT,
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
    display_timezone: str | None = typer.Option(
        None, "--display-timezone", help="IANA timezone for rendering."
    ),
    json_output: bool = JSON_OPT,
) -> None:
    """PUT /v1/auth/settings. display_timezone is the only mutable field.

    The home currency is locked engine-side (2026-08-01) and the display
    preferences (theme, sort, sidebar) were removed in the 2026-08-06 schema
    slimming — the engine rejects any other field with 422.

    Example: expense auth settings --display-timezone America/Lima
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    if display_timezone is None:
        typer.echo("Error: No settings to update; pass at least one flag.", err=True)
        raise typer.Exit(code=1)

    payload = {"display_timezone": display_timezone}

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.put("/auth/settings", json_body=payload)

    _render_settings_only(body, json_mode=json_output)
