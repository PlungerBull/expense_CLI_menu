"""Shared prompt helpers across menu group flows (Step 9.5.3+).

Extracted from log.py once Inbox became the second flow phase. Every
helper here is intra-package public (no leading underscore) and consumed
by sibling modules (log.py, inbox.py, future 9.5.4+ phases).
"""

from collections.abc import Callable
from datetime import date as date_cls
from datetime import datetime, timedelta

import questionary
import typer

from expense.dates import parse_year_month, to_canonical_aware


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
        default=False if default_no else True,
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


def prompt_validated_text(
    label: str,
    validate: Callable[[str], bool | str],
    *,
    password: bool = False,
) -> str | None:
    """Validated text prompt. Returns the trimmed input, or None on Ctrl-C.

    `validate(raw) -> True | error_message_str` is called synchronously by
    questionary; on a string return value the prompt re-prompts. When
    `password=True` the input is hidden (uses `questionary.password`).
    """
    prompter = questionary.password if password else questionary.text
    answer = prompter(label, validate=validate).ask()
    if answer is None:
        return None
    return answer.strip()


_DATE_PRESETS = [
    "Any date",
    "This month",
    "Last month",
    "Last 30 days",
    "Last 90 days",
    "This year",
    "Custom range…",
]


def _iso(dt: datetime) -> str:
    """Local-aware ISO 8601 with seconds precision, matching dates.now_local_iso."""
    return dt.astimezone().isoformat(timespec="seconds")


def _first_of_month(d: date_cls) -> datetime:
    return datetime(d.year, d.month, 1, 0, 0, 0)


def _last_of_prev_month(today: date_cls) -> datetime:
    first_this = date_cls(today.year, today.month, 1)
    last_prev_d = first_this - timedelta(days=1)
    return datetime(last_prev_d.year, last_prev_d.month, last_prev_d.day, 23, 59, 59)


def prompt_date_range_preset() -> tuple[bool, str | None, str | None]:
    """Date-range filter prompt.

    Returns (ok, date_from_iso, date_to_iso). ok=False signals user aborted.
    All presets compute client-side using the local timezone. Custom range
    forks into two text prompts, each parsed via dates.to_canonical_aware.
    """
    choice = questionary.select("Date range?", choices=_DATE_PRESETS).ask()
    if choice is None:
        return False, None, None

    today = datetime.now().date()
    end_of_today = datetime(today.year, today.month, today.day, 23, 59, 59)

    if choice == "Any date":
        return True, None, None
    if choice == "This month":
        return True, _iso(_first_of_month(today)), _iso(end_of_today)
    if choice == "Last month":
        first_prev = date_cls(today.year, today.month, 1) - timedelta(days=1)
        first_prev = date_cls(first_prev.year, first_prev.month, 1)
        return True, _iso(_first_of_month(first_prev)), _iso(_last_of_prev_month(today))
    if choice == "Last 30 days":
        start = datetime.combine(today - timedelta(days=30), datetime.min.time())
        return True, _iso(start), _iso(end_of_today)
    if choice == "Last 90 days":
        start = datetime.combine(today - timedelta(days=90), datetime.min.time())
        return True, _iso(start), _iso(end_of_today)
    if choice == "This year":
        start = datetime(today.year, 1, 1, 0, 0, 0)
        return True, _iso(start), _iso(end_of_today)

    # Custom range — two text prompts.
    raw_from = questionary.text("From date (YYYY-MM-DD or RFC 3339)").ask()
    if raw_from is None:
        return False, None, None
    raw_to = questionary.text("To date (YYYY-MM-DD or RFC 3339)").ask()
    if raw_to is None:
        return False, None, None
    try:
        df = to_canonical_aware(raw_from.strip()) if raw_from.strip() else None
        dt = to_canonical_aware(raw_to.strip()) if raw_to.strip() else None
    except typer.BadParameter as exc:
        typer.echo(f"  {exc.message}", err=True)
        return False, None, None
    return True, df, dt


def validate_currency_code(raw: str) -> bool | str:
    """questionary validator for ISO 4217 currency codes (3 uppercase letters)."""
    value = raw.strip()
    if not value:
        return "Currency code is required."
    if len(value) != 3 or not value.isalpha() or not value.isupper():
        return "Currency code must be 3 uppercase letters (e.g. USD, PEN)."
    return True


def prompt_year_month(label: str, *, default: str | None = None) -> tuple[bool, str | None]:
    """YYYY-MM prompt. Returns (ok, canonical "YYYY-MM"). Ctrl-C → (False, None)."""

    def _validate(raw: str) -> bool | str:
        try:
            parse_year_month(raw.strip(), param_hint=label)
        except typer.BadParameter as exc:
            return exc.message
        return True

    raw = questionary.text(label, default=default or "", validate=_validate).ask()
    if raw is None:
        return False, None
    year, month = parse_year_month(raw.strip(), param_hint=label)
    return True, f"{year:04d}-{month:02d}"
