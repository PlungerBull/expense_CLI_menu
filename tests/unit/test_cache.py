import io
import json
import sqlite3
from uuid import uuid4

import httpx
import pytest
import respx

from expense import cache
from expense.cache import db as cache_db
from expense.cache import state as cache_state
from expense.cache import sync as cache_sync
from expense.config import Config
from expense.errors import CacheUnavailableError, EngineError
from expense.http import ExpenseClient

SYNC_FULL_RESPONSE = {
    "sync_token": "token-1",
    "accounts": [
        {
            "id": "a1",
            "user_id": "u1",
            "name": "BCP",
            "is_archived": False,
            "is_person": False,
            "deleted_at": None,
            "sort_order": 1,
            "version": 1,
        }
    ],
    "categories": [
        {
            "id": "c1",
            "user_id": "u1",
            "name": "Food",
            "is_archived": False,
            "is_system": False,
            "deleted_at": None,
            "sort_order": 1,
            "version": 1,
        }
    ],
    "hashtags": [
        {
            "id": "h1",
            "user_id": "u1",
            "name": "#vacation",
            "is_archived": False,
            "deleted_at": None,
            "sort_order": 1,
            "version": 1,
        }
    ],
    "inbox": [],
    "transactions": [
        {
            "id": "t1",
            "user_id": "u1",
            "title": "Lunch",
            "amount_cents": -1200,
            "account_id": "a1",
            "category_id": "c1",
            "reconciliation_id": None,
            "parent_transaction_id": None,
            "transfer_transaction_id": None,
            "inbox_id": None,
            "date": "2026-04-25",
            "deleted_at": None,
            "version": 1,
            "updated_at": "2026-04-25T10:00:00Z",
            "hashtag_ids": ["h1"],
        }
    ],
    "reconciliations": [],
    "settings": {"user_id": "u1", "main_currency": "USD", "version": 1},
}


@pytest.fixture
def cache_path(tmp_path, monkeypatch):
    path = tmp_path / "cache.sqlite3"
    monkeypatch.setenv("EXPENSE_CACHE", str(path))
    yield path


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    config_path = tmp_path / ".expense-config"
    monkeypatch.setenv("EXPENSE_CONFIG", str(config_path))
    return Config(
        engine_url="https://api.example.com",
        token="ewe_pat_test",
        client_id=uuid4(),
    )


def _make_client(cfg: Config) -> ExpenseClient:
    return ExpenseClient(cfg)


def test_connect_creates_schema_and_meta(cache_path):
    conn = cache.connect()
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        for expected in (
            "_cache_meta",
            "accounts",
            "categories",
            "hashtags",
            "inbox",
            "transactions",
            "reconciliations",
            "settings",
        ):
            assert expected in tables

        meta = conn.execute("SELECT * FROM _cache_meta WHERE id = 1").fetchone()
        assert meta["schema_version"] == cache.SCHEMA_VERSION
        assert meta["user_id"] is None
        assert meta["sync_token"] is None

        wal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert wal.lower() == "wal"
    finally:
        conn.close()


@respx.mock
def test_cold_start_populates_all_resources(cache_path, cfg):
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_FULL_RESPONSE)
    )
    with _make_client(cfg) as client:
        summary = cache.cold_start(client, cfg)

    assert summary.kind == "cold_start"
    assert summary.sync_token == "token-1"
    assert summary.inserts["accounts"] == 1
    assert summary.inserts["transactions"] == 1
    assert summary.inserts["inbox"] == 0
    assert summary.settings_changed is True

    conn = cache.connect()
    try:
        assert conn.execute("SELECT count(*) FROM accounts").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM transactions").fetchone()[0] == 1
        s = cache_state.read(conn)
        assert s.user_id == "u1"
        assert s.client_id == str(cfg.client_id)
        assert s.engine_url == cfg.engine_url
        assert s.sync_token == "token-1"
        body = conn.execute("SELECT body FROM transactions WHERE id = 't1'").fetchone()[0]
        assert json.loads(body)["hashtag_ids"] == ["h1"]
    finally:
        conn.close()


@respx.mock
def test_delta_sync_applies_inserts_updates_tombstones(cache_path, cfg):
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_FULL_RESPONSE)
    )
    with _make_client(cfg) as client:
        cache.cold_start(client, cfg)

    delta = {
        "sync_token": "token-2",
        "accounts": [
            {
                "id": "a1",
                "user_id": "u1",
                "name": "BCP renamed",
                "is_archived": False,
                "is_person": False,
                "deleted_at": None,
                "sort_order": 1,
                "version": 2,
            }
        ],
        "categories": [],
        "hashtags": [],
        "inbox": [],
        "transactions": [
            {
                "id": "t2",
                "user_id": "u1",
                "title": "New row",
                "amount_cents": -500,
                "account_id": "a1",
                "category_id": "c1",
                "reconciliation_id": None,
                "parent_transaction_id": None,
                "transfer_transaction_id": None,
                "inbox_id": None,
                "date": "2026-04-26",
                "deleted_at": None,
                "version": 1,
                "updated_at": "2026-04-26T10:00:00Z",
                "hashtag_ids": [],
            },
            {
                "id": "t1",
                "user_id": "u1",
                "title": "Lunch",
                "amount_cents": -1200,
                "account_id": "a1",
                "category_id": "c1",
                "reconciliation_id": None,
                "parent_transaction_id": None,
                "transfer_transaction_id": None,
                "inbox_id": None,
                "date": "2026-04-25",
                "deleted_at": "2026-04-26T11:00:00Z",
                "version": 2,
                "updated_at": "2026-04-26T11:00:00Z",
                "hashtag_ids": ["h1"],
            },
        ],
        "reconciliations": [],
        "settings": None,
    }
    respx.get("https://api.example.com/v1/sync").mock(return_value=httpx.Response(200, json=delta))
    with _make_client(cfg) as client:
        summary = cache.delta_sync(client, cfg)

    assert summary.kind == "delta"
    assert summary.sync_token == "token-2"
    assert summary.updates["accounts"] == 1
    assert summary.inserts["transactions"] == 1
    assert summary.tombstones["transactions"] == 1
    assert summary.settings_changed is False

    conn = cache.connect()
    try:
        assert conn.execute("SELECT count(*) FROM transactions").fetchone()[0] == 1
        assert conn.execute("SELECT id FROM transactions").fetchone()[0] == "t2"
        body = conn.execute("SELECT body FROM accounts WHERE id = 'a1'").fetchone()[0]
        assert json.loads(body)["name"] == "BCP renamed"
    finally:
        conn.close()


