"""Cold-start, delta-sync, and apply-response logic.

Cold-start: fetch sync_token=*, then wipe the cache, populate from a clean
DB, persist the new token. Fetch-first: a network failure mid-cold-start
must leave the existing (stale) replica in place, not destroy it.

Delta-sync: read the stored token, fetch sync_token=<token>, apply
inserts/updates/tombstones inside one transaction, persist the new token.
On unknown-token 422, fall through to cold-start.
"""

import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from sqlite3 import Connection
from typing import IO, Literal

from expense.cache import db, state
from expense.config import Config
from expense.errors import EngineError
from expense.http import ExpenseClient

RESOURCE_TABLES: dict[str, tuple[str, ...]] = {
    "accounts": (
        "id",
        "user_id",
        "is_archived",
        "is_person",
        "deleted_at",
        "sort_order",
        "version",
    ),
    "categories": (
        "id",
        "user_id",
        "is_archived",
        "is_system",
        "deleted_at",
        "sort_order",
        "version",
    ),
    "hashtags": ("id", "user_id", "is_archived", "deleted_at", "sort_order", "version"),
    "transactions": (
        "id",
        "user_id",
        "account_id",
        "category_id",
        "reconciliation_id",
        "parent_transaction_id",
        "transfer_transaction_id",
        "inbox_id",
        "date",
        "deleted_at",
        "version",
        "updated_at",
    ),
    "inbox": (
        "id",
        "user_id",
        "account_id",
        "category_id",
        "status",
        "date",
        "deleted_at",
        "version",
    ),
    "reconciliations": (
        "id",
        "user_id",
        "account_id",
        "status",
        "sort_order",
        "date_end",
        "deleted_at",
        "version",
    ),
}

RESOURCE_KEYS: tuple[str, ...] = tuple(RESOURCE_TABLES.keys())


@dataclass
class SyncSummary:
    kind: Literal["cold_start", "delta"]
    inserts: dict[str, int] = field(default_factory=dict)
    updates: dict[str, int] = field(default_factory=dict)
    tombstones: dict[str, int] = field(default_factory=dict)
    settings_changed: bool = False
    sync_token: str = ""
    pulled_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    raw_response: dict = field(default_factory=dict)


def _derive_user_id(response: dict) -> str:
    """Pick a user_id from the response. Settings is the safest source."""
    settings = response.get("settings")
    if isinstance(settings, dict) and settings.get("user_id"):
        return str(settings["user_id"])
    for key in RESOURCE_KEYS:
        rows = response.get(key) or []
        if rows and isinstance(rows, list) and rows[0].get("user_id"):
            return str(rows[0]["user_id"])
    raise RuntimeError(
        "Cannot derive user_id from /sync response: settings is null and every resource is empty."
    )


def _apply_resource(
    conn: Connection,
    table: str,
    cols: tuple[str, ...],
    rows: list[dict],
    counts: dict[str, dict[str, int]],
) -> None:
    counts["inserts"][table] = 0
    counts["updates"][table] = 0
    counts["tombstones"][table] = 0
    if not rows:
        return

    existing = {r[0] for r in conn.execute(f"SELECT id FROM {table}")}

    placeholders = ", ".join(["?"] * (len(cols) + 1))
    insert_sql = f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}, body) VALUES ({placeholders})"
    delete_sql = f"DELETE FROM {table} WHERE id = ?"

    for row in rows:
        row_id = row.get("id")
        if not row_id:
            continue
        if row.get("deleted_at"):
            cur = conn.execute(delete_sql, (row_id,))
            if cur.rowcount > 0:
                counts["tombstones"][table] += 1
            continue
        if row_id in existing:
            counts["updates"][table] += 1
        else:
            counts["inserts"][table] += 1
        values = tuple(row.get(c) for c in cols) + (json.dumps(row),)
        conn.execute(insert_sql, values)


def _apply_settings(conn: Connection, settings: dict | None) -> bool:
    if not isinstance(settings, dict):
        return False
    user_id = settings.get("user_id")
    if not user_id:
        return False
    conn.execute(
        "INSERT OR REPLACE INTO settings (user_id, body) VALUES (?, ?)",
        (str(user_id), json.dumps(settings)),
    )
    return True


