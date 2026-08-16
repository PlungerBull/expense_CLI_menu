"""Contract lifecycle for transactions against the live engine.

Each test creates the supporting account/category, exercises the full lifecycle,
then cleans up. Gated on PYTEST_LIVE=1.
"""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from expense import config as config_module
from expense.errors import EngineError
from expense.http import ExpenseClient

pytestmark = pytest.mark.skipif(
    os.environ.get("PYTEST_LIVE") != "1",
    reason="Contract tests require PYTEST_LIVE=1",
)


@pytest.fixture
def client():
    cfg = config_module.ensure_loaded()
    with ExpenseClient(cfg) as c:
        yield c


def _safe_delete(client, path):
    try:
        client.delete(path)
    except EngineError:
        pass


def _make_account(client, currency_code="PEN"):
    new_id = str(uuid4())
    client.post(
        "/accounts",
        json_body={
            "id": new_id,
            "name": f"contract-acct-{new_id[:8]}",
            "currency_code": currency_code,
        },
    )
    return new_id


def _make_category(client):
    new_id = str(uuid4())
    client.post(
        "/categories",
        json_body={
            "id": new_id,
            "name": f"contract-cat-{new_id[:8]}",
            "color": "#123456",
        },
    )
    return new_id


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def test_transactions_lifecycle(client):
    account_id = _make_account(client)
    category_id = _make_category(client)
    tx_id = str(uuid4())

    try:
        created = client.post(
            "/transactions",
            json_body={
                "id": tx_id,
                "title": "coffee",
                "amount_cents": -500,
                "account_id": account_id,
                "category_id": category_id,
                "date": _now_iso(),
            },
        )
        assert created["id"] == tx_id

        fetched = client.get(f"/transactions/{tx_id}")
        assert fetched["id"] == tx_id
        assert fetched["title"] == "coffee"

        listed = client.get("/transactions", params={"account_id": account_id})
        assert any(item["id"] == tx_id for item in listed["items"])

        updated = client.put(
            f"/transactions/{tx_id}",
            json_body={"title": "cafe latte"},
        )
        assert updated["title"] == "cafe latte"

        deleted = client.delete(f"/transactions/{tx_id}")
        assert deleted["id"] == tx_id
        assert deleted.get("deleted_at") is not None
        assert isinstance(deleted.get("warnings"), list)

        restored = client.post(f"/transactions/{tx_id}/restore")
        assert restored["id"] == tx_id
        assert restored.get("deleted_at") is None
        assert isinstance(restored.get("warnings"), list)
    finally:
        _safe_delete(client, f"/transactions/{tx_id}")
        _safe_delete(client, f"/categories/{category_id}")
        _safe_delete(client, f"/accounts/{account_id}")


def test_batch_create(client):
    account_id = _make_account(client)
    category_id = _make_category(client)
    ids = [str(uuid4()) for _ in range(3)]

    try:
        body = client.post(
            "/transactions/batch",
            json_body={
                "transactions": [
                    {
                        "id": ids[0],
                        "title": "a",
                        "amount_cents": -100,
                        "account_id": account_id,
                        "category_id": category_id,
                        "date": _now_iso(),
                    },
                    {
                        "id": ids[1],
                        "title": "b",
                        "amount_cents": -200,
                        "account_id": account_id,
                        "category_id": category_id,
                        "date": _now_iso(),
                    },
                    {
                        "id": ids[2],
                        "title": "c",
                        "amount_cents": -300,
                        "account_id": account_id,
                        "category_id": category_id,
                        "date": _now_iso(),
                    },
                ]
            },
        )
        created = body.get("created", [])
        assert {item["id"] for item in created} == set(ids)
    finally:
        for tx_id in ids:
            _safe_delete(client, f"/transactions/{tx_id}")
        _safe_delete(client, f"/categories/{category_id}")
        _safe_delete(client, f"/accounts/{account_id}")
