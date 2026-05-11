import typer

from expense import __version__
from expense.commands import (
    accounts_cmd,
    activity_cmd,
    auth_cmd,
    categories_cmd,
    config_cmd,
    dashboard_cmd,
    hashtags_cmd,
    inbox_cmd,
    log_cmd,
    ping_cmd,
    rates_cmd,
    reconcile_cmd,
    reports_cmd,
    sync_cmd,
    transactions_cmd,
)
from expense.context import AppContext
from expense.menu import menu_command

app = typer.Typer(
    help="The Hands — expense_world_engine CLI.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main(
    ctx: typer.Context,
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Print HTTP request/response to stderr (Authorization redacted).",
    ),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        envvar="EXPENSE_STATELESS",
        help=(
            "Bypass the local replica; reads go straight to the engine. "
            "Stateless mode for CSV imports, CI, scripts."
        ),
    ),
    no_sync_after: bool = typer.Option(
        False,
        "--no-sync-after",
        envvar="EXPENSE_NO_SYNC_AFTER",
        help=(
            "Skip the post-write delta sync. Useful when batching many writes "
            "in a script that runs `expense sync` once at the end."
        ),
    ),
) -> None:
    """The Hands — expense_world_engine CLI."""
    ctx.obj = AppContext(verbose=verbose, no_cache=no_cache, no_sync_after=no_sync_after)


@app.command()
def version() -> None:
    """Print the CLI version.

    Example: expense version
    """
    typer.echo(__version__)


app.add_typer(config_cmd.app, name="config")
app.add_typer(auth_cmd.app, name="auth")
app.add_typer(accounts_cmd.app, name="accounts")
app.add_typer(categories_cmd.app, name="categories")
app.add_typer(hashtags_cmd.app, name="hashtags")
app.add_typer(inbox_cmd.app, name="inbox")
app.add_typer(transactions_cmd.app, name="transactions")
app.add_typer(reconcile_cmd.app, name="reconcile")
app.add_typer(reports_cmd.app, name="reports")
app.add_typer(activity_cmd.app, name="activity")
app.add_typer(rates_cmd.app, name="rates")
app.command("ping")(ping_cmd.ping)
app.command("whoami")(auth_cmd.whoami)
app.command("log")(log_cmd.log)
app.command("dashboard")(dashboard_cmd.dashboard)
app.command("sync")(sync_cmd.sync)
app.command("menu")(menu_command)


if __name__ == "__main__":
    app()
