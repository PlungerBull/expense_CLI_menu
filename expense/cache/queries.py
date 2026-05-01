"""Cache-side read queries for replica-backed list/get commands.

Each helper returns the same response shape the engine returns so the
existing per-command renderers consume cache and engine results
identically. `get_*` raises EngineError(NOT_FOUND, 404) on miss to mimic
the engine's 404 envelope; `@handle_errors` then renders the same way it
does for engine 404s.
"""

import json

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
    *, include_archived: bool = False, include_deleted: bool = False, include_people: bool = False
) -> list[dict]:
    """GET /v1/accounts equivalent. Engine returns a flat list (no pagination)."""
    where: list[str] = []
    if not include_archived:
        where.append("is_archived = 0")
    if not include_deleted:
        where.append("deleted_at IS NULL")
    if not include_people:
        where.append("(is_person = 0 OR is_person IS NULL)")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    sql = (
        "SELECT body FROM accounts "
        f"{clause} "
        "ORDER BY COALESCE(sort_order, 999999) ASC, id ASC"
    )
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
    include_deleted: bool = False,
    limit: int | None = None,
    offset: int | None = None,
) -> dict:
    where: list[str] = []
    if not include_archived:
        where.append("is_archived = 0")
    if not include_deleted:
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
    include_deleted: bool = False,
    limit: int | None = None,
    offset: int | None = None,
) -> dict:
    where: list[str] = []
    if not include_archived:
        where.append("is_archived = 0")
    if not include_deleted:
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
