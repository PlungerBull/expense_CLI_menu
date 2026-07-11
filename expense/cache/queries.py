"""Cache-side read queries for replica-backed list/get commands.

Each helper returns the same response shape the engine returns so the
existing per-command renderers consume cache and engine results
identically. `get_*` raises EngineError(NOT_FOUND, 404) on miss to mimic
the engine's 404 envelope; `@handle_errors` then renders the same way it
does for engine 404s.
"""

import json
from datetime import UTC, datetime

from expense.cache import db
from expense.errors import EngineError


def _not_found(resource: str, resource_id: str) -> EngineError:
    return EngineError(
        code="NOT_FOUND",
        message=f"{resource} {resource_id} not found.",
        fields=None,
        status=404,
        raw_body={
            "error": {
                "code": "NOT_FOUND",
                "message": f"{resource} {resource_id} not found.",
                "fields": None,
            }
        },
    )


def _row_to_dict(body_text: str) -> dict:
    return json.loads(body_text)


def list_accounts(
    *,
    include_archived: bool = False,
    include_people: bool = False,
    limit: int | None = None,
    offset: int | None = None,
) -> list[dict] | dict:
    """GET /v1/accounts equivalent — dual shape.

    With neither limit nor offset: the flat list the spec documents for
    /accounts (internal consumers — name maps, account choices, recon browse —
    rely on it). With either set: the standard {items,total,limit,offset}
    envelope, mirroring what the engine actually serves (it pages /accounts at
    default 50 despite the spec; gap noted at commit 4ef5c55). Added for the
    20-row human default (2026-07-11).
    """
    where: list[str] = []
    if not include_archived:
        where.append("is_archived = 0")
    # tombstones are purged at sync — guard, not filter
    where.append("deleted_at IS NULL")
    if not include_people:
        where.append("(is_person = 0 OR is_person IS NULL)")
    order_by = "ORDER BY COALESCE(sort_order, 999999) ASC, id ASC"
    if limit is not None or offset is not None:
        return _list_paginated(
            "accounts",
            where_clauses=where,
            params=(),
            order_by=order_by,
            limit=limit,
            offset=offset,
        )
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"SELECT body FROM accounts {clause} {order_by}"
    conn = db.connect()
    try:
        return [_row_to_dict(row["body"]) for row in conn.execute(sql)]
    finally:
        conn.close()


