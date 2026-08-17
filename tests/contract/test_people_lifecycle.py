"""Contract lifecycle for the People API against a real engine.

Additive engine capability, 2026-08-14 (backlog 6.2). **This is the only check
that can see this feature at all.** The fast suite mocks the engine with recorded
fixtures, and a recorded fixture cannot grow an endpoint that did not exist when
it was written; `scripts/check_fixture_drift.py` is blind here too, since it only
reports fields the engine has *stopped* serving. Unit-green therefore says
nothing about whether `POST /people` works — this file does.

What it pins, in the order the client meets it:

1. `POST /people` creates a person: `is_person = true`, balance `0`.
2. `is_person` in the body is a `422` on **both** routes — the endpoint is the
   flag, and the client never sends the field on either.
3. The name key is **shared** with bank accounts within a currency (`409`), not
   scoped per list.
4. A person refuses an opening balance (`422`) — a debt is built from recorded
   rows, not seeded.
5. Everything after creation is an *account* route: `GET`, `PUT`, `/archive`,
   `/unarchive`, `DELETE` all accept the person row. There is no `GET /people`.
6. She is listed by `GET /accounts?include_people=true`, appears in the
   dashboard's `people` panel, and moves to `archived_people` — a panel distinct
   from `archived_accounts` — when archived.

Gating, target resolution and the real-ledger guard live in conftest.py.
"""

from uuid import uuid4

from expense.errors import EngineError


def _safe_delete(client, path):
    try:
        client.delete(path)
    except EngineError:
        pass


def _expect_status(call, status: int, what: str):
    try:
        call()
    except EngineError as err:
        assert err.status == status, f"{what}: expected {status}, got {err.status}"
        return
    raise AssertionError(f"{what}: expected {status}, the write succeeded")


def _names(rows) -> set[str]:
    return {row.get("name") for row in rows or []}


def test_people_lifecycle(client):
    person_id = str(uuid4())
    name = f"contract-person-{person_id[:8]}"
    account_id = str(uuid4())

    created = client.post(
        "/people",
        json_body={"id": person_id, "name": name, "currency_code": "PEN"},
    )
    try:
        # 1 — the flag the client could never set, now set by the endpoint.
        assert created["id"] == person_id
        assert created["is_person"] is True
        assert created["current_balance_cents"] == 0

        # 2 — `is_person` is forbidden on both routes, so the CLI sends it on
        # neither. Sending it fails closed: the whole write is rejected.
        _expect_status(
            lambda: client.post(
                "/people",
                json_body={
                    "id": str(uuid4()),
                    "name": f"{name}-flag",
                    "currency_code": "PEN",
                    "is_person": True,
                },
            ),
            422,
            "is_person on POST /people",
        )
        _expect_status(
            lambda: client.post(
                "/accounts",
                json_body={
                    "id": str(uuid4()),
                    "name": f"{name}-acct-flag",
                    "currency_code": "PEN",
                    "is_person": True,
                },
            ),
            422,
            "is_person on POST /accounts",
        )

        # 3 — one name list per currency, spanning people AND bank accounts.
        # This is why `create-person` explains the collision instead of letting
        # a bare CONFLICT through.
        _expect_status(
            lambda: client.post(
                "/accounts",
                json_body={"id": account_id, "name": name, "currency_code": "PEN"},
            ),
            409,
            "bank account colliding with a person's name",
        )

        # 4 — a person's balance is built from rows, never seeded.
        _expect_status(
            lambda: client.post(
                f"/accounts/{person_id}/opening-balance",
                json_body={
                    "transaction_id": str(uuid4()),
                    "amount_cents": 10000,
                    "date": "2026-01-01T00:00:00Z",
                },
            ),
            422,
            "opening balance on a person",
        )

        # 5 — after creation she is an ordinary account row on ordinary routes.
        fetched = client.get(f"/accounts/{person_id}")
        assert fetched["is_person"] is True

        renamed = client.put(f"/accounts/{person_id}", json_body={"name": f"{name}-renamed"})
        assert renamed["name"] == f"{name}-renamed"
        assert renamed["is_person"] is True  # a rename never flips the flag

        # 6 — where she shows up, and where she moves when archived.
        listed = client.get("/accounts", params={"include_people": "true", "limit": "200"})
        rows = listed["items"] if isinstance(listed, dict) else listed
        assert person_id in {row.get("id") for row in rows}

        # Excluded from the default list, which is bank accounts only.
        plain = client.get("/accounts", params={"limit": "200"})
        plain_rows = plain["items"] if isinstance(plain, dict) else plain
        assert person_id not in {row.get("id") for row in plain_rows}

        dashboard = client.get("/dashboard", params={"include_archived": "true"})
        assert f"{name}-renamed" in _names(dashboard.get("people"))
        # The two archived panels are separate and never mix.
        assert f"{name}-renamed" not in _names(dashboard.get("archived_accounts"))

        client.post(f"/accounts/{person_id}/archive")
        archived = client.get("/dashboard", params={"include_archived": "true"})
        assert f"{name}-renamed" not in _names(archived.get("people"))
        assert f"{name}-renamed" in _names(archived.get("archived_people"))
        assert f"{name}-renamed" not in _names(archived.get("archived_accounts"))

        # `archived_people` is null-not-omitted without the flag (the CLI's
        # `is not None` panel gate depends on exactly this).
        default_view = client.get("/dashboard")
        assert default_view["archived_people"] is None
        assert default_view["archived_accounts"] is None

        client.post(f"/accounts/{person_id}/unarchive")
        back = client.get("/dashboard", params={"include_archived": "true"})
        assert f"{name}-renamed" in _names(back.get("people"))
    finally:
        _safe_delete(client, f"/accounts/{person_id}")
        _safe_delete(client, f"/accounts/{account_id}")


