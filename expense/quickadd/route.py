"""Where a parsed line goes: the ledger, or the Inbox.

One copy of the rule for both surfaces — the flat `expense log "…"` asks it
once per line, the TUI staged list asks it per row to fill its `goes to`
column (docs/mockups/expense-world-quickadd-batch.html).

The rule, as decided (docs/decisions.md): a row reaches the ledger only if
it is **complete** and **not dated ahead**. Everything else is a draft —
`POST /inbox` takes sparse bodies (only `id` is required) and has no
future-date check, which is gated at promote instead.

Deliberately not a method on `ParsedLine`: routing needs `today`, and the
parser's job ends at "what does this line say".
"""

from dataclasses import dataclass
from datetime import date as date_cls

from expense.quickadd.parse import ParsedLine, Unresolved

LEDGER = "ledger"
INBOX = "inbox"

_SIGIL = {"account": "$", "category": "@", "hashtag": "#"}
_MISSING_PHRASE = {
    "title": "the line has no title",
    "amount": "the line has no amount — a number needs a sign to be one",
    "account": "the line names no account",
    "category": "the line names no category",
}


@dataclass(frozen=True)
class Routing:
    """Where the row goes, and the phrases that say why it is not the ledger.

    `reasons` is empty for a ledger row. Each reason is a finished sentence
    fragment a caller can print as-is — the flat command puts one under the
    prompt, the staged list folds them into its footnote ("row 3 has no
    account, row 5 is dated ahead").
    """

    target: str
    reasons: tuple[str, ...] = ()

    @property
    def to_inbox(self) -> bool:
        return self.target == INBOX


def route(parsed: ParsedLine, today: date_cls) -> Routing:
    """Ledger when complete and not dated ahead; a draft otherwise."""
    reasons: list[str] = []

    for field in parsed.missing:
        # An unresolved name already explains itself below — reporting the
        # same account twice ("names no account" + "matches 2") reads as two
        # problems when there is one.
        if any(u.kind == field for u in parsed.unresolved):
            continue
        reasons.append(_MISSING_PHRASE[field])

    for token in parsed.unresolved:
        reasons.append(describe(token))

    if parsed.date > today.isoformat():
        reasons.append("it is dated ahead")

    return Routing(INBOX if reasons else LEDGER, tuple(reasons))


def describe(token: Unresolved) -> str:
    """One unresolved token as a phrase: `"$sig" matches 2 accounts`.

    Zero candidates and several read differently on purpose — one is a typo,
    the other is a name that needs more of itself typed.
    """
    if token.kind == "date":
        return f'"{token.text}" is not a real date'

    typed = f"{_SIGIL[token.kind]}{token.text}"
    plural = f"{token.kind}s" if token.kind != "category" else "categories"
    if not token.candidates:
        return f'"{typed}" matches no {plural}'
    return f'"{typed}" matches {len(token.candidates)} {plural}'