def get_account(account_id: str) -> dict:
    conn = db.connect()
    try:
        row = conn.execute("SELECT body FROM accounts WHERE id = ?", (account_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise _not_found("Account", account_id)
    return _row_to_dict(row["body"])


def _list_paginated(
    table: str,
    *,
    where_clauses: list[str],
    params: tuple,
    order_by: str,
    limit: int | None,
    offset: int | None,
) -> dict:
    clause = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    eff_limit = limit if isinstance(limit, int) and limit > 0 else 100
    eff_offset = offset if isinstance(offset, int) and offset >= 0 else 0
    conn = db.connect()
    try:
        total = conn.execute(f"SELECT count(*) FROM {table} {clause}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT body FROM {table} {clause} {order_by} LIMIT ? OFFSET ?",
            params + (eff_limit, eff_offset),
        ).fetchall()
    finally:
        conn.close()
    return {
        "total": total,
        "limit": eff_limit,
        "offset": eff_offset,
        "items": [_row_to_dict(r["body"]) for r in rows],
    }


def list_categories(
    *,
    include_archived: bool = False,
    limit: int | None = None,
    offset: int | None = None,
) -> dict:
    where: list[str] = []
    if not include_archived:
        where.append("is_archived = 0")
    # tombstones are purged at sync — guard, not filter
    where.append("deleted_at IS NULL")
    return _list_paginated(
        "categories",
        where_clauses=where,
        params=(),
        order_by="ORDER BY COALESCE(sort_order, 999999) ASC, id ASC",
        limit=limit,
        offset=offset,
    )


def get_category(category_id: str) -> dict:
    conn = db.connect()
    try:
        row = conn.execute("SELECT body FROM categories WHERE id = ?", (category_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise _not_found("Category", category_id)
    return _row_to_dict(row["body"])


def list_hashtags(
    *,
    include_archived: bool = False,
    limit: int | None = None,
    offset: int | None = None,
) -> dict:
    where: list[str] = []
    if not include_archived:
        where.append("is_archived = 0")
    # tombstones are purged at sync — guard, not filter
    where.append("deleted_at IS NULL")
    return _list_paginated(
        "hashtags",
        where_clauses=where,
        params=(),
        order_by="ORDER BY COALESCE(sort_order, 999999) ASC, id ASC",
        limit=limit,
        offset=offset,
    )


def get_hashtag(hashtag_id: str) -> dict:
    conn = db.connect()
    try:
        row = conn.execute("SELECT body FROM hashtags WHERE id = ?", (hashtag_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise _not_found("Hashtag", hashtag_id)
    return _row_to_dict(row["body"])


# Mirrors the engine's ?ready=true conditions (engine app/routers/inbox.py):
# title set + non-UNTITLED, amount set + non-zero, date <= now(), account &
# category present, active and non-archived. The date comparison is a full
# UTC *timestamp* (`i.date <= now()`), NOT a calendar-date truncation — the
# engine does not use the profile timezone here.
_READY_PREDICATE = """\
json_extract(i.body, '$.title') IS NOT NULL
AND json_extract(i.body, '$.title') != 'UNTITLED'
AND json_extract(i.body, '$.amount_cents') IS NOT NULL
AND json_extract(i.body, '$.amount_cents') != 0
AND i.date IS NOT NULL
AND datetime(i.date) <= datetime(?)
AND i.account_id IS NOT NULL
AND i.category_id IS NOT NULL
AND a.id IS NOT NULL AND a.deleted_at IS NULL AND a.is_archived = 0
AND c.id IS NOT NULL AND c.deleted_at IS NULL AND c.is_archived = 0\
"""


def list_inbox(
    *,
    ready: bool = False,
    overdue: bool = False,
    limit: int | None = None,
    offset: int | None = None,
    now: str | None = None,
) -> dict:
    """GET /v1/inbox equivalent. Paginated wrapper.

    `ready` and `overdue` replicate the engine's conditions and, like the
    engine's, combine independently (ready: `i.date <= now()`, overdue:
    `i.date < now()`). `now` is an RFC 3339 UTC timestamp, parameterized so
    tests can freeze it; SQLite's datetime() normalizes both 'Z' and
    '±HH:MM' offsets, matching the engine's UTC now() regardless of how the
    synced date was serialized. No `i.status = 1` filter is needed:
    promotion tombstones the row engine-side and sync purges tombstones
    (expense/cache/sync.py), so replica rows are always drafts.
    """
    eff_limit = limit if isinstance(limit, int) and limit > 0 else 100
    eff_offset = offset if isinstance(offset, int) and offset >= 0 else 0
    now_utc = now or datetime.now(UTC).isoformat()

    # tombstones are purged at sync — guard, not filter
    where_parts: list[str] = ["i.deleted_at IS NULL"]
    params: list = []
    if ready:
        where_parts.append(_READY_PREDICATE)
        params.append(now_utc)
    if overdue:
        where_parts.append("i.date IS NOT NULL AND datetime(i.date) < datetime(?)")
        params.append(now_utc)

    where_sql = "WHERE " + " AND ".join(f"({c})" for c in where_parts)

    conn = db.connect()
    try:
        join_sql = (
            "FROM inbox i "
            "LEFT JOIN accounts a ON a.id = i.account_id "
            "LEFT JOIN categories c ON c.id = i.category_id "
        )
        total = conn.execute(
            f"SELECT count(*) {join_sql}{where_sql}",
            params,
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT i.body {join_sql}{where_sql} ORDER BY i.date DESC, i.id ASC LIMIT ? OFFSET ?",
            (*params, eff_limit, eff_offset),
        ).fetchall()
    finally:
        conn.close()

    return {
        "total": total,
        "limit": eff_limit,
        "offset": eff_offset,
        "items": [_row_to_dict(r["body"]) for r in rows],
    }


def get_inbox(inbox_id: str) -> dict:
    conn = db.connect()
    try:
        row = conn.execute("SELECT body FROM inbox WHERE id = ?", (inbox_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise _not_found("Inbox item", inbox_id)
    return _row_to_dict(row["body"])


def list_reconciliations(
    *,
    account_id: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> dict:
    where: list[str] = []
    params: tuple = ()
    if account_id is not None:
        where.append("account_id = ?")
        params = (account_id,)
    # tombstones are purged at sync — guard, not filter
    where.append("deleted_at IS NULL")
    return _list_paginated(
        "reconciliations",
        where_clauses=where,
        params=params,
        order_by="ORDER BY COALESCE(sort_order, 999999) ASC, id ASC",
        limit=limit,
        offset=offset,
    )


def list_transactions(
    *,
    account_id: str | None = None,
    category_id: str | None = None,
    hashtag_id: str | None = None,
    reconciliation_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    cleared: bool | None = None,
    search: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> dict:
    """GET /v1/transactions equivalent. Paginated wrapper.

    `hashtag_id` uses SQLite `json_each(body, '$.hashtag_ids')` for containment.
    `search` uses `LIKE ? COLLATE NOCASE` against title + description.
    Engine A+ embeds `hashtag_ids` on every transaction-returning endpoint
    (sorted ASC, `[]` on empty) per api-design-principles.md §3a, and the
    cache mirrors that — items here carry `hashtag_ids` from the stored body.
    """
    eff_limit = limit if isinstance(limit, int) and limit > 0 else 100
    eff_offset = offset if isinstance(offset, int) and offset >= 0 else 0

    where: list[str] = ["t.deleted_at IS NULL"]
    params: list = []

    if account_id is not None:
        where.append("t.account_id = ?")
        params.append(account_id)
    if category_id is not None:
        where.append("t.category_id = ?")
        params.append(category_id)
    if reconciliation_id is not None:
        where.append("t.reconciliation_id = ?")
        params.append(reconciliation_id)
    if date_from is not None:
        where.append("t.date >= ?")
        params.append(date_from)
    if date_to is not None:
        where.append("t.date <= ?")
        params.append(date_to)
    if cleared is not None:
        where.append("json_extract(t.body, '$.cleared') = ?")
        params.append(1 if cleared else 0)
    if hashtag_id is not None:
        where.append(
            "EXISTS (SELECT 1 FROM json_each(t.body, '$.hashtag_ids') h WHERE h.value = ?)"
        )
        params.append(hashtag_id)
    if search:
        like = f"%{search}%"
        where.append(
            "(json_extract(t.body, '$.title') LIKE ? COLLATE NOCASE "
            "OR json_extract(t.body, '$.description') LIKE ? COLLATE NOCASE)"
        )
        params.extend([like, like])

    where_sql = "WHERE " + " AND ".join(where)
    order_sql = "ORDER BY t.date DESC, json_extract(t.body, '$.created_at') DESC"

    conn = db.connect()
    try:
        total = conn.execute(
            f"SELECT count(*) FROM transactions t {where_sql}",
            tuple(params),
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT t.body FROM transactions t {where_sql} {order_sql} LIMIT ? OFFSET ?",
            tuple(params) + (eff_limit, eff_offset),
        ).fetchall()
    finally:
        conn.close()

    return {
        "total": total,
        "limit": eff_limit,
        "offset": eff_offset,
        "items": [_row_to_dict(r["body"]) for r in rows],
    }


def get_transaction(transaction_id: str) -> dict:
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT body FROM transactions WHERE id = ?", (transaction_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise _not_found("Transaction", transaction_id)
    return _row_to_dict(row["body"])


def get_reconciliation(
    reconciliation_id: str,
    *,
    embedded_limit: int | None = None,
    embedded_offset: int | None = None,
) -> dict:
    """Returns the reconciliation row plus paginated embedded transactions.

    Mimics the engine's ReconciliationDetailResponse: the row's fields plus
    `transactions`, `transactions_total`, `transactions_limit`,
    `transactions_offset`, `transactions_truncated`.
    """
    eff_limit = embedded_limit if isinstance(embedded_limit, int) and embedded_limit > 0 else 100
    eff_offset = embedded_offset if isinstance(embedded_offset, int) and embedded_offset >= 0 else 0

    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT body FROM reconciliations WHERE id = ?", (reconciliation_id,)
        ).fetchone()
        if row is None:
            raise _not_found("Reconciliation", reconciliation_id)
        recon_body = _row_to_dict(row["body"])

        total = conn.execute(
            "SELECT count(*) FROM transactions WHERE reconciliation_id = ? AND deleted_at IS NULL",
            (reconciliation_id,),
        ).fetchone()[0]
        tx_rows = conn.execute(
            "SELECT body FROM transactions "
            "WHERE reconciliation_id = ? AND deleted_at IS NULL "
            "ORDER BY date DESC, json_extract(body, '$.created_at') DESC "
            "LIMIT ? OFFSET ?",
            (reconciliation_id, eff_limit, eff_offset),
        ).fetchall()
    finally:
        conn.close()

    items = [_row_to_dict(r["body"]) for r in tx_rows]
    return {
        **recon_body,
        "transactions": items,
        "transactions_total": total,
        "transactions_limit": eff_limit,
        "transactions_offset": eff_offset,
        "transactions_truncated": (eff_offset + len(items)) < total,
    }
