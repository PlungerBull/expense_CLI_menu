"""Shared cell renderables for list rows."""

from rich.text import Text

from expense.commands._resource import format_cents
from expense.tui.theme import Palette


def swatch(color: object) -> Text:
    """A ` ██ ` color swatch in the given `#RRGGBB`, or a dim em-dash if unset."""
    if isinstance(color, str) and len(color) == 7 and color.startswith("#"):
        return Text("██", style=color)
    return Text("—", style="dim")


def amount_cell(cents: object, palette: Palette | None, rule: str) -> str | Text:
    """`format_cents`, sign-colored per `rule` when a palette is given.

    Returns the plain string under rule="plain", palette=None, or non-int cents,
    so palette-less callers (and their equality-asserting tests) see today's
    output unchanged. "sign" colors both directions; "income-only" only ≥ 0.
    """
    text = format_cents(cents)
    if palette is None or rule == "plain" or not isinstance(cents, int):
        return text
    if cents >= 0:
        return Text(text, style=palette.success)
    return Text(text, style=palette.error) if rule == "sign" else text