@respx.mock
def test_cold_start_wipes_existing_rows(cache_path, cfg):
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_FULL_RESPONSE)
    )
    with _make_client(cfg) as client:
        cache.cold_start(client, cfg)

    smaller = {
        "sync_token": "token-3",
        "accounts": [],
        "categories": [
            {
                "id": "c2",
                "user_id": "u1",
                "name": "Solo",
                "is_archived": False,
                "is_system": False,
                "deleted_at": None,
                "sort_order": 1,
                "version": 1,
            }
        ],
        "hashtags": [],
        "inbox": [],
        "transactions": [],
        "reconciliations": [],
        "settings": {"user_id": "u1", "main_currency": "USD", "version": 1},
    }
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=smaller)
    )
    with _make_client(cfg) as client:
        cache.cold_start(client, cfg)

    conn = cache.connect()
    try:
        assert conn.execute("SELECT count(*) FROM accounts").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM transactions").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM categories").fetchone()[0] == 1
        assert conn.execute("SELECT id FROM categories").fetchone()[0] == "c2"
    finally:
        conn.close()


def test_is_healthy_checks_schema_token_client_engine(cache_path):
    fp = cache_state.token_fingerprint("ewe_pat_test")
    conn = cache.connect()
    try:
        cache_state.write_identity(
            conn,
            user_id="u1",
            client_id="cid-1",
            engine_url="https://api.example.com",
            token_fingerprint=fp,
        )
        s = cache_state.read(conn)
        assert cache_state.is_healthy(
            s,
            expected_client_id="cid-1",
            expected_engine_url="https://api.example.com",
            expected_token_fingerprint=fp,
        )
        # token swap — the whole point of the fingerprint
        assert not cache_state.is_healthy(
            s,
            expected_client_id="cid-1",
            expected_engine_url="https://api.example.com",
            expected_token_fingerprint=cache_state.token_fingerprint("ewe_pat_other"),
        )
        assert not cache_state.is_healthy(
            s,
            expected_client_id="cid-2",
            expected_engine_url="https://api.example.com",
            expected_token_fingerprint=fp,
        )
        assert not cache_state.is_healthy(
            s,
            expected_client_id="cid-1",
            expected_engine_url="https://other.example.com",
            expected_token_fingerprint=fp,
        )
    finally:
        conn.close()


def test_is_healthy_requires_identity_written(cache_path):
    conn = cache.connect()
    try:
        s = cache_state.read(conn)  # fresh meta row — cold_start never completed
    finally:
        conn.close()
    assert not cache_state.is_healthy(
        s,
        expected_client_id="cid-1",
        expected_engine_url="https://api.example.com",
        expected_token_fingerprint=cache_state.token_fingerprint("ewe_pat_test"),
    )


def test_is_healthy_rejects_schema_version_mismatch(cache_path, monkeypatch):
    fp = cache_state.token_fingerprint("ewe_pat_test")
    conn = cache.connect()
    try:
        cache_state.write_identity(
            conn,
            user_id="u1",
            client_id="cid-1",
            engine_url="https://api.example.com",
            token_fingerprint=fp,
        )
        s = cache_state.read(conn)
        monkeypatch.setattr(cache_state, "SCHEMA_VERSION", s.schema_version + 1)
        assert not cache_state.is_healthy(
            s,
            expected_client_id="cid-1",
            expected_engine_url="https://api.example.com",
            expected_token_fingerprint=fp,
        )
    finally:
        conn.close()


def test_read_tolerates_pre_v3_meta_schema(cache_path):
    """A v2 cache file lacks the fingerprint column — read() must not raise, so
    the version check (not an IndexError) is what retires the old cache."""
    conn = cache.connect()
    try:
        conn.execute("ALTER TABLE _cache_meta DROP COLUMN token_fingerprint")
        conn.execute("UPDATE _cache_meta SET schema_version = 2 WHERE id = 1")
        s = cache_state.read(conn)
    finally:
        conn.close()
    assert s.token_fingerprint is None
    assert not cache_state.is_healthy(
        s,
        expected_client_id="cid-1",
        expected_engine_url="https://api.example.com",
        expected_token_fingerprint=cache_state.token_fingerprint("ewe_pat_test"),
    )


@respx.mock
def test_ensure_synced_cold_starts_on_token_swap(cache_path, cfg):
    """User B's PAT must never read user A's replica (backlog 1.1)."""
    route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_FULL_RESPONSE)
    )
    with _make_client(cfg) as client:
        cache.cold_start(client, cfg)
    assert route.call_count == 1

    # Unchanged config → healthy replica, no engine call.
    with _make_client(cfg) as client:
        assert cache.ensure_synced(client, cfg, notice_stream=io.StringIO()) is None
    assert route.call_count == 1

    # Same machine, user B's token → fingerprint mismatch forces wipe + cold start.
    cfg_b = Config(engine_url=cfg.engine_url, token="ewe_pat_other", client_id=cfg.client_id)
    response_b = {
        **SYNC_FULL_RESPONSE,
        "sync_token": "token-b",
        "accounts": [{**SYNC_FULL_RESPONSE["accounts"][0], "id": "b1", "user_id": "u2"}],
        "categories": [],
        "hashtags": [],
        "transactions": [],
        "settings": {"user_id": "u2", "main_currency": "PEN", "version": 1},
    }
    route.mock(return_value=httpx.Response(200, json=response_b))
    with _make_client(cfg_b) as client:
        summary = cache.ensure_synced(client, cfg_b, notice_stream=io.StringIO())
    assert summary is not None and summary.kind == "cold_start"

    conn = cache.connect()
    try:
        ids = [r[0] for r in conn.execute("SELECT id FROM accounts")]
        assert ids == ["b1"]  # user A's rows are gone
        assert cache_state.read(conn).user_id == "u2"
    finally:
        conn.close()


