"""Terminal-control helpers for the interactive `expense menu` shell.

Kept separate from `groups/_common.py` (prompt helpers) so the two
concerns don't grow into each other.
"""

import os
import sys

import click

# Anything outside this set, after lowercasing, is treated as truthy.
# Matches the spirit of Click's bool coercion so EXPENSE_NO_CLEAR
# parses the same way EXPENSE_NO_SYNC_AFTER does via Typer's envvar=.
_FALSY = {"", "0", "false", "no"}


def clear_screen() -> None:
    """Clear the terminal viewport. No-op when stdout isn't a TTY or
    when ``EXPENSE_NO_CLEAR`` is set to a truthy value.

    Uses ``click.clear()`` (``\\x1b[2J\\x1b[H``) — clears the visible
    viewport but leaves scrollback intact, so users can scroll up to
    review prior menu output (including ``print_recap()`` lines).
    """
    if os.environ.get("EXPENSE_NO_CLEAR", "").lower() not in _FALSY:
        return
    if not sys.stdout.isatty():
        return
    click.clear()
