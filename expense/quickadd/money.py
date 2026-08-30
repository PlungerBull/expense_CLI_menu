"""Money as text — the decimal string a human types, and its inverse.

Moved here from expense/tui/screens/quick_log.py 2026-08-25: the quick-add
grammar needs to read an amount out of a line, and the staged-row round trip
needs to write one back into it. Behaviour is unchanged.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from expense.currencies import MINOR_UNIT_SCALE


def parse_amount(text: str) -> int | None:
    """`-99.92` → -9992 cents. None if unparseable. Sign is explicit."""
    text = text.strip().replace(",", "")
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return int((value * MINOR_UNIT_SCALE).to_integral_value(rounding=ROUND_HALF_UP))


def amount_to_text(cents: int) -> str:
    """Cents → an editable decimal string (no grouping): -9992 → '-99.92'."""
    return str(Decimal(cents) / MINOR_UNIT_SCALE)
