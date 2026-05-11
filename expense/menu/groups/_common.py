"""Shared prompt helpers across menu group flows (Step 9.5.3+).

Extracted from log.py once Inbox became the second flow phase. Every
helper here is intra-package public (no leading underscore) and consumed
by sibling modules (log.py, inbox.py, future 9.5.4+ phases).
"""

import questionary
import typer

from expense.dates import to_canonical_aware


def prompt_title() -> str | None:
    """Required title prompt. Returns None on Ctrl-C."""
    answer = questionary.text(
        "Title",
        validate=lambda raw: True if raw.strip() else "Title is required.",
    ).ask()
    if answer is None:
        return None
    return answer.strip()


def prompt_optional_text(label: str) -> str | None:
    """Optional text prompt. Empty input → None. Ctrl-C → None."""
    answer = questionary.text(f"{label} (skip)").ask()
    if answer is None:
        return None
    answer = answer.strip()
    return answer or None


def prompt_date_optional() -> tuple[bool, str | None]:
    """Optional date prompt. Returns (ok, value).

    Empty input → (True, None). Bad parse → (False, None) with stderr hint.
    Ctrl-C → (False, None).
    """
    raw = questionary.text("Date  [now]").ask()
    if raw is None:
        return False, None
    raw = raw.strip()
    if raw == "":
        return True, None
    try:
        return True, to_canonical_aware(raw)
    except typer.BadParameter as exc:
        typer.echo(f"  {exc.message}", err=True)
        return False, None


def prompt_cleared_tri() -> tuple[bool, bool | None]:
    """Cleared tri-state (Default/Yes/No). Returns (ok, bool | None)."""
    answer = questionary.select(
        "Cleared?",
        choices=[
            questionary.Choice(title="Default (unset)", value="unset"),
            questionary.Choice(title="Yes (cleared)", value=True),
            questionary.Choice(title="No (not cleared)", value=False),
        ],
    ).ask()
    if answer is None:
        return False, None
    return True, None if answer == "unset" else bool(answer)


def prompt_exchange_rate() -> tuple[bool, float | None]:
    """Optional positive-float exchange rate. Returns (ok, value)."""

    def _validate(raw: str) -> bool | str:
        if raw == "":
            return True
        try:
            value = float(raw)
        except ValueError:
            return "Must be a number (e.g. 3.75)."
        if value <= 0:
            return "Exchange rate must be positive."
        return True

    raw = questionary.text("Override exchange rate? (skip)", validate=_validate).ask()
    if raw is None:
        return False, None
    raw = raw.strip()
    if raw == "":
        return True, None
    return True, float(raw)


def prompt_yes_no(message: str, *, default_no: bool = True) -> bool | None:
    """Binary select. Returns True/False, or None on Ctrl-C."""
    answer = questionary.select(
        message,
        choices=[
            questionary.Choice(title="No", value=False),
            questionary.Choice(title="Yes", value=True),
        ],
        default="No" if default_no else "Yes",
    ).ask()
    return answer


def print_recap(command: str, flags: list[tuple[str, str | None]]) -> None:
    """Print the equivalent flat-command invocation for audit.

    `command` is the verb path (e.g. "log", "inbox add", "inbox update <id>").
    `flags` is an ordered list of (flag_name, value) tuples. value=None drops
    the flag; value="" emits a bare flag (e.g. ("--transfer", "")). Quoting
    is the caller's responsibility — pre-quote string values in the tuple.
    """
    pieces: list[str] = []
    for flag, value in flags:
        if value is None:
            continue
        if value == "":
            pieces.append(f"    {flag}")
        else:
            pieces.append(f"    {flag} {value}")
    typer.echo("")
    typer.echo("About to call:")
    if not pieces:
        typer.echo(f"  expense {command}")
        typer.echo("")
        return
    typer.echo(f"  expense {command} \\")
    for i, piece in enumerate(pieces):
        if i == len(pieces) - 1:
            typer.echo(piece)
        else:
            typer.echo(piece + " \\")
    typer.echo("")


def pause() -> None:
    """Pause at end of a flow before returning to parent menu."""
    questionary.text("Press Enter to return").ask()
