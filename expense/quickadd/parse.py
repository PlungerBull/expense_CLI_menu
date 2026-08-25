"""Pure parsing: one typed line -> ParsedLine. No I/O, no HTTP, no Textual.

The grammar, as drawn in docs/mockups/expense-world-quickadd-batch.html:

    tottus -38.60 $signature @korakuen #caja hoy
    title  amount $account   @category #tag  when

`//` opens a note that runs to the end of the line. A sign is what *makes* a
number an amount, and the first sign wins. `$`, `@` and the date are
first-wins; `#` is the only repeatable token. Whatever is left, in order, is
the title.

Names are matched against the reference lists the caller already holds —
nothing is created here, and an unmatched name is reported rather than
guessed. Spans come back with every token so a caller can colour the line
without parsing it again.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date as date_cls

from expense.quickadd.money import parse_amount
from expense.quickadd.when import parse_date

# A sign only starts an amount at a token boundary, which is what keeps
# `coca-cola`, `T-800` and `covid-19` titles while `-30` is money. The `$` is
# decoration the account already settles, so `-$1800` is `-1800`.
_AMOUNT = re.compile(r"^[+-]\$?[0-9][0-9,.]*$")
_SIGILS = ("$", "@", "#")

REQUIRED = ("title", "amount", "account", "category")


@dataclass(frozen=True)
class Span:
    """One token's place in the source line, for colouring.

    `kind` is amount | account | category | hashtag | note | date | title.
    `resolved` is False only for a reference name that found no single match,
    or a date-shaped word that is not a real date — the error slot.
    """

    kind: str
    start: int
    end: int
    text: str
    resolved: bool = True


@dataclass(frozen=True)
class Unresolved:
    """A token that named something the reference lists do not contain.

    `candidates` is empty when nothing matched and holds every hit when
    several did — the picker's input either way.
    """

    kind: str
    text: str
    span: Span
    candidates: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ParsedLine:
    title: str
    amount_cents: int | None
    account_id: str | None
    category_id: str | None
    hashtag_ids: tuple[str, ...]
    note: str | None
    date: str
    date_given: bool
    spans: tuple[Span, ...]
    unresolved: tuple[Unresolved, ...]
    missing: tuple[str, ...]

    @property
    def is_complete(self) -> bool:
        """Every required field present and every name resolved.

        Routing is the screen's call, not this module's: a complete row still
        goes to the Inbox when it is dated ahead (docs/decisions.md).
        """
        return not self.missing and not self.unresolved


@dataclass(frozen=True)
class _Entry:
    id: str
    name: str
    key: str
    words: int


def _entries(rows: Sequence[Sequence]) -> list[_Entry]:
    """`(id, name, …)` rows -> match entries. Extra columns are ignored, so
    `account_choices()` tuples pass straight through."""
    out: list[_Entry] = []
    for row in rows:
        if len(row) < 2:
            continue
        ident, name = row[0], row[1]
        if not isinstance(ident, str) or not isinstance(name, str):
            continue
        key = " ".join(name.split()).casefold()
        if not key:
            continue
        out.append(_Entry(id=ident, name=name, key=key, words=len(key.split())))
    return out


def _lookahead(words: list[tuple[int, int, str]], start: int, limit: int) -> int:
    """How many words after `start` a multi-word name may swallow.

    Stops at another sigil or at an amount, so a name never eats `-38.60` or
    the `@category` that follows it.
    """
    taken = 0
    index = start + 1
    while taken < limit - 1 and index < len(words):
        text = words[index][2]
        if text[0] in _SIGILS or _AMOUNT.match(text):
            break
        taken += 1
        index += 1
    return taken


def _resolve(
    words: list[tuple[int, int, str]], start: int, head: str, entries: list[_Entry]
) -> tuple[int, list[_Entry]]:
    """Longest-first name matching. Returns (words consumed, hits).

    An exact name wins outright at the longest length that has one; failing
    that, "contains anywhere" at the longest length with any hit (decided
    2026-08-25 — the rule every existing picker already uses).
    """
    limit = max((e.words for e in entries), default=1)
    extra = _lookahead(words, start, limit)
    phrases: list[tuple[int, str]] = []
    for k in range(extra, -1, -1):
        parts = [head] + [words[start + i][2] for i in range(1, k + 1)]
        phrases.append((k + 1, " ".join(" ".join(parts).split()).casefold()))

    for count, phrase in phrases:
        hits = [e for e in entries if e.key == phrase]
        if hits:
            return count, hits
    for count, phrase in phrases:
        hits = [e for e in entries if phrase in e.key]
        if hits:
            return count, hits
    return 1, []


def parse(
    line: str,
    *,
    accounts: Sequence[Sequence],
    categories: Sequence[Sequence],
    hashtags: Sequence[Sequence],
    today: date_cls,
) -> ParsedLine:
    """Read one quick-add line into the fields a transaction needs.

    The three reference arguments are `(id, name)` sequences the caller
    already holds; `today` is injected so the result is deterministic.
    """
    spans: list[Span] = []
    unresolved: list[Unresolved] = []

    body, note, note_span = _split_note(line)
    if note_span is not None:
        spans.append(note_span)

    refs = {
        "account": _entries(accounts),
        "category": _entries(categories),
        "hashtag": _entries(hashtags),
    }
    sigil_kind = {"$": "account", "@": "category", "#": "hashtag"}

    words = [(m.start(), m.end(), m.group()) for m in re.finditer(r"\S+", body)]
    title_words: list[str] = []
    amount_cents: int | None = None
    picked: dict[str, str | None] = {"account": None, "category": None}
    hashtag_ids: list[str] = []
    iso: str | None = None
    bad_date = False

    index = 0
    while index < len(words):
        start, end, text = words[index]
        head = text[1:]
        kind = sigil_kind.get(text[0]) if len(text) > 1 else None

        # `$` splits on the next character: digits are money decoration the
        # account already settles, letters name an account. Safe because no
        # account name starts with a digit.
        if kind == "account" and head[0].isdigit():
            kind = None

        if kind is not None and (kind == "hashtag" or picked.get(kind) is None):
            count, hits = _resolve(words, index, head, refs[kind])
            last = words[index + count - 1][1]
            typed = body[start:last]
            resolved = len(hits) == 1
            span = Span(kind, start, last, typed, resolved=resolved)
            spans.append(span)
            if resolved:
                if kind == "hashtag":
                    # The same tag twice is a slip, not an error — dedupe it.
                    if hits[0].id not in hashtag_ids:
                        hashtag_ids.append(hits[0].id)
                else:
                    picked[kind] = hits[0].id
            else:
                unresolved.append(
                    Unresolved(
                        kind=kind,
                        text=typed[1:],
                        span=span,
                        candidates=tuple((h.id, h.name) for h in hits),
                    )
                )
            index += count
            continue

        if amount_cents is None and _AMOUNT.match(text):
            cents = parse_amount(text.replace("$", ""))
            if cents is not None:
                amount_cents = cents
                spans.append(Span("amount", start, end, text))
                index += 1
                continue

        if iso is None and not bad_date:
            found, looked = parse_date(text, today)
            if looked:
                iso = found
                bad_date = found is None
                span = Span("date", start, end, text, resolved=not bad_date)
                spans.append(span)
                if bad_date:
                    unresolved.append(Unresolved(kind="date", text=text, span=span))
                index += 1
                continue

        title_words.append(text)
        spans.append(Span("title", start, end, text))
        index += 1

    title = " ".join(title_words)
    values = {
        "title": title or None,
        "amount": amount_cents,
        "account": picked["account"],
        "category": picked["category"],
    }
    return ParsedLine(
        title=title,
        amount_cents=amount_cents,
        account_id=picked["account"],
        category_id=picked["category"],
        hashtag_ids=tuple(hashtag_ids),
        note=note,
        date=iso or today.isoformat(),
        date_given=iso is not None,
        spans=tuple(sorted(spans, key=lambda s: s.start)),
        unresolved=tuple(unresolved),
        missing=tuple(k for k in REQUIRED if values[k] is None),
    )


def _split_note(line: str) -> tuple[str, str | None, Span | None]:
    """Everything after the first space-preceded `//` is the description.

    The space is what lets a pasted `https://…` stay in the title.
    """
    for i in range(len(line) - 1):
        if line[i : i + 2] == "//" and (i == 0 or line[i - 1].isspace()):
            text = line[i + 2 :].strip()
            return line[:i], text or None, Span("note", i, len(line), line[i:])
    return line, None, None
