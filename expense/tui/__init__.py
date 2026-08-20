"""Interactive TUI — `expense world` (Phase 0 walking skeleton).

A retained-mode Textual app over the same engine/command layer the flat CLI
uses (zero business logic here). The entry point is kept light: `world_command`
imports Textual lazily so plain `expense <cmd>` invocations don't pay the cost.
See [docs/tui.md](../../docs/tui.md).
"""

import typer


def world_command(ctx: typer.Context) -> None:
    """Open the interactive TUI.

    Example: expense world
    """
    from expense.tui.app import run_world

    run_world(ctx)


__all__ = ["world_command"]
