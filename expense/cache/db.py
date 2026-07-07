"""SQLite connection, schema bootstrap, WAL setup.

Hybrid schema: typed columns for fields filtered/sorted by 7b.2 read paths,
plus a `body` JSON blob holding the full row. New non-indexed engine fields
land in `body` without local migrations. Indexed-column changes bump
SCHEMA_VERSION and trigger wipe + cold-start.
"""

import os
import sqlite3
from pathlib import Path

from expense.errors import CacheUnavailableError

SCHEMA_VERSION = 3


def cache_path() -> Path:
    return Path(os.environ.get("EXPENSE_CACHE", "~/.expense-cache.sqlite3")).expanduser()


def _set_perms(path: Path) -> None:
    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def connect() -> sqlite3.Connection:
    """Open a connection, ensure schema, return it. Caller closes.

    The cache is a disposable replica: if the file is corrupt (sqlite3
    errors on first use), wipe it and rebuild fresh — the next read
    cold-starts from the engine. A second failure propagates.

    OperationalError is excluded from the wipe: it means locked (another
    expense process holds the file past the 5s busy timeout) or unopenable
    (path/permission trouble), never corruption — wiping would destroy a
    healthy replica under the other process's feet. Surface it cleanly.
    """
    try:
        try:
            return _open()
        except sqlite3.OperationalError:
            raise
        except sqlite3.DatabaseError:
            wipe()
            return _open()
    except sqlite3.OperationalError as exc:
        raise CacheUnavailableError(
            f"Local cache at {cache_path()} is unavailable ({exc}). Another expense "
            "process may hold it — retry in a moment, or run with --no-cache."
        ) from exc


def _open() -> sqlite3.Connection:
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = not path.exists()
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    if fresh:
        _set_perms(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=OFF")
        _bootstrap_schema(conn)
    except sqlite3.DatabaseError:
        conn.close()
        raise
    return conn


def _bootstrap_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS _cache_meta (
            id                 INTEGER PRIMARY KEY CHECK (id = 1),
            schema_version     INTEGER NOT NULL,
            user_id            TEXT,
            client_id          TEXT,
            engine_url         TEXT,
            token_fingerprint  TEXT,
            sync_token         TEXT,
            last_synced_at     TEXT
        );

        CREATE TABLE IF NOT EXISTS accounts (
            id           TEXT PRIMARY KEY,
            user_id      TEXT NOT NULL,
            is_archived  INTEGER,
            is_person    INTEGER,
            deleted_at   TEXT,
            sort_order   INTEGER,
            version      INTEGER,
            body         TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_accounts_user      ON accounts(user_id);
        CREATE INDEX IF NOT EXISTS idx_accounts_archived  ON accounts(is_archived);
        CREATE INDEX IF NOT EXISTS idx_accounts_person    ON accounts(is_person);
        CREATE INDEX IF NOT EXISTS idx_accounts_sort      ON accounts(sort_order);

        CREATE TABLE IF NOT EXISTS categories (
            id           TEXT PRIMARY KEY,
            user_id      TEXT NOT NULL,
            is_archived  INTEGER,
            is_system    INTEGER,
            deleted_at   TEXT,
            sort_order   INTEGER,
            version      INTEGER,
            body         TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_categories_user      ON categories(user_id);
        CREATE INDEX IF NOT EXISTS idx_categories_archived  ON categories(is_archived);
        CREATE INDEX IF NOT EXISTS idx_categories_sort      ON categories(sort_order);

        CREATE TABLE IF NOT EXISTS hashtags (
            id           TEXT PRIMARY KEY,
            user_id      TEXT NOT NULL,
            is_archived  INTEGER,
            deleted_at   TEXT,
            sort_order   INTEGER,
            version      INTEGER,
            body         TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_hashtags_user      ON hashtags(user_id);
        CREATE INDEX IF NOT EXISTS idx_hashtags_archived  ON hashtags(is_archived);
        CREATE INDEX IF NOT EXISTS idx_hashtags_sort      ON hashtags(sort_order);

        CREATE TABLE IF NOT EXISTS transactions (
            id                       TEXT PRIMARY KEY,
            user_id                  TEXT NOT NULL,
            account_id               TEXT,
            category_id              TEXT,
            reconciliation_id        TEXT,
            parent_transaction_id    TEXT,
            transfer_transaction_id  TEXT,
            inbox_id                 TEXT,
            date                     TEXT,
            deleted_at               TEXT,
            version                  INTEGER,
            updated_at               TEXT,
            body                     TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tx_user      ON transactions(user_id);
        CREATE INDEX IF NOT EXISTS idx_tx_account   ON transactions(account_id);
        CREATE INDEX IF NOT EXISTS idx_tx_category  ON transactions(category_id);
        CREATE INDEX IF NOT EXISTS idx_tx_recon     ON transactions(reconciliation_id);
        CREATE INDEX IF NOT EXISTS idx_tx_inbox     ON transactions(inbox_id);
        CREATE INDEX IF NOT EXISTS idx_tx_date      ON transactions(date);
        CREATE INDEX IF NOT EXISTS idx_tx_updated   ON transactions(updated_at);

        CREATE TABLE IF NOT EXISTS inbox (
            id           TEXT PRIMARY KEY,
            user_id      TEXT NOT NULL,
            account_id   TEXT,
            category_id  TEXT,
            status       INTEGER,
            date         TEXT,
            deleted_at   TEXT,
            version      INTEGER,
            body         TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_inbox_user      ON inbox(user_id);
        CREATE INDEX IF NOT EXISTS idx_inbox_account   ON inbox(account_id);
        CREATE INDEX IF NOT EXISTS idx_inbox_category  ON inbox(category_id);
        CREATE INDEX IF NOT EXISTS idx_inbox_status    ON inbox(status);
        CREATE INDEX IF NOT EXISTS idx_inbox_date      ON inbox(date);

        CREATE TABLE IF NOT EXISTS reconciliations (
            id           TEXT PRIMARY KEY,
            user_id      TEXT NOT NULL,
            account_id   TEXT,
            status       INTEGER,
            sort_order   INTEGER,
            date_end     TEXT,
            deleted_at   TEXT,
            version      INTEGER,
            body         TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_recon_user     ON reconciliations(user_id);
        CREATE INDEX IF NOT EXISTS idx_recon_account  ON reconciliations(account_id);
        CREATE INDEX IF NOT EXISTS idx_recon_sort     ON reconciliations(sort_order);

        CREATE TABLE IF NOT EXISTS settings (
            user_id  TEXT PRIMARY KEY,
            body     TEXT NOT NULL
        );
        """
    )

    cur.execute("SELECT schema_version FROM _cache_meta WHERE id = 1")
    row = cur.fetchone()
    if row is None:
        cur.execute(
            "INSERT INTO _cache_meta (id, schema_version) VALUES (1, ?)",
            (SCHEMA_VERSION,),
        )


def wipe() -> None:
    """Delete the cache file + WAL/SHM sidecars.

    Called by cold_start, corrupt-DB recovery (connect), and the config
    commands (`config set --token/--engine-url`, `config clear`).
    """
    path = cache_path()
    if path.exists():
        path.unlink()
    for sidecar in (path.with_suffix(path.suffix + "-wal"), path.with_suffix(path.suffix + "-shm")):
        if sidecar.exists():
            sidecar.unlink()
