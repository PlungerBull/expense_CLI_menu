import typer

from expense import __version__

app = typer.Typer(
    help="The Hands — expense_world_engine CLI.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main() -> None:
    """The Hands — expense_world_engine CLI."""


@app.command()
def version() -> None:
    """Print the CLI version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