@respx.mock
def test_delta_sync_cold_starts_on_token_swap(cache_path, cfg):
    """Bare `expense sync` / post-write refresh must also catch the swap."""
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_FULL_RESPONSE)
    )
    with _make_client(cfg) as client:
        cache.cold_start(client, cfg)

    cfg_b = Config(engine_url=cfg.engine_url, token="ewe_pat_other", client_id=cfg.client_id)
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json={**SYNC_FULL_RESPONSE, "sync_token": "token-b"})
    )
    with _make_client(cfg_b) as client:
        summary = cache.delta_sync(client, cfg_b)
    assert summary.kind == "cold_start"


@respx.mock
def test_delta_with_no_token_falls_through_to_cold_start(cache_path, cfg):
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_FULL_RESPONSE)
    )
    with _make_client(cfg) as client:
        summary = cache.delta_sync(client, cfg)
    assert summary.kind == "cold_start"
    assert summary.sync_token == "token-1"


@respx.mock
def test_delta_with_unknown_token_falls_through_to_cold_start(cache_path, cfg):
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_FULL_RESPONSE)
    )
    with _make_client(cfg) as client:
        cache.cold_start(client, cfg)

    error_body = {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "sync_token is unknown for this client.",
            "fields": {"sync_token": "Unknown token; retry with sync_token=*."},
        }
    }
    sequence = [
        httpx.Response(422, json=error_body),
        httpx.Response(200, json={**SYNC_FULL_RESPONSE, "sync_token": "token-rebuilt"}),
    ]
    respx.get("https://api.example.com/v1/sync").mock(side_effect=sequence)

    with _make_client(cfg) as client:
        summary = cache.delta_sync(client, cfg)
    assert summary.kind == "cold_start"
    assert summary.sync_token == "token-rebuilt"


@respx.mock
def test_delta_with_engine_500_propagates(cache_path, cfg):
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_FULL_RESPONSE)
    )
    with _make_client(cfg) as client:
        cache.cold_start(client, cfg)

    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(
            500, json={"error": {"code": "INTERNAL", "message": "boom", "fields": None}}
        )
    )
    with _make_client(cfg) as client:
        with pytest.raises(EngineError):
            cache.delta_sync(client, cfg)


def test_settings_null_on_delta_is_noop(cache_path):
    conn = cache.connect()
    try:
        cache_sync.apply_response(conn, SYNC_FULL_RESPONSE, kind="cold_start")
        before = conn.execute("SELECT body FROM settings").fetchone()[0]
        delta = {**SYNC_FULL_RESPONSE, "settings": None, "sync_token": "x"}
        for key in cache.RESOURCE_KEYS:
            delta[key] = []
        summary = cache_sync.apply_response(conn, delta, kind="delta")
        assert summary.settings_changed is False
        after = conn.execute("SELECT body FROM settings").fetchone()[0]
        assert before == after
    finally:
        conn.close()


def test_hashtag_ids_round_trip_in_body(cache_path):
    conn = cache.connect()
    try:
        cache_sync.apply_response(conn, SYNC_FULL_RESPONSE, kind="cold_start")
        body = conn.execute("SELECT body FROM transactions WHERE id = 't1'").fetchone()[0]
        assert json.loads(body)["hashtag_ids"] == ["h1"]
    finally:
        conn.close()


def test_wipe_removes_cache_file(cache_path):
    conn = cache.connect()
    try:
        cache_state.write_identity(
            conn, user_id="u1", client_id="c", engine_url="x", token_fingerprint="f"
        )
    finally:
        conn.close()
    assert cache_db.cache_path().exists()
    cache.wipe()
    assert not cache_db.cache_path().exists()


def test_connect_wipes_and_rebuilds_corrupt_cache(cache_path):
    """A garbage cache file is wiped and rebuilt fresh, not a crash."""
    cache_path.write_bytes(b"this is not a sqlite database")
    conn = cache.connect()
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "_cache_meta" in tables
        assert "transactions" in tables
        meta = conn.execute("SELECT * FROM _cache_meta WHERE id = 1").fetchone()
        assert meta["schema_version"] == cache.SCHEMA_VERSION
        # Fresh replica: no identity/token — the next read cold-starts.
        assert meta["user_id"] is None
        assert meta["sync_token"] is None
    finally:
        conn.close()


def test_connect_locked_cache_errors_cleanly_and_survives(cache_path, monkeypatch):
    """A transient lock must not trigger the corruption wipe (backlog 3.5)."""
    conn = cache.connect()  # healthy replica on disk
    conn.close()

    def locked() -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cache_db, "_open", locked)
    with pytest.raises(CacheUnavailableError) as exc:
        cache.connect()

    assert "database is locked" in str(exc.value)
    assert cache_db.cache_path().exists()  # the replica was not destroyed


def test_connect_unopenable_path_errors_cleanly(cache_path):
    """A directory at the cache path is unopenable, not corrupt — no wipe attempt."""
    cache_path.mkdir()
    with pytest.raises(CacheUnavailableError):
        cache.connect()
    assert cache_path.is_dir()


