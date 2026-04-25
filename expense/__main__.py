import typer

from expense import __version__
from expense.commands import (
    accounts_cmd,
    auth_cmd,
    categories_cmd,
    config_cmd,
    hashtags_cmd,
    ping_cmd,
)
from expense.context import AppContext

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
) -> None:
    """The Hands — expense_world_engine CLI."""
    ctx.obj = AppContext(verbose=verbose)


@app.command()
def version() -> None:
    """Print the CLI version."""
    typer.echo(__version__)


app.add_typer(config_cmd.app, name="config")
app.add_typer(auth_cmd.app, name="auth")
app.add_typer(accounts_cmd.app, name="accounts")
app.add_typer(categories_cmd.app, name="categories")
app.add_typer(hashtags_cmd.app, name="hashtags")
app.command("ping")(ping_cmd.ping)
app.command("whoami")(auth_cmd.whoami)


if __name__ == "__main__":
    app()
