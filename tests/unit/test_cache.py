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