def _seed_accounts(conn, rows: list[dict]) -> None:
    for row in rows:
        conn.execute(
            "INSERT OR REPLACE INTO accounts "
            "(id, user_id, is_archived, is_person, deleted_at, sort_order, version, body) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                row.get("user_id"),
                1 if row.get("is_archived") else 0,
                1 if row.get("is_person") else 0,
                row.get("deleted_at"),
                row.get("sort_order"),
                row.get("version"),
                json.dumps(row),
            ),
        )


def _seed_categories(conn, rows: list[dict]) -> None:
    for row in rows:
        conn.execute(
            "INSERT OR REPLACE INTO categories "
            "(id, user_id, is_archived, is_system, deleted_at, sort_order, version, body) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                row.get("user_id"),
                1 if row.get("is_archived") else 0,
                1 if row.get("is_system") else 0,
                row.get("deleted_at"),
                row.get("sort_order"),
                row.get("version"),
                json.dumps(row),
            ),
        )


def _seed_hashtags(conn, rows: list[dict]) -> None:
    for row in rows:
        conn.execute(
            "INSERT OR REPLACE INTO hashtags "
            "(id, user_id, is_archived, deleted_at, sort_order, version, body) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                row.get("user_id"),
                1 if row.get("is_archived") else 0,
                row.get("deleted_at"),
                row.get("sort_order"),
                row.get("version"),
                json.dumps(row),
            ),
        )


def test_list_accounts_default_excludes_archived_and_people(cache_path):
    conn = cache.connect()
    try:
        _seed_accounts(
            conn,
            [
                {"id": "a1", "user_id": "u1", "name": "Active", "sort_order": 1, "version": 1},
                {
                    "id": "a2",
                    "user_id": "u1",
                    "name": "Old",
                    "is_archived": True,
                    "sort_order": 2,
                    "version": 1,
                },
                {
                    "id": "a3",
                    "user_id": "u1",
                    "name": "Alex",
                    "is_person": True,
                    "sort_order": 3,
                    "version": 1,
                },
            ],
        )
    finally:
        conn.close()
    rows = cache.list_accounts()
    names = [r["name"] for r in rows]
    assert names == ["Active"]


def test_list_accounts_with_includes(cache_path):
    conn = cache.connect()
    try:
        _seed_accounts(
            conn,
            [
                {"id": "a1", "user_id": "u1", "name": "Active", "sort_order": 1, "version": 1},
                {
                    "id": "a2",
                    "user_id": "u1",
                    "name": "Old",
                    "is_archived": True,
                    "sort_order": 2,
                    "version": 1,
                },
                {
                    "id": "a3",
                    "user_id": "u1",
                    "name": "Alex",
                    "is_person": True,
                    "sort_order": 3,
                    "version": 1,
                },
            ],
        )
    finally:
        conn.close()
    assert {r["name"] for r in cache.list_accounts(include_archived=True)} == {"Active", "Old"}
    assert {r["name"] for r in cache.list_accounts(include_people=True)} == {"Active", "Alex"}


def test_list_accounts_sort_order(cache_path):
    conn = cache.connect()
    try:
        _seed_accounts(
            conn,
            [
                {"id": "a1", "user_id": "u1", "name": "Third", "sort_order": 3, "version": 1},
                {"id": "a2", "user_id": "u1", "name": "First", "sort_order": 1, "version": 1},
                {"id": "a3", "user_id": "u1", "name": "Second", "sort_order": 2, "version": 1},
            ],
        )
    finally:
        conn.close()
    assert [r["name"] for r in cache.list_accounts()] == ["First", "Second", "Third"]


def test_get_account_hits_and_miss(cache_path):
    conn = cache.connect()
    try:
        _seed_accounts(
            conn,
            [{"id": "a1", "user_id": "u1", "name": "Hit", "sort_order": 1, "version": 1}],
        )
    finally:
        conn.close()
    body = cache.get_account("a1")
    assert body["name"] == "Hit"

    with pytest.raises(EngineError) as exc:
        cache.get_account("missing")
    assert exc.value.code == "NOT_FOUND"
    assert exc.value.status == 404


def test_list_categories_paginated_shape(cache_path):
    conn = cache.connect()
    try:
        _seed_categories(
            conn,
            [
                {"id": f"c{i}", "user_id": "u1", "name": f"Cat{i}", "sort_order": i, "version": 1}
                for i in range(1, 6)
            ],
        )
    finally:
        conn.close()
    body = cache.list_categories(limit=2, offset=1)
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert [c["name"] for c in body["items"]] == ["Cat2", "Cat3"]


def test_list_hashtags_smoke(cache_path):
    conn = cache.connect()
    try:
        _seed_hashtags(
            conn,
            [
                {"id": "h1", "user_id": "u1", "name": "lunch", "sort_order": 1, "version": 1},
                {
                    "id": "h2",
                    "user_id": "u1",
                    "name": "old",
                    "is_archived": True,
                    "sort_order": 2,
                    "version": 1,
                },
            ],
        )
    finally:
        conn.close()
    body = cache.list_hashtags()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "lunch"


@respx.mock
def test_ensure_synced_no_op_on_healthy_cache(cache_path, cfg, capsys):
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_FULL_RESPONSE)
    )
    with _make_client(cfg) as client:
        cache.cold_start(client, cfg)

    respx.get("https://api.example.com/v1/sync")
    with _make_client(cfg) as client:
        result = cache.ensure_synced(client, cfg)
    assert result is None
    captured = capsys.readouterr()
    assert "First-run sync" not in captured.err


@respx.mock
def test_ensure_synced_cold_starts_empty_cache(cache_path, cfg, capsys):
    sync_route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_FULL_RESPONSE)
    )
    with _make_client(cfg) as client:
        result = cache.ensure_synced(client, cfg)
    assert result is not None
    assert result.kind == "cold_start"
    assert sync_route.called
    captured = capsys.readouterr()
    assert "First-run sync" in captured.err


