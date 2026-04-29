import json
from uuid import uuid4

import httpx
import pytest
import respx

from expense import cache
from expense.cache import db as cache_db
from expense.cache import state as cache_state
from expense.cache import sync as cache_sync
from expense.config import Config
from expense.errors import EngineError
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


def test_is_healthy_checks_schema_user_engine(cache_path):
    conn = cache.connect()
    try:
        cache_state.write_identity(
            conn, user_id="u1", client_id="cid-1", engine_url="https://api.example.com"
        )
        s = cache_state.read(conn)
        assert cache_state.is_healthy(
            s,
            expected_user_id="u1",
            expected_client_id="cid-1",
            expected_engine_url="https://api.example.com",
        )
        assert not cache_state.is_healthy(
            s,
            expected_user_id="u2",
            expected_client_id="cid-1",
            expected_engine_url="https://api.example.com",
        )
        assert not cache_state.is_healthy(
            s,
            expected_user_id="u1",
            expected_client_id="cid-2",
            expected_engine_url="https://api.example.com",
        )
        assert not cache_state.is_healthy(
            s,
            expected_user_id="u1",
            expected_client_id="cid-1",
            expected_engine_url="https://other.example.com",
        )
    finally:
        conn.close()


def test_is_healthy_rejects_schema_version_mismatch(cache_path, monkeypatch):
    conn = cache.connect()
    try:
        cache_state.write_identity(
            conn, user_id="u1", client_id="cid-1", engine_url="https://api.example.com"
        )
        s = cache_state.read(conn)
        monkeypatch.setattr(cache_state, "SCHEMA_VERSION", s.schema_version + 1)
        assert not cache_state.is_healthy(
            s,
            expected_user_id="u1",
            expected_client_id="cid-1",
            expected_engine_url="https://api.example.com",
        )
    finally:
        conn.close()


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
        cache_state.write_identity(conn, user_id="u1", client_id="c", engine_url="x")
    finally:
        conn.close()
    assert cache_db.cache_path().exists()
    cache.wipe()
    assert not cache_db.cache_path().exists()
