"""Contract lifecycle: create → update → archive → unarchive → delete → restore.

Hits the real engine. Gated on PYTEST_LIVE=1. Requires EXPENSE_ENGINE_URL and
EXPENSE_PAT env vars (or a populated ~/.expense-config) — uses ExpenseClient
directly so each test owns its idempotency keys.
"""

import os
from uuid import uuid4

import pytest

from expense import config as config_module
from expense.commands._resource import fetch_all_pages
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


def _list_all(client, resource: str, **flags) -> list[dict]:
    """Page through the whole collection.

    List endpoints serve default-limit pages — including /accounts, which
    engine-spec.md documents as unpaginated ("returns all") but which caps at
    50 and honors limit/offset (contract gap found by this gate 2026-07-08).
    Unpaginated reads went flaky once gate-run tombstones passed the cap.
    """
    params = {flag: "true" for flag, on in flags.items() if on}
    return fetch_all_pages(
        lambda limit, offset: client.get(
            f"/{resource}", params={**params, "limit": str(limit), "offset": str(offset)}
        )
    )


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

        active = _list_all(client, "accounts")
        assert any(a["id"] == new_id for a in active)

        client.post(f"/accounts/{new_id}/archive")
        active_after = _list_all(client, "accounts")
        assert not any(a["id"] == new_id for a in active_after)

        archived = _list_all(client, "accounts", include_archived=True)
        assert any(a["id"] == new_id for a in archived)

        client.post(f"/accounts/{new_id}/unarchive")
        client.delete(f"/accounts/{new_id}")
        deleted = _list_all(client, "accounts", include_deleted=True)
        assert any(a["id"] == new_id for a in deleted)

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
        active_after = _list_all(client, "categories")
        assert not any(c["id"] == new_id for c in active_after)

        client.post(f"/categories/{new_id}/unarchive")
        client.delete(f"/categories/{new_id}")
        deleted = _list_all(client, "categories", include_deleted=True)
        assert any(c["id"] == new_id for c in deleted)

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
        active_after = _list_all(client, "hashtags")
        assert not any(h["id"] == new_id for h in active_after)

        client.post(f"/hashtags/{new_id}/unarchive")
        client.delete(f"/hashtags/{new_id}")
        deleted = _list_all(client, "hashtags", include_deleted=True)
        assert any(h["id"] == new_id for h in deleted)

        client.post(f"/hashtags/{new_id}/restore")
    finally:
        try:
            client.delete(f"/hashtags/{new_id}")
        except Exception:
            pass