def test_settled_person_is_returned_not_hidden(client):
    """A person whose debt clears stays in the `people` panel with balance 0.

    The engine refuses to filter on a computed balance — folding settled people
    is a *client* display choice, and this test is what guarantees the client
    still receives the rows it folds. If the engine ever started hiding them,
    `▸ 3 settled` would quietly become `▸ 0 settled` and nobody would notice.
    """
    person_id = str(uuid4())
    name = f"contract-settled-{person_id[:8]}"
    category_id = str(uuid4())
    lend_id = str(uuid4())
    repay_id = str(uuid4())

    client.post(
        "/people",
        json_body={"id": person_id, "name": name, "currency_code": "PEN"},
    )
    client.post(
        "/categories",
        json_body={"id": category_id, "name": f"contract-cat-{person_id[:8]}", "color": "#123456"},
    )
    try:
        # Lend 200: an ordinary transaction against her. Her balance IS the debt.
        client.post(
            "/transactions",
            json_body={
                "id": lend_id,
                "title": "lent",
                "amount_cents": 20000,
                "date": "2026-08-01T12:00:00Z",
                "account_id": person_id,
                "category_id": category_id,
            },
        )
        owed = client.get(f"/accounts/{person_id}")
        assert owed["current_balance_cents"] == 20000

        # She pays it back. Zero is a balance, not a missing value.
        client.post(
            "/transactions",
            json_body={
                "id": repay_id,
                "title": "repaid",
                "amount_cents": -20000,
                "date": "2026-08-02T12:00:00Z",
                "account_id": person_id,
                "category_id": category_id,
            },
        )
        settled = client.get(f"/accounts/{person_id}")
        assert settled["current_balance_cents"] == 0

        panel = client.get("/dashboard").get("people") or []
        row = next((p for p in panel if p.get("id") == person_id), None)
        assert row is not None, "a settled person must still be returned, not filtered out"
        assert row["current_balance_cents"] == 0
    finally:
        _safe_delete(client, f"/transactions/{lend_id}")
        _safe_delete(client, f"/transactions/{repay_id}")
        _safe_delete(client, f"/accounts/{person_id}")
        _safe_delete(client, f"/categories/{category_id}")
