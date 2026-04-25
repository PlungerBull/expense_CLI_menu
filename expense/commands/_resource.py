"""Shared helpers for resource sub-apps (accounts, categories, hashtags)."""

import json
import sys
from collections.abc import Callable
from typing import Any

import typer

from expense import config as config_module
from expense.config import Config
from expense.context import get_verbose
from expense.http import ExpenseClient


def require_yes(yes: bool, prompt_text: str) -> None:
    """Enforce explicit confirmation for destructive operations.

    Mirrors the pattern from `auth settings`: in non-TTY mode, --yes is mandatory;
    in TTY mode, prompt the user unless --yes was already passed.
    """
    if yes:
        return
    if not sys.stdin.isatty():
        typer.echo(
            "Error: --yes is required for this operation in non-interactive mode.",
            err=True,
        )
        raise typer.Exit(code=1)
    if not typer.confirm(prompt_text):
        typer.echo("Aborted.")
        raise typer.Exit(code=1)


def build_update_payload(items: dict[str, Any]) -> dict[str, Any]:
    """Drop None values; exit if nothing is left to update."""
    payload = {key: value for key, value in items.items() if value is not None}
    if not payload:
        typer.echo("Error: No fields to update; pass at least one flag.", err=True)
        raise typer.Exit(code=1)
    return payload


def run_toggle(
    ctx: typer.Context,
    *,
    resource: str,
    id_: str,
    verb: str,
    json_output: bool,
    render_human: Callable[[dict], None],
) -> None:
    """Execute one of the {archive, unarchive, restore} toggle verbs.

    All three are POST /{resource}/{id}/{verb} with no body and an identical
    response shape (the resource row).
    """
    cfg: Config = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    with ExpenseClient(cfg, verbose=verbose) as client:
        body = client.post(f"/{resource}/{id_}/{verb}")

    if json_output:
        typer.echo(json.dumps(body, indent=2))
    else:
        render_human(body)
