"""A parsed line as a request body — one for the ledger, one for the Inbox.

Shared so the flat `expense log "…"` and the TUI's `ctrl+s` batch build the
same body from the same row. Pure: `date` arrives already canonicalised
(RFC 3339 with an offset), because `expense.dates.to_canonical_aware` raises
`typer.BadParameter` and this package stays free of typer.

The two bodies differ in exactly one way that matters: the ledger body is
complete by construction (routing only sends it there when it is), while the
Inbox body is **sparse** — every absent field is omitted, never sent as null.
An explicit null is a 422 on every inbox field, so the CLI never sends one
(docs/cli-spec.md, `expense inbox`).
"""

from expense.quickadd.parse import ParsedLine


def transaction_payload(parsed: ParsedLine, *, row_id: str, date: str) -> dict:
    """`POST /transactions` body. Only valid for a complete line.

    `row_id` is client-minted so a replayed write cannot double-apply — the
    same contract `expense import` and every other create already use.
    """
    payload: dict = {
        "id": row_id,
        "title": parsed.title,
        "amount_cents": parsed.amount_cents,
        "account_id": parsed.account_id,
        "category_id": parsed.category_id,
        "date": date,
    }
    if parsed.note is not None:
        payload["description"] = parsed.note
    if parsed.hashtag_ids:
        payload["hashtag_ids"] = list(parsed.hashtag_ids)
    return payload


def inbox_payload(parsed: ParsedLine, *, row_id: str, date: str) -> dict:
    """`POST /inbox` body, sparse. Only `id` is guaranteed to be there.

    Unresolved references are dropped rather than guessed: a `$sig` that
    matched two accounts leaves `account_id` out entirely, so the draft says
    "no account yet" instead of naming the wrong one.
    """
    payload: dict = {"id": row_id, "date": date}
    if parsed.title:
        payload["title"] = parsed.title
    if parsed.amount_cents is not None:
        payload["amount_cents"] = parsed.amount_cents
    if parsed.account_id is not None:
        payload["account_id"] = parsed.account_id
    if parsed.category_id is not None:
        payload["category_id"] = parsed.category_id
    if parsed.note is not None:
        payload["description"] = parsed.note
    if parsed.hashtag_ids:
        payload["hashtag_ids"] = list(parsed.hashtag_ids)
    return payload
