"""The `when` token — date words and date shapes, in both languages.

Emits `YYYY-MM-DD` and nothing else. The caller hands that to
`expense.dates.to_canonical_aware` for the wire format; that function raises
`typer.BadParameter`, so it is deliberately not reachable from here.

Accepted (decided 2026-08-25, docs/decisions.md):
  hoy / ayer / mañana        · unaccented spellings too, any case
  today / yesterday / tomorrow
  dd/mm/yyyy                 · dd/mm/yy, where yy → 20yy
  yyyy/mm/dd                 · 4-digit-first disambiguates, so it cannot
                               collide with dd/mm/yyyy
  yyyy-mm-dd                 · the form `--date` takes everywhere else
  28Aug / 28/Aug / 28-Aug    · day + month name, this year (2026-08-29). Both
                               languages, any prefix of the month from three
                               letters up (`ago`, `agosto`, `sept`, `set`), and
                               an optional year: `28Aug26`, `28-ago-2025`.
"""

import re
from datetime import date, timedelta

_OFFSETS = {
    "hoy": 0,
    "today": 0,
    "ayer": -1,
    "yesterday": -1,
    "mañana": 1,
    "manana": 1,
    "tomorrow": 1,
}

# 4-digit year first: yyyy/mm/dd and yyyy-mm-dd.
_YEAR_FIRST = re.compile(r"^(\d{4})([/-])(\d{1,2})\2(\d{1,2})$")
# Day first, slashes only — a dashed dd-mm-yyyy is not a shape we accept.
_DAY_FIRST = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})$")
# Day + month *name*: `28Aug`, `28/Aug`, `28-ago-2025`. The separators are
# optional because that is how it gets typed; the month is letters, which is
# what keeps this shape away from `dd/mm` — a bare `28/08` is deliberately NOT
# a date (2026-08-29), because `1/2` and `1/4` are things people write in a
# title and a fraction must not silently become February.
_DAY_MONTH = re.compile(r"^(\d{1,2})[/-]?([^\W\d_]{3,})(?:[/-]?(\d{2}|\d{4}))?$", re.UNICODE)

#: Month names in both languages, longest spelling first. Matching is by
#: **prefix from three letters up**, which covers every abbreviation anyone
#: types (`aug`, `agos`, `sept`, `set`, `dic`) without a table of them — and is
#: unambiguous by construction: no three-letter prefix reaches two different
#: months in either language (`mar` is March and marzo; `may` is may and mayo).
_MONTH_NAMES: dict[int, tuple[str, ...]] = {
    1: ("january", "enero"),
    2: ("february", "febrero"),
    3: ("march", "marzo"),
    4: ("april", "abril"),
    5: ("may", "mayo"),
    6: ("june", "junio"),
    7: ("july", "julio"),
    8: ("august", "agosto"),
    9: ("september", "septiembre", "setiembre"),
    10: ("october", "octubre"),
    11: ("november", "noviembre"),
    12: ("december", "diciembre"),
}


def month_from_word(word: str) -> int | None:
    """`'aug'`/`'agosto'`/`'Sept'` → the month number; None for anything else."""
    key = word.casefold()
    hits = {
        number
        for number, names in _MONTH_NAMES.items()
        if any(name.startswith(key) for name in names)
    }
    return hits.pop() if len(hits) == 1 else None


def parse_date(word: str, today: date) -> tuple[str | None, bool]:
    """`('2026-08-18', True)` for a date, `(None, False)` for anything else.

    The second element says the word *looked* like a date, so `(None, True)`
    means date-shaped but impossible (`32/13/2026`) — the caller reports that
    rather than letting the word slide silently into the title.
    """
    key = word.casefold()
    if key in _OFFSETS:
        return (today + timedelta(days=_OFFSETS[key])).isoformat(), True

    match = _YEAR_FIRST.match(word)
    if match:
        year, _, month, day = match.groups()
        return _build(int(year), int(month), int(day))

    match = _DAY_MONTH.match(word)
    if match:
        day, name, year = match.groups()
        month = month_from_word(name)
        if month is not None:
            # No year means *this* year — the ledger you are typing into is
            # the current one, and the resolved date is echoed in words before
            # the row is staged, so a wrong guess is visible (2026-08-29).
            if year is None:
                resolved = today.year
            else:
                resolved = 2000 + int(year) if len(year) == 2 else int(year)
            return _build(resolved, month, int(day))

    match = _DAY_FIRST.match(word)
    if match:
        day, month, year = match.groups()
        # Two-digit years resolve to this century. Accepted because the screen
        # echoes the resolved date in words before a row is staged, so a
        # misread is visible rather than silent (docs/decisions.md).
        return _build(2000 + int(year) if len(year) == 2 else int(year), int(month), int(day))

    return None, False


def _build(year: int, month: int, day: int) -> tuple[str | None, bool]:
    try:
        return date(year, month, day).isoformat(), True
    except ValueError:
        return None, True


_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def format_date_words(iso: str) -> str:
    """`'2026-08-18'` -> `'Tue 18 Aug 2026'`. Unparseable input passes through.

    The echo the grammar leans on: two-digit years are accepted *because* the
    resolved date is always spelled out before the row is committed, so a
    misread is visible rather than silent (docs/decisions.md). English and
    fixed on purpose — `strftime` would follow the machine locale, and a date
    that changes shape between machines is the opposite of a check.
    """
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{_WEEKDAYS[d.weekday()]} {d.day} {_MONTHS[d.month - 1]} {d.year}"