def _seed_inbox(conn, rows: list[dict]) -> None:
    for row in rows:
        conn.execute(
            "INSERT OR REPLACE INTO inbox "
            "(id, user_id, account_id, category_id, status, date, deleted_at, version, body) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                row.get("user_id"),
                row.get("account_id"),
                row.get("category_id"),
                row.get("status"),
                row.get("date"),
                row.get("deleted_at"),
                row.get("version"),
                json.dumps(row),
            ),
        )


def _seed_reconciliations(conn, rows: list[dict]) -> None:
    for row in rows:
        conn.execute(
            "INSERT OR REPLACE INTO reconciliations "
            "(id, user_id, account_id, status, sort_order, date_end, deleted_at, version, body) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                row.get("user_id"),
                row.get("account_id"),
                row.get("status"),
                row.get("sort_order"),
                row.get("date_end"),
                row.get("deleted_at"),
                row.get("version"),
                json.dumps(row),
            ),
        )


def _seed_transactions(conn, rows: list[dict]) -> None:
    for row in rows:
        conn.execute(
            "INSERT OR REPLACE INTO transactions "
            "(id, user_id, account_id, category_id, reconciliation_id, parent_transaction_id, "
            "transfer_transaction_id, inbox_id, date, deleted_at, version, updated_at, body) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                row.get("user_id"),
                row.get("account_id"),
                row.get("category_id"),
                row.get("reconciliation_id"),
                row.get("parent_transaction_id"),
                row.get("transfer_transaction_id"),
                row.get("inbox_id"),
                row.get("date"),
                row.get("deleted_at"),
                row.get("version"),
                row.get("updated_at"),
                json.dumps(row),
            ),
        )


def test_list_inbox_default_excludes_deleted(cache_path):
    conn = cache.connect()
    try:
        _seed_inbox(
            conn,
            [
                {
                    "id": "i1",
                    "user_id": "u1",
                    "title": "active",
                    "amount_cents": 100,
                    "date": "2026-04-25",
                    "version": 1,
                },
                {
                    "id": "i2",
                    "user_id": "u1",
                    "title": "deleted",
                    "amount_cents": 200,
                    "date": "2026-04-25",
                    "deleted_at": "2026-04-26",
                    "version": 1,
                },
            ],
        )
    finally:
        conn.close()
    body = cache.list_inbox()
    assert body["total"] == 1
    assert body["items"][0]["id"] == "i1"


def test_list_inbox_overdue_filter(cache_path):
    conn = cache.connect()
    try:
        _seed_inbox(
            conn,
            [
                {
                    "id": "future",
                    "user_id": "u1",
                    "title": "x",
                    "amount_cents": 1,
                    "date": "2099-01-01",
                    "version": 1,
                },
                {
                    "id": "past",
                    "user_id": "u1",
                    "title": "x",
                    "amount_cents": 1,
                    "date": "2020-01-01",
                    "version": 1,
                },
            ],
        )
    finally:
        conn.close()
    body = cache.list_inbox(overdue=True, now="2026-07-07T12:00:00+00:00")
    ids = [r["id"] for r in body["items"]]
    assert "past" in ids
    assert "future" not in ids


def test_list_inbox_ready_filter_full_predicate(cache_path):
    conn = cache.connect()
    try:
        _seed_accounts(
            conn,
            [
                {"id": "active-acct", "user_id": "u1", "name": "A", "sort_order": 1, "version": 1},
                {
                    "id": "archived-acct",
                    "user_id": "u1",
                    "name": "Old",
                    "is_archived": True,
                    "sort_order": 2,
                    "version": 1,
                },
            ],
        )
        _seed_categories(
            conn,
            [
                {"id": "active-cat", "user_id": "u1", "name": "C", "sort_order": 1, "version": 1},
            ],
        )
        _seed_inbox(
            conn,
            [
                {
                    "id": "ok",
                    "user_id": "u1",
                    "title": "lunch",
                    "amount_cents": 100,
                    "date": "2026-04-25",
                    "account_id": "active-acct",
                    "category_id": "active-cat",
                    "version": 1,
                },
                {
                    "id": "untitled",
                    "user_id": "u1",
                    "title": "UNTITLED",
                    "amount_cents": 100,
                    "date": "2026-04-25",
                    "account_id": "active-acct",
                    "category_id": "active-cat",
                    "version": 1,
                },
                {
                    "id": "no-amount",
                    "user_id": "u1",
                    "title": "x",
                    "amount_cents": 0,
                    "date": "2026-04-25",
                    "account_id": "active-acct",
                    "category_id": "active-cat",
                    "version": 1,
                },
                {
                    "id": "future",
                    "user_id": "u1",
                    "title": "x",
                    "amount_cents": 100,
                    "date": "2099-12-31",
                    "account_id": "active-acct",
                    "category_id": "active-cat",
                    "version": 1,
                },
                {
                    "id": "no-acct",
                    "user_id": "u1",
                    "title": "x",
                    "amount_cents": 100,
                    "date": "2026-04-25",
                    "account_id": None,
                    "category_id": "active-cat",
                    "version": 1,
                },
                {
                    "id": "archived-acct-ref",
                    "user_id": "u1",
                    "title": "x",
                    "amount_cents": 100,
                    "date": "2026-04-25",
                    "account_id": "archived-acct",
                    "category_id": "active-cat",
                    "version": 1,
                },
                {
                    "id": "missing-cat",
                    "user_id": "u1",
                    "title": "x",
                    "amount_cents": 100,
                    "date": "2026-04-25",
                    "account_id": "active-acct",
                    "category_id": "ghost",
                    "version": 1,
                },
            ],
        )
    finally:
        conn.close()
    body = cache.list_inbox(ready=True, now="2026-07-07T12:00:00+00:00")
    ids = [r["id"] for r in body["items"]]
    assert "ok" in ids
    assert "untitled" not in ids
    assert "no-amount" not in ids
    assert "future" not in ids
    assert "no-acct" not in ids
    assert "archived-acct-ref" not in ids
    assert "missing-cat" not in ids