def apply_response(conn: Connection, response: dict, *, kind: str) -> SyncSummary:
    """Apply a /sync response in one transaction. Returns summary counts."""
    summary = SyncSummary(kind=kind)
    counts: dict[str, dict[str, int]] = {"inserts": {}, "updates": {}, "tombstones": {}}

    conn.execute("BEGIN")
    try:
        for table, cols in RESOURCE_TABLES.items():
            _apply_resource(conn, table, cols, response.get(table) or [], counts)
        summary.settings_changed = _apply_settings(conn, response.get("settings"))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    summary.inserts = counts["inserts"]
    summary.updates = counts["updates"]
    summary.tombstones = counts["tombstones"]
    summary.sync_token = response.get("sync_token") or ""
    return summary


def _fetch(client: ExpenseClient, sync_token: str) -> dict:
    return client.get(
        "/sync",
        params={"sync_token": sync_token, "debit_as_negative": "true"},
    )


def cold_start(client: ExpenseClient, cfg: Config) -> SyncSummary:
    """Fetch sync_token=*, wipe the cache, populate, persist the new token.

    Wiping only after a successful fetch (and user_id derivation) means a
    failed cold-start degrades to "still stale", never to "no cache at all".
    """
    pulled_at = datetime.now(UTC)
    response = _fetch(client, "*")
    user_id = _derive_user_id(response)

    db.wipe()
    conn = db.connect()
    try:
        summary = apply_response(conn, response, kind="cold_start")
        state.write_identity(
            conn,
            user_id=user_id,
            client_id=str(cfg.client_id),
            engine_url=cfg.engine_url,
            token_fingerprint=state.token_fingerprint(cfg.token),
        )
        state.write_token(conn, summary.sync_token)
    finally:
        conn.close()

    summary.pulled_at = pulled_at
    summary.raw_response = response
    return summary


def ensure_synced(
    client: ExpenseClient, cfg: Config, *, notice_stream: IO[str] | None = None
) -> SyncSummary | None:
    """Cold-start the cache if missing/unhealthy. No-op when healthy.

    Prints a one-line notice to `notice_stream` (default stderr) before a
    cold-start so users know why the first read is slow. Returns the
    summary if a sync ran, else None.
    """
    stream = notice_stream if notice_stream is not None else sys.stderr
    conn = db.connect()
    try:
        cur_state = state.read(conn)
    finally:
        conn.close()

    healthy = state.is_healthy(
        cur_state,
        expected_client_id=str(cfg.client_id),
        expected_engine_url=cfg.engine_url,
        expected_token_fingerprint=state.token_fingerprint(cfg.token),
    )
    needs_cold_start = (not healthy) or cur_state.sync_token is None

    if not needs_cold_start:
        return None

    print(
        f"First-run sync against {cfg.engine_url} — this may take a moment...",
        file=stream,
    )
    return cold_start(client, cfg)


def refresh_after_write(
    client: ExpenseClient,
    cfg: Config,
    *,
    no_cache: bool,
    no_sync_after: bool,
    notice_stream: IO[str] | None = None,
) -> SyncSummary | None:
    """Delta-sync the cache after a successful write. Non-fatal on failure.

    Skips when stateless mode is active, when the user opts out for this
    invocation, or when the cache file does not exist yet (writes must
    not bootstrap the cache; cold-start is a read-side responsibility).
    Any sync failure is swallowed with a one-line stderr warning so the
    write itself remains the user-visible result.
    """
    if no_cache or no_sync_after:
        return None
    if not db.cache_path().exists():
        return None
    stream = notice_stream if notice_stream is not None else sys.stderr
    try:
        return delta_sync(client, cfg)
    except Exception as exc:
        print(
            f"Cache refresh failed after write: {exc}. Run 'expense sync' to refresh.",
            file=stream,
        )
        return None


def delta_sync(client: ExpenseClient, cfg: Config) -> SyncSummary:
    """Delta-sync the cache. Falls back to cold_start on unhealthy state or 422."""
    pulled_at = datetime.now(UTC)
    conn = db.connect()
    try:
        cur_state = state.read(conn)
    finally:
        conn.close()

    healthy = state.is_healthy(
        cur_state,
        expected_client_id=str(cfg.client_id),
        expected_engine_url=cfg.engine_url,
        expected_token_fingerprint=state.token_fingerprint(cfg.token),
    )
    if not healthy or cur_state.sync_token is None:
        return cold_start(client, cfg)

    try:
        response = _fetch(client, cur_state.sync_token or "*")
    except EngineError as err:
        if err.status == 422 and (err.fields or {}).get("sync_token"):
            return cold_start(client, cfg)
        raise

    conn = db.connect()
    try:
        summary = apply_response(conn, response, kind="delta")
        state.write_token(conn, summary.sync_token)
    finally:
        conn.close()

    summary.pulled_at = pulled_at
    summary.raw_response = response
    return summary
