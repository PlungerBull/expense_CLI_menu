"""Menu flows for the Sync group (Step 9.5.13).

Two flag-preset wrappers over `expense sync`:
  - Refresh (delta sync)
  - Full rebuild (--full)

Each renders the per-resource count summary via the same renderers the
flat command uses. The submenu also prints a `Last synced:` header line
above the picker so the user can see whether the replica is fresh.

In stateless mode (`--no-cache` / `EXPENSE_STATELESS=1`), both actions
route through the same stateless full-snapshot path the flat command
uses, and the header reflects that no local cache is in play.
"""

from datetime import UTC, datetime

import questionary
import typer

from expense import cache as cache_pkg
from expense import config as config_module
from expense.cache import db as cache_db
from expense.cache import state as cache_state
from expense.commands import sync_cmd
from expense.context import get_no_cache, get_verbose
from expense.errors import EngineConnectionError, EngineError, render
from expense.http import ExpenseClient
from expense.menu import prompts
from expense.menu.groups import _common as common
from expense.menu.term import clear_screen

BACK_LABEL = "← Back"


def run_sync_menu(ctx: typer.Context) -> None:
    """Sync sub-menu loop with a last-synced header above the picker."""
    while True:
        clear_screen()
        _print_header(ctx)
        try:
            choice = questionary.select(
                "Sync — what do you like to do?",
                choices=[
                    "Refresh (delta sync)",
                    "Full rebuild (--full)",
                    BACK_LABEL,
                ],
            ).ask()
        except KeyboardInterrupt:
            return
        if choice is None or choice == BACK_LABEL:
            return
        handler = _HANDLERS.get(choice)
        if handler is None:
            continue
        clear_screen()
        try:
            handler(ctx)
        except typer.Exit:
            pass


# --------------------------------------------------------------- header


def _print_header(ctx: typer.Context) -> None:
    """Render the `Last synced: …` line shown above the picker."""
    if get_no_cache(ctx):
        typer.echo("Last synced: (stateless mode — no local cache)")
        typer.echo("")
        return
    if not cache_db.cache_path().exists():
        typer.echo("Last synced: (no local cache yet — Refresh will cold-start)")
        typer.echo("")
        return
    try:
        conn = cache_db.connect()
        try:
            st = cache_state.read(conn)
        finally:
            conn.close()
    except Exception:
        typer.echo("Last synced: (cache unreadable — Refresh will cold-start)")
        typer.echo("")
        return
    if st.last_synced_at is None or not st.sync_token:
        typer.echo("Last synced: (no sync yet — Refresh will cold-start)")
        typer.echo("")
        return
    token_tail = st.sync_token[-6:] if len(st.sync_token) >= 6 else st.sync_token
    typer.echo(f"Last synced: {st.last_synced_at}  token …{token_tail}")
    typer.echo("")


# --------------------------------------------------------------- shared


def _stateless_snapshot(client: ExpenseClient) -> None:
    pulled_at = datetime.now(UTC)
    body = client.get(
        "/sync",
        params={"sync_token": "*", "debit_as_negative": "true"},
    )
    sync_cmd._render_stateless(body, pulled_at, json_mode=False)


# --------------------------------------------------------------- 1. Refresh


def run_refresh(ctx: typer.Context) -> None:
    """Bare `expense sync` — delta sync (or cold-start on first run)."""
    common.print_recap("sync", [])
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)
    no_cache = get_no_cache(ctx)
    try:
        with ExpenseClient(cfg, verbose=verbose, cold_start_notice=True) as client:
            if no_cache:
                _stateless_snapshot(client)
            else:
                summary = cache_pkg.delta_sync(client, cfg)
                if summary.kind == "cold_start":
                    sync_cmd._render_cache_cold_start(summary, json_mode=False)
                else:
                    sync_cmd._render_cache_delta(summary, json_mode=False)
    except (EngineError, EngineConnectionError) as err:
        output, _exit_code, use_stderr = render(err, json_mode=False)
        typer.echo(output, err=use_stderr)
    common.pause()


# --------------------------------------------------------------- 2. Full rebuild


def run_full_rebuild(ctx: typer.Context) -> None:
    """`expense sync --full` — confirmed wipe + cold-start."""
    confirmed = prompts.confirm_destructive(
        "Full rebuild — continue?",
        warning=(
            "Wipes your local cache and re-pulls everything from the engine. "
            "Recoverable (engine still has all your data), but slower than a delta refresh."
        ),
    )
    if not confirmed:
        typer.echo("Aborted.")
        common.pause()
        return
    common.print_recap("sync", [("--full", "")])
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)
    no_cache = get_no_cache(ctx)
    try:
        with ExpenseClient(cfg, verbose=verbose, cold_start_notice=True) as client:
            if no_cache:
                _stateless_snapshot(client)
            else:
                summary = cache_pkg.cold_start(client, cfg)
                sync_cmd._render_cache_cold_start(summary, json_mode=False)
    except (EngineError, EngineConnectionError) as err:
        output, _exit_code, use_stderr = render(err, json_mode=False)
        typer.echo(output, err=use_stderr)
    common.pause()


# --------------------------------------------------------------- dispatch

_HANDLERS = {
    "Refresh (delta sync)": run_refresh,
    "Full rebuild (--full)": run_full_rebuild,
}