def _seed_ready_refs(conn) -> None:
    _seed_accounts(
        conn,
        [{"id": "a1", "user_id": "u1", "name": "A", "sort_order": 1, "version": 1}],
    )
    _seed_categories(
        conn,
        [{"id": "c1", "user_id": "u1", "name": "C", "sort_order": 1, "version": 1}],
    )


def _ready_row(id_: str, date: str) -> dict:
    return {
        "id": id_,
        "user_id": "u1",
        "title": "x",
        "amount_cents": 100,
        "date": date,
        "account_id": "a1",
        "category_id": "c1",
        "version": 1,
    }


def test_list_inbox_ready_is_timestamp_not_date(cache_path):
    """Readiness mirrors the engine's `i.date <= now()` — a full timestamp
    comparison, not a calendar-date truncation (backlog 2.3)."""
    conn = cache.connect()
    try:
        _seed_ready_refs(conn)
        _seed_inbox(
            conn,
            [
                _ready_row("earlier-today", "2026-07-07T10:00:00Z"),
                _ready_row("exact-now", "2026-07-07T12:00:00Z"),
                _ready_row("later-today", "2026-07-07T18:00:00Z"),
            ],
        )
    finally:
        conn.close()
    body = cache.list_inbox(ready=True, now="2026-07-07T12:00:00+00:00")
    ids = {r["id"] for r in body["items"]}
    # later-today is the case date('now') got wrong: same UTC day, future timestamp
    assert ids == {"earlier-today", "exact-now"}


def test_list_inbox_overdue_is_timestamp_not_date(cache_path):
    """Overdue mirrors the engine's strict `i.date < now()` — an item earlier
    today IS overdue; exact-now is not."""
    conn = cache.connect()
    try:
        _seed_inbox(
            conn,
            [
                _ready_row("earlier-today", "2026-07-07T10:00:00Z"),
                _ready_row("exact-now", "2026-07-07T12:00:00Z"),
                _ready_row("later-today", "2026-07-07T18:00:00Z"),
            ],
        )
    finally:
        conn.close()
    body = cache.list_inbox(overdue=True, now="2026-07-07T12:00:00+00:00")
    ids = {r["id"] for r in body["items"]}
    assert ids == {"earlier-today"}


def test_list_inbox_ready_and_overdue_combine(cache_path):
    """Both flags combine like the engine's independent conditions: exact-now
    is ready (<=) but not overdue (<)."""
    conn = cache.connect()
    try:
        _seed_ready_refs(conn)
        _seed_inbox(
            conn,
            [
                _ready_row("earlier-today", "2026-07-07T10:00:00Z"),
                _ready_row("exact-now", "2026-07-07T12:00:00Z"),
            ],
        )
    finally:
        conn.close()
    body = cache.list_inbox(ready=True, overdue=True, now="2026-07-07T12:00:00+00:00")
    ids = {r["id"] for r in body["items"]}
    assert ids == {"earlier-today"}


def test_list_inbox_offset_aware_dates_compare_correctly(cache_path):
    """'2026-07-07T08:00:00-05:00' is 13:00Z — SQLite datetime() must
    normalize the offset so the comparison matches the engine's UTC now()."""
    conn = cache.connect()
    try:
        _seed_ready_refs(conn)
        _seed_inbox(conn, [_ready_row("lima", "2026-07-07T08:00:00-05:00")])
    finally:
        conn.close()
    at_noon = cache.list_inbox(ready=True, now="2026-07-07T12:00:00+00:00")
    assert at_noon["items"] == []
    at_one = cache.list_inbox(ready=True, now="2026-07-07T13:00:00+00:00")
    assert [r["id"] for r in at_one["items"]] == ["lima"]


def test_get_inbox_hit_and_miss(cache_path):
    conn = cache.connect()
    try:
        _seed_inbox(
            conn,
            [
                {
                    "id": "ib1",
                    "user_id": "u1",
                    "title": "x",
                    "amount_cents": 1,
                    "date": "2026-04-25",
                    "version": 1,
                }
            ],
        )
    finally:
        conn.close()
    assert cache.get_inbox("ib1")["title"] == "x"
    with pytest.raises(EngineError) as exc:
        cache.get_inbox("missing")
    assert exc.value.code == "NOT_FOUND"


def test_list_reconciliations_account_filter(cache_path):
    conn = cache.connect()
    try:
        _seed_reconciliations(
            conn,
            [
                {"id": "r1", "user_id": "u1", "account_id": "a1", "sort_order": 1, "version": 1},
                {"id": "r2", "user_id": "u1", "account_id": "a1", "sort_order": 2, "version": 1},
                {"id": "r3", "user_id": "u1", "account_id": "a2", "sort_order": 1, "version": 1},
            ],
        )
    finally:
        conn.close()
    body = cache.list_reconciliations(account_id="a1")
    assert body["total"] == 2
    assert [i["id"] for i in body["items"]] == ["r1", "r2"]


def test_get_reconciliation_with_embedded_transactions(cache_path):
    conn = cache.connect()
    try:
        _seed_reconciliations(
            conn,
            [
                {
                    "id": "r1",
                    "user_id": "u1",
                    "account_id": "a1",
                    "sort_order": 1,
                    "version": 1,
                    "name": "April",
                }
            ],
        )
        _seed_transactions(
            conn,
            [
                {
                    "id": "t1",
                    "user_id": "u1",
                    "reconciliation_id": "r1",
                    "date": "2026-04-15",
                    "version": 1,
                    "updated_at": "2026-04-15",
                    "created_at": "2026-04-15T12:00:00Z",
                },
                {
                    "id": "t2",
                    "user_id": "u1",
                    "reconciliation_id": "r1",
                    "date": "2026-04-14",
                    "version": 1,
                    "updated_at": "2026-04-14",
                    "created_at": "2026-04-14T12:00:00Z",
                },
                {
                    "id": "t-other",
                    "user_id": "u1",
                    "reconciliation_id": "r2",
                    "date": "2026-04-15",
                    "version": 1,
                    "updated_at": "2026-04-15",
                    "created_at": "2026-04-15T12:00:00Z",
                },
            ],
        )
    finally:
        conn.close()
    body = cache.get_reconciliation("r1")
    assert body["id"] == "r1"
    assert body["transactions_total"] == 2
    assert [t["id"] for t in body["transactions"]] == ["t1", "t2"]
    assert body["transactions_truncated"] is False


