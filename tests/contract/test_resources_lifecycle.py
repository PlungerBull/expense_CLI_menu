"""Contract lifecycle: create → update → archive → unarchive → delete → restore.

Hits the real engine. Gated on PYTEST_LIVE=1. Requires EXPENSE_ENGINE_URL and
EXPENSE_PAT env vars (or a populated ~/.expense-config) — uses ExpenseClient
directly so each test owns its idempotency keys.
"""

import os
from uuid import uuid4

import pytest

from expense import config as config_module
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


def test_accounts_lifecycle(client):
    new_id = str(uuid4())
    name = f"contract-account-{new_id[:8]}"

    created = client.post(
        "/accounts",
        json_body={"id": new_id, "name": name, "currency_code": "USD"},
    )
    try:
        assert created["id"] == new_id
        assert created["name"] == name

        fetched = client.get(f"/accounts/{new_id}")
        assert fetched["id"] == new_id

        updated = client.put(f"/accounts/{new_id}", json_body={"name": f"{name}-renamed"})
        assert updated["name"] == f"{name}-renamed"

        active = client.get("/accounts")
        assert any(a["id"] == new_id for a in _items(active))

        client.post(f"/accounts/{new_id}/archive")
        active_after = client.get("/accounts")
        assert not any(a["id"] == new_id for a in _items(active_after))

        archived = client.get("/accounts", params={"include_archived": "true"})
        assert any(a["id"] == new_id for a in _items(archived))

        client.post(f"/accounts/{new_id}/unarchive")
        client.delete(f"/accounts/{new_id}")
        deleted = client.get("/accounts", params={"include_deleted": "true"})
        assert any(a["id"] == new_id for a in _items(deleted))

        client.post(f"/accounts/{new_id}/restore")
    finally:
        # Best-effort cleanup; ignore if already deleted/restored.
        try:
            client.delete(f"/accounts/{new_id}")
        except Exception:
            pass


def test_categories_lifecycle(client):
    new_id = str(uuid4())
    name = f"contract-cat-{new_id[:8]}"

    created = client.post(
        "/categories",
        json_body={"id": new_id, "name": name, "color": "#123456"},
    )
    try:
        assert created["id"] == new_id

        fetched = client.get(f"/categories/{new_id}")
        assert fetched["id"] == new_id

        updated = client.put(f"/categories/{new_id}", json_body={"name": f"{name}-renamed"})
        assert updated["name"] == f"{name}-renamed"

        client.post(f"/categories/{new_id}/archive")
        active_after = client.get("/categories")
        assert not any(c["id"] == new_id for c in _items(active_after))

        client.post(f"/categories/{new_id}/unarchive")
        client.delete(f"/categories/{new_id}")
        deleted = client.get("/categories", params={"include_deleted": "true"})
        assert any(c["id"] == new_id for c in _items(deleted))

        client.post(f"/categories/{new_id}/restore")
    finally:
        try:
            client.delete(f"/categories/{new_id}")
        except Exception:
            pass


def test_hashtags_lifecycle(client):
    new_id = str(uuid4())
    name = f"contract-tag-{new_id[:8]}"

    created = client.post("/hashtags", json_body={"id": new_id, "name": name})
    try:
        assert created["id"] == new_id

        fetched = client.get(f"/hashtags/{new_id}")
        assert fetched["id"] == new_id

        updated = client.put(f"/hashtags/{new_id}", json_body={"name": f"{name}-renamed"})
        assert updated["name"] == f"{name}-renamed"

        client.post(f"/hashtags/{new_id}/archive")
        active_after = client.get("/hashtags")
        assert not any(h["id"] == new_id for h in _items(active_after))

        client.post(f"/hashtags/{new_id}/unarchive")
        client.delete(f"/hashtags/{new_id}")
        deleted = client.get("/hashtags", params={"include_deleted": "true"})
        assert any(h["id"] == new_id for h in _items(deleted))

        client.post(f"/hashtags/{new_id}/restore")
    finally:
        try:
            client.delete(f"/hashtags/{new_id}")
        except Exception:
            pass


def _items(body):
    """Engine returns either a bare list or a paginated {items, total, ...} envelope."""
    if isinstance(body, dict) and "items" in body:
        return body["items"]
    return body
