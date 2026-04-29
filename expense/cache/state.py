"""Meta row read/write + cache-health checks.

The `_cache_meta` table always has exactly one row (id=1), seeded by
db.connect()'s schema bootstrap. Health is the conjunction of:
  schema_version matches SCHEMA_VERSION (else: wipe + cold-start)
  user_id matches caller's expected user_id (else: wipe — token swap)
  engine_url matches caller's expected engine_url (else: wipe — env swap)
  sync_token is non-null (else: cold-start needed, but cache itself is OK)
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from sqlite3 import Connection

from expense.cache.db import SCHEMA_VERSION


@dataclass
class CacheState:
    schema_version: int
    user_id: str | None
    client_id: str | None
    engine_url: str | None
    sync_token: str | None
    last_synced_at: str | None


def read(conn: Connection) -> CacheState:
    row = conn.execute("SELECT * FROM _cache_meta WHERE id = 1").fetchone()
    return CacheState(
        schema_version=row["schema_version"],
        user_id=row["user_id"],
        client_id=row["client_id"],
        engine_url=row["engine_url"],
        sync_token=row["sync_token"],
        last_synced_at=row["last_synced_at"],
    )


def write_token(conn: Connection, sync_token: str) -> None:
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "UPDATE _cache_meta SET sync_token = ?, last_synced_at = ? WHERE id = 1",
        (sync_token, now),
    )


def write_identity(conn: Connection, *, user_id: str, client_id: str, engine_url: str) -> None:
    """Set identity fields. Called once during cold_start after first sync."""
    conn.execute(
        """
        UPDATE _cache_meta
        SET user_id = ?, client_id = ?, engine_url = ?
        WHERE id = 1
        """,
        (user_id, client_id, engine_url),
    )


def is_healthy(
    state: CacheState, *, expected_user_id: str, expected_client_id: str, expected_engine_url: str
) -> bool:
    """Return True iff the cache can be trusted for delta sync.

    A non-healthy cache should be wiped and rebuilt via cold_start.
    """
    if state.schema_version != SCHEMA_VERSION:
        return False
    if state.user_id is None or state.user_id != expected_user_id:
        return False
    if state.engine_url is None or state.engine_url != expected_engine_url:
        return False
    if state.client_id is None or state.client_id != expected_client_id:
        return False
    return True