def test_get_reconciliation_pagination(cache_path):
    conn = cache.connect()
    try:
        _seed_reconciliations(
            conn,
            [{"id": "r1", "user_id": "u1", "account_id": "a1", "sort_order": 1, "version": 1}],
        )
        _seed_transactions(
            conn,
            [
                {
                    "id": f"t{i}",
                    "user_id": "u1",
                    "reconciliation_id": "r1",
                    "date": f"2026-04-{i:02d}",
                    "version": 1,
                    "updated_at": f"2026-04-{i:02d}",
                    "created_at": f"2026-04-{i:02d}T12:00:00Z",
                }
                for i in range(1, 6)
            ],
        )
    finally:
        conn.close()
    body = cache.get_reconciliation("r1", embedded_limit=2, embedded_offset=0)
    assert body["transactions_total"] == 5
    assert body["transactions_limit"] == 2
    assert body["transactions_offset"] == 0
    assert len(body["transactions"]) == 2
    assert body["transactions_truncated"] is True


def test_get_reconciliation_not_found(cache_path):
    with pytest.raises(EngineError) as exc:
        cache.get_reconciliation("missing")
    assert exc.value.code == "NOT_FOUND"


def _tx_row(**overrides) -> dict:
    base = {
        "user_id": "u1",
        "title": "Lunch",
        "description": "burrito place",
        "amount_cents": -1200,
        "amount_home_cents": -1200,
        "account_id": "a1",
        "category_id": "c1",
        "reconciliation_id": None,
        "parent_transaction_id": None,
        "transfer_transaction_id": None,
        "inbox_id": None,
        "date": "2026-04-25",
        "deleted_at": None,
        "version": 1,
        "updated_at": "2026-04-25T10:00:00Z",
        "created_at": "2026-04-25T10:00:00Z",
        "cleared": False,
        "hashtag_ids": [],
    }
    base.update(overrides)
    return base


def _seed_transactions_local(conn, rows: list[dict]) -> None:
    for row in rows:
        conn.execute(
            "INSERT OR REPLACE INTO transactions "
            "(id, user_id, account_id, category_id, reconciliation_id, parent_transaction_id, "
            "transfer_transaction_id, inbox_id, date, deleted_at, version, updated_at, body) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                row.get("user_id"),
                row.get("account_id"),
                row.get("category_id"),
                row.get("reconciliation_id"),
                row.get("parent_transaction_id"),
                row.get("transfer_transaction_id"),
                row.get("inbox_id"),
                row.get("date"),
                row.get("deleted_at"),
                row.get("version"),
                row.get("updated_at"),
                json.dumps(row),
            ),
        )


def test_list_transactions_orders_date_desc(cache_path):
    conn = cache.connect()
    try:
        _seed_transactions_local(
            conn,
            [
                _tx_row(id="t1", date="2026-04-23"),
                _tx_row(id="t2", date="2026-04-25"),
                _tx_row(id="t3", date="2026-04-24"),
            ],
        )
    finally:
        conn.close()
    body = cache.list_transactions()
    assert body["total"] == 3
    assert [r["id"] for r in body["items"]] == ["t2", "t3", "t1"]


def test_list_transactions_includes_hashtag_ids(cache_path):
    """Engine A+ embeds hashtag_ids on every transaction-returning endpoint;
    cache mirrors that — no strip on the cached list path."""
    conn = cache.connect()
    try:
        _seed_transactions_local(
            conn,
            [_tx_row(id="t1", hashtag_ids=["h1", "h2"])],
        )
    finally:
        conn.close()
    body = cache.list_transactions()
    assert body["items"][0]["hashtag_ids"] == ["h1", "h2"]


def test_list_transactions_account_filter(cache_path):
    conn = cache.connect()
    try:
        _seed_transactions_local(
            conn,
            [
                _tx_row(id="t1", account_id="a1"),
                _tx_row(id="t2", account_id="a2"),
            ],
        )
    finally:
        conn.close()
    body = cache.list_transactions(account_id="a1")
    assert body["total"] == 1
    assert body["items"][0]["id"] == "t1"


def test_list_transactions_date_range(cache_path):
    conn = cache.connect()
    try:
        _seed_transactions_local(
            conn,
            [
                _tx_row(id="t1", date="2026-03-15"),
                _tx_row(id="t2", date="2026-04-15"),
                _tx_row(id="t3", date="2026-05-15"),
            ],
        )
    finally:
        conn.close()
    body = cache.list_transactions(date_from="2026-04-01", date_to="2026-04-30")
    ids = [r["id"] for r in body["items"]]
    assert ids == ["t2"]


def test_list_transactions_cleared_filter(cache_path):
    conn = cache.connect()
    try:
        _seed_transactions_local(
            conn,
            [
                _tx_row(id="t1", cleared=True),
                _tx_row(id="t2", cleared=False),
            ],
        )
    finally:
        conn.close()
    assert [r["id"] for r in cache.list_transactions(cleared=True)["items"]] == ["t1"]
    assert [r["id"] for r in cache.list_transactions(cleared=False)["items"]] == ["t2"]


