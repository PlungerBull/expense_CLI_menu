import json
import sys

import typer

from expense import config as config_module
from expense.config import Config
from expense.errors import handle_errors

app = typer.Typer(help="Manage ~/.expense-config", no_args_is_help=True)


@app.command("set")
def set_cmd(
    engine_url: str | None = typer.Option(None, "--engine-url", help="Base URL of the engine."),
    token: str | None = typer.Option(None, "--token", help="PAT (prefix ewe_pat_) or JWT."),
    main_currency: str | None = typer.Option(
        None,
        "--main-currency",
        help="Cached main currency. Usually set automatically by `auth me`.",
    ),
) -> None:
    """Set one or more fields in ~/.expense-config. Creates the file on first run."""
    existing = config_module.load()

    if existing is None:
        if not engine_url:
            raise typer.BadParameter("--engine-url is required on first run.")
        new = Config(
            engine_url=engine_url,
            token=token,
            client_id=config_module.generate_client_id(),
            main_currency=main_currency,
        )
    else:
        new = Config(
            engine_url=engine_url or existing.engine_url,
            token=token if token is not None else existing.token,
            client_id=existing.client_id,
            main_currency=(main_currency if main_currency is not None else existing.main_currency),
        )

    if new.token and not new.token.startswith("ewe_pat_"):
        typer.echo(
            "Warning: token does not start with 'ewe_pat_'; "
            "assuming JWT (will work but PAT is recommended for long-lived use).",
            err=True,
        )

    config_module.save(new)
    typer.echo(f"Config saved to {config_module.config_path()}")


def _redact_token(token: str | None) -> str | None:
    if token is None:
        return None
    if len(token) <= 8:
        return "****"
    return f"{token[:8]}****{token[-4:]}"


@app.command("get")
@handle_errors
def get_cmd(
    show_token: bool = typer.Option(
        False, "--show-token", help="Reveal the token (default: redacted)."
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Print the current config. Token is redacted unless --show-token is passed."""
    cfg = config_module.ensure_loaded()
    data = cfg.model_dump(mode="json")
    if not show_token:
        data["token"] = _redact_token(cfg.token)

    if json_output:
        typer.echo(json.dumps(data, indent=2, sort_keys=True))
    else:
        for key, value in sorted(data.items()):
            display = value if value is not None else "(not set)"
            typer.echo(f"{key}: {display}")


@app.command("clear")
def clear_cmd(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Remove ~/.expense-config."""
    path = config_module.config_path()
    if not path.exists():
        typer.echo("No config file to clear.")
        return

    if not yes:
        if not sys.stdin.isatty():
            typer.echo("Error: --yes is required in non-interactive mode.", err=True)
            raise typer.Exit(code=3)
        if not typer.confirm(f"Remove {path}?"):
            typer.echo("Aborted.")
            raise typer.Exit(code=1)

    config_module.clear()
    typer.echo(f"Config removed: {path}")
