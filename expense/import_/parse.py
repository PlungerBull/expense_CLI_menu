"""Pure parsing: RawRow -> ParsedRow | SkippedRow. No I/O, no HTTP.

Handles Excel serial dates, decimal->signed-cents conversion (float-artifact
safe via Decimal), and currency validation. A T.C. (tipo de cambio) column, if
present, is ignored — the engine converts currency at read time and rejects
per-row rates (2026-08-05 engine rework).
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from expense.import_ import mapping
from expense.import_.reader import RawRow, SheetData

EXCEL_EPOCH = date(1899, 12, 30)


@dataclass(frozen=True)
class ParsedRow:
    line: int
    title: str
    category: str
    hashtag: str
    date_iso: str
    amount_cents: int
    currency: str
    account: str
    description: str | None


@dataclass(frozen=True)
class OpeningRow:
    """A SALDO INICIAL row — routed to POST /accounts/{id}/opening-balance.

    Detected by title (case/whitespace-insensitive). Category and hashtag are
    deliberately absent: the engine assigns the @Opening system category, and
    spreadsheets typically leave those cells blank on opening rows.
    """

    line: int
    title: str
    account: str
    currency: str
    date_iso: str
    amount_cents: int


@dataclass(frozen=True)
class SkippedRow:
    line: int
    reason: str
    detail: str = ""


#: Titles that mark a row as an opening balance, normalized via
#: ``_normalize_title`` (casefold + collapsed whitespace).
OPENING_TITLES = frozenset({"saldo inicial"})

#: Categories that mark a row as an opening balance. Sheets disagree on which
#: column carries the marker — some title the row "Saldo Inicial", others give
#: it a descriptive title and file it under a SALDO INICIAL category. Either
#: marker routes the row to the opening-balance endpoint; the category itself
#: is then discarded (the engine assigns @Opening), so the marker never becomes
#: a real user category.
OPENING_CATEGORIES = frozenset({"saldo inicial"})


def _normalize_title(title: str) -> str:
    return " ".join(title.split()).casefold()


def is_opening_title(title: str) -> bool:
    return _normalize_title(title) in OPENING_TITLES


def is_opening_category(category: str | None) -> bool:
    return category is not None and _normalize_title(category) in OPENING_CATEGORIES


class ImportFormatError(Exception):
    """The header row is missing one or more required columns."""


def build_column_index(headers: list[object]) -> dict[str, int]:
    """Map each canonical field to its column index by matching header labels."""
    norm = [mapping.normalize_header(h) for h in headers]
    index: dict[str, int] = {}
    for field, labels in mapping.FIELD_HEADERS.items():
        for label in labels:
            if label in norm:
                index[field] = norm.index(label)
                break
    missing = mapping.REQUIRED_FIELDS - index.keys()
    if missing:
        wanted = ", ".join(sorted(mapping.FIELD_HEADERS[m][0] for m in missing))
        found = ", ".join(str(h) for h in headers if h is not None)
        raise ImportFormatError(
            f"Spreadsheet is missing required column(s): {wanted}. Found headers: {found}"
        )
    return index


def _clean(value: object) -> str | None:
    """Trim a cell; treat ``''`` and the literal ``'None'`` as empty."""
    if value is None:
        return None
    s = str(value).strip()
    if s == "" or s.casefold() == "none":
        return None
    return s


def serial_to_iso(serial: object) -> str:
    """Excel serial day number -> ``YYYY-MM-DD`` (epoch 1899-12-30)."""
    days = int(float(serial))
    return (EXCEL_EPOCH + timedelta(days=days)).isoformat()


def to_iso_date(value: object) -> str | None:
    """Coerce a date cell to ``YYYY-MM-DD``.

    Handles datetime/date objects, Excel serial day-numbers (int, float, or a
    numeric string), and ISO-formatted **text** cells (``2022-12-01`` or
    ``2022-12-01 10:30``). The text branch is why a column typed as text still
    imports instead of being dropped as ``bad-date``. Numeric-string serials
    (e.g. ``"46170"``) fail ISO parsing and fall through to the serial path,
    which preserves their existing handling.
    """
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        text = value.strip()
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(text).date().isoformat()
        except ValueError:
            pass
    try:
        return serial_to_iso(value)
    except (TypeError, ValueError):
        return None


def amount_to_cents(value: object) -> int:
    """Signed decimal -> signed integer cents, float-artifact safe.

    ``-132.80000000000001`` -> ``-13280``.
    """
    cents = Decimal(str(value)).scaleb(2)
    return int(cents.to_integral_value(rounding=ROUND_HALF_UP))


def parse_row(raw: RawRow, index: dict[str, int]) -> ParsedRow | OpeningRow | SkippedRow:
    def cell(field: str) -> object:
        i = index.get(field)
        if i is None or i >= len(raw.cells):
            return None
        return raw.cells[i]

    title = _clean(cell("title"))
    account = _clean(cell("account"))
    category = _clean(cell("category"))
    hashtag = _clean(cell("hashtag"))
    currency_raw = _clean(cell("currency"))

    if title is None:
        return SkippedRow(raw.line, "missing-title")
    opening = is_opening_title(title) or is_opening_category(category)
    if account is None:
        return SkippedRow(raw.line, "missing-account")
    # Opening rows skip the category/hashtag requirement — the engine assigns
    # the @Opening system category, and sheets leave those cells blank.
    if not opening and category is None:
        return SkippedRow(raw.line, "missing-category")
    if not opening and hashtag is None:
        return SkippedRow(raw.line, "missing-hashtag")
    if currency_raw is None:
        return SkippedRow(raw.line, "missing-currency")

    currency = currency_raw.upper()
    if currency not in mapping.VALID_CURRENCIES:
        return SkippedRow(raw.line, "unknown-currency", currency)

    date_iso = to_iso_date(cell("date"))
    if date_iso is None:
        return SkippedRow(raw.line, "bad-date", str(cell("date")))

    try:
        amount_cents = amount_to_cents(cell("amount"))
    except (InvalidOperation, ValueError, TypeError):
        return SkippedRow(raw.line, "bad-amount", str(cell("amount")))
    if amount_cents == 0:
        return SkippedRow(raw.line, "zero-amount")

    if opening:
        return OpeningRow(
            line=raw.line,
            title=title,
            account=account,
            currency=currency,
            date_iso=date_iso,
            amount_cents=amount_cents,
        )

    return ParsedRow(
        line=raw.line,
        title=title,
        category=category,
        hashtag=hashtag,
        date_iso=date_iso,
        amount_cents=amount_cents,
        currency=currency,
        account=account,
        description=_clean(cell("description")),
    )


def parse_sheet(
    sheet: SheetData,
) -> tuple[list[ParsedRow], list[OpeningRow], list[SkippedRow]]:
    """Parse every data row. Fully-empty rows are ignored (not reported)."""
    index = build_column_index(sheet.headers)
    parsed: list[ParsedRow] = []
    openings: list[OpeningRow] = []
    skipped: list[SkippedRow] = []
    for raw in sheet.rows:
        if all(_clean(c) is None for c in raw.cells):
            continue
        result = parse_row(raw, index)
        if isinstance(result, ParsedRow):
            parsed.append(result)
        elif isinstance(result, OpeningRow):
            openings.append(result)
        else:
            skipped.append(result)
    return parsed, openings, skipped