def test_list_transactions_hashtag_filter_uses_json_each(cache_path):
    conn = cache.connect()
    try:
        _seed_transactions_local(
            conn,
            [
                _tx_row(id="t1", hashtag_ids=["h1", "h2"]),
                _tx_row(id="t2", hashtag_ids=["h2"]),
                _tx_row(id="t3", hashtag_ids=[]),
            ],
        )
    finally:
        conn.close()
    body = cache.list_transactions(hashtag_id="h1")
    ids = [r["id"] for r in body["items"]]
    assert ids == ["t1"]
    body2 = cache.list_transactions(hashtag_id="h2")
    assert sorted(r["id"] for r in body2["items"]) == ["t1", "t2"]


def test_list_transactions_search_case_insensitive(cache_path):
    conn = cache.connect()
    try:
        _seed_transactions_local(
            conn,
            [
                _tx_row(id="t1", title="Coffee shop", description="downtown"),
                _tx_row(id="t2", title="Lunch", description="WITH coworker"),
                _tx_row(id="t3", title="Dinner", description="quiet evening"),
            ],
        )
    finally:
        conn.close()
    assert [r["id"] for r in cache.list_transactions(search="COFFEE")["items"]] == ["t1"]
    assert [r["id"] for r in cache.list_transactions(search="coworker")["items"]] == ["t2"]


def test_list_transactions_combined_filters(cache_path):
    conn = cache.connect()
    try:
        _seed_transactions_local(
            conn,
            [
                _tx_row(id="t1", account_id="a1", date="2026-04-15", cleared=True),
                _tx_row(id="t2", account_id="a1", date="2026-04-20", cleared=False),
                _tx_row(id="t3", account_id="a2", date="2026-04-15", cleared=True),
            ],
        )
    finally:
        conn.close()
    body = cache.list_transactions(account_id="a1", cleared=True)
    assert [r["id"] for r in body["items"]] == ["t1"]


def test_list_transactions_pagination(cache_path):
    conn = cache.connect()
    try:
        _seed_transactions_local(
            conn,
            [_tx_row(id=f"t{i}", date=f"2026-04-{i:02d}") for i in range(1, 6)],
        )
    finally:
        conn.close()
    body = cache.list_transactions(limit=2, offset=0)
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert len(body["items"]) == 2


def test_list_transactions_excludes_deleted(cache_path):
    conn = cache.connect()
    try:
        _seed_transactions_local(
            conn,
            [
                _tx_row(id="t1"),
                _tx_row(id="t2", deleted_at="2026-04-26"),
            ],
        )
    finally:
        conn.close()
    ids = [r["id"] for r in cache.list_transactions()["items"]]
    assert "t1" in ids
    assert "t2" not in ids


def test_get_transaction_includes_hashtag_ids(cache_path):
    """Engine A+ embeds hashtag_ids on GET /v1/transactions/{id}; cache mirrors."""
    conn = cache.connect()
    try:
        _seed_transactions_local(conn, [_tx_row(id="t1", hashtag_ids=["h1"])])
    finally:
        conn.close()
    body = cache.get_transaction("t1")
    assert body["hashtag_ids"] == ["h1"]
    assert body["id"] == "t1"


def test_get_transaction_not_found(cache_path):
    with pytest.raises(EngineError) as exc:
        cache.get_transaction("missing")
    assert exc.value.code == "NOT_FOUND"


# ---------------------------------------------------------------------------
# refresh_after_write (Step 7b.3)
# ---------------------------------------------------------------------------


@respx.mock
def test_refresh_after_write_skips_when_no_cache(cache_path, cfg, capsys):
    sync_route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_FULL_RESPONSE)
    )
    with _make_client(cfg) as client:
        cache.cold_start(client, cfg)

    sync_route.reset()
    with _make_client(cfg) as client:
        result = cache.refresh_after_write(client, cfg, no_cache=True, no_sync_after=False)

    assert result is None
    assert not sync_route.called


@respx.mock
def test_refresh_after_write_skips_when_no_sync_after(cache_path, cfg):
    sync_route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_FULL_RESPONSE)
    )
    with _make_client(cfg) as client:
        cache.cold_start(client, cfg)

    sync_route.reset()
    with _make_client(cfg) as client:
        result = cache.refresh_after_write(client, cfg, no_cache=False, no_sync_after=True)

    assert result is None
    assert not sync_route.called


@respx.mock
def test_refresh_after_write_skips_when_cache_file_missing(cache_path, cfg):
    sync_route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_FULL_RESPONSE)
    )
    assert not cache_db.cache_path().exists()
    with _make_client(cfg) as client:
        result = cache.refresh_after_write(client, cfg, no_cache=False, no_sync_after=False)

    assert result is None
    assert not sync_route.called


@respx.mock
def test_refresh_after_write_runs_delta_on_healthy_cache(cache_path, cfg):
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_FULL_RESPONSE)
    )
    with _make_client(cfg) as client:
        cache.cold_start(client, cfg)

    delta = {**SYNC_FULL_RESPONSE, "sync_token": "token-after-write"}
    for key in cache.RESOURCE_KEYS:
        delta[key] = []
    respx.get("https://api.example.com/v1/sync").mock(return_value=httpx.Response(200, json=delta))

    with _make_client(cfg) as client:
        result = cache.refresh_after_write(client, cfg, no_cache=False, no_sync_after=False)

    assert result is not None
    assert result.kind == "delta"
    assert result.sync_token == "token-after-write"


@respx.mock
def test_refresh_after_write_swallows_engine_errors(cache_path, cfg, capsys):
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_FULL_RESPONSE)
    )
    with _make_client(cfg) as client:
        cache.cold_start(client, cfg)

    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(
            500, json={"error": {"code": "INTERNAL", "message": "boom", "fields": None}}
        )
    )
    with _make_client(cfg) as client:
        result = cache.refresh_after_write(client, cfg, no_cache=False, no_sync_after=False)

    assert result is None
    captured = capsys.readouterr()
    assert "Cache refresh failed after write" in captured.err
    assert "expense sync" in captured.err
