"""Contract lifecycle for inbox + log against a real engine.

Each test creates the supporting account/category, exercises the full lifecycle,
then cleans up. Gating, target resolution and the real-ledger guard live in
conftest.py.
"""

from datetime import UTC, datetime
from uuid import uuid4

from expense.errors import EngineError


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


def test_inbox_lifecycle(client):
    account_id = _make_account(client)
    category_id = _make_category(client)
    inbox_id = str(uuid4())
    transaction_id = str(uuid4())

    try:
        # Add a sparse draft (title + amount only).
        added = client.post(
            "/inbox",
            json_body={"id": inbox_id, "title": "lunch", "amount_cents": -2500},
        )
        assert added["id"] == inbox_id
        assert added["title"] == "lunch"

        # Confirm it shows up in the active list.
        listed = client.get("/inbox")
        assert any(item["id"] == inbox_id for item in listed["items"])

        # Try promoting prematurely — should 422 because account/category/date are missing.
        try:
            client.post(
                f"/inbox/{inbox_id}/promote",
                json_body={"id": str(uuid4())},
            )
            raise AssertionError("Expected 422 on premature promote")
        except EngineError as err:
            assert err.status == 422

        # Fill in the missing fields.
        client.put(
            f"/inbox/{inbox_id}",
            json_body={
                "account_id": account_id,
                "category_id": category_id,
                "date": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            },
        )

        # Promote — should succeed and return the new transaction.
        promoted = client.post(
            f"/inbox/{inbox_id}/promote",
            json_body={"id": transaction_id},
        )
        assert promoted["id"] == transaction_id
        assert promoted["title"] == "lunch"
        assert promoted["inbox_id"] == inbox_id

        # Inbox item is no longer in the active (PENDING) list after promote.
        active = client.get("/inbox")
        assert not any(item["id"] == inbox_id for item in active["items"])
    finally:
        _safe_delete(client, f"/transactions/{transaction_id}")
        _safe_delete(client, f"/inbox/{inbox_id}")
        _safe_delete(client, f"/categories/{category_id}")
        _safe_delete(client, f"/accounts/{account_id}")


def test_log_lifecycle(client):
    account_id = _make_account(client)
    category_id = _make_category(client)
    transaction_id = str(uuid4())

    try:
        created = client.post(
            "/transactions",
            json_body={
                "id": transaction_id,
                "title": "coffee",
                "amount_cents": -500,
                "account_id": account_id,
                "category_id": category_id,
                "date": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            },
        )
        assert created["id"] == transaction_id
        assert created["title"] == "coffee"
        # Engine stores positive amount, records direction in transaction_type.
        assert created["amount_cents"] == 500
        assert created["transaction_type"] == 1  # 1 = EXPENSE
    finally:
        _safe_delete(client, f"/transactions/{transaction_id}")
        _safe_delete(client, f"/categories/{category_id}")
        _safe_delete(client, f"/accounts/{account_id}")
