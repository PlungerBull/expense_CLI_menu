import json
from uuid import UUID

import httpx
import pytest
import respx
from typer.testing import CliRunner

from expense import config as config_module
from expense.cache import db as cache_db
from expense.cache import state as cache_state
from expense.commands.inbox_cmd import app as inbox_app
from tests.unit.helpers import (
    insert_account,
    insert_category,
    insert_inbox,
    make_cli_app,
    sync_payload,
)

cli_app = make_cli_app(inbox_app, "inbox")

runner = CliRunner()


INBOX_RESPONSE = {
    "id": "44444444-4444-4444-4444-444444444444",
    "user_id": "u_123",
    "status": 1,
    "title": "lunch",
    "amount_cents": 2500,
    "amount_home_cents": 2500,
    "date": "2026-04-24T12:00:00Z",
    "account_id": None,
    "category_id": None,
    "description": None,
    "cleared": False,
    "exchange_rate": 1.0,
    "transaction_type": 1,
    "transfer_account_id": None,
    "transfer_amount_cents": None,
    "transfer_amount_home_cents": None,
    "created_at": "2026-04-24T10:00:00Z",
    "updated_at": "2026-04-24T10:00:00Z",
    "deleted_at": None,
    "version": 1,
}

LIST_RESPONSE = {
    "items": [INBOX_RESPONSE],
    "total": 1,
    "limit": 50,
    "offset": 0,
}


@pytest.fixture
def cache_populated(configured):
    cfg = config_module.ensure_loaded()
    conn = cache_db.connect()
    try:
        insert_account(
            conn,
            {"id": "acct-1", "user_id": "u1", "name": "Active", "sort_order": 1, "version": 1},
        )
        insert_account(
            conn,
            {
                "id": "acct-archived",
                "user_id": "u1",
                "name": "Old",
                "is_archived": True,
                "sort_order": 2,
                "version": 1,
            },
        )
        insert_category(
            conn,
            {"id": "cat-1", "user_id": "u1", "name": "Food", "sort_order": 1, "version": 1},
        )

        ready_row = {
            **INBOX_RESPONSE,
            "id": "ib-ready",
            "title": "lunch",
            "amount_cents": 2500,
            "date": "2026-04-25",
            "account_id": "acct-1",
            "category_id": "cat-1",
            "user_id": "u1",
        }
        insert_inbox(conn, ready_row)

        not_ready_no_account = {
            **INBOX_RESPONSE,
            "id": "ib-no-account",
            "title": "untitled draft",
            "amount_cents": 1000,
            "date": "2026-04-25",
            "account_id": None,
            "category_id": "cat-1",
            "user_id": "u1",
        }
        insert_inbox(conn, not_ready_no_account)

        not_ready_archived_account = {
            **INBOX_RESPONSE,
            "id": "ib-archived-acct",
            "title": "stale",
            "amount_cents": 500,
            "date": "2026-04-25",
            "account_id": "acct-archived",
            "category_id": "cat-1",
            "user_id": "u1",
        }
        insert_inbox(conn, not_ready_archived_account)

        future_row = {
            **INBOX_RESPONSE,
            "id": "ib-future",
            "title": "future",
            "amount_cents": 100,
            "date": "2099-12-31",
            "account_id": "acct-1",
            "category_id": "cat-1",
            "user_id": "u1",
        }
        insert_inbox(conn, future_row)

        overdue_row = {
            **INBOX_RESPONSE,
            "id": "ib-overdue",
            "title": "old draft",
            "amount_cents": 800,
            "date": "2020-01-01",
            "account_id": "acct-1",
            "category_id": "cat-1",
            "user_id": "u1",
        }
        insert_inbox(conn, overdue_row)

        cache_state.write_identity(
            conn,
            user_id="u1",
            client_id=str(cfg.client_id),
            engine_url=cfg.engine_url,
            token_fingerprint=cache_state.token_fingerprint(cfg.token),
        )
        cache_state.write_token(conn, "tok-populated")
    finally:
        conn.close()
    yield


@respx.mock
def test_list_happy(configured):
    route = respx.get("https://api.example.com/v1/inbox").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["--no-cache", "inbox", "list", "--ready"])
    assert result.exit_code == 0, result.output
    assert "lunch" in result.output

    request = route.calls.last.request
    assert request.url.params.get("ready") == "true"
    assert request.url.params.get("debit_as_negative") == "true"


@respx.mock
def test_list_json_mode(configured):
    respx.get("https://api.example.com/v1/inbox").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["--no-cache", "inbox", "list", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == LIST_RESPONSE


@respx.mock
def test_list_include_deleted_param(configured):
    route = respx.get("https://api.example.com/v1/inbox").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["--no-cache", "inbox", "list", "--include-deleted"])
    assert result.exit_code == 0, result.output

    request = route.calls.last.request
    assert request.url.params.get("include_deleted") == "true"


@respx.mock
def test_get_happy(configured):
    route = respx.get("https://api.example.com/v1/inbox/abc").mock(
        return_value=httpx.Response(200, json=INBOX_RESPONSE)
    )
    result = runner.invoke(cli_app, ["--no-cache", "inbox", "get", "abc"])
    assert result.exit_code == 0, result.output
    assert "lunch" in result.output
    assert route.calls.last.request.url.params.get("debit_as_negative") == "true"


@respx.mock
def test_get_404(configured):
    respx.get("https://api.example.com/v1/inbox/missing").mock(
        return_value=httpx.Response(
            404,
            json={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Inbox item not found",
                    "fields": None,
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["--no-cache", "inbox", "get", "missing"])
    assert result.exit_code == 1
    assert "NOT_FOUND" in result.output


@respx.mock
def test_add_happy(configured):
    route = respx.post("https://api.example.com/v1/inbox").mock(
        return_value=httpx.Response(201, json=INBOX_RESPONSE)
    )
    result = runner.invoke(
        cli_app,
        ["inbox", "add", "--title", "lunch", "--amount", "-2500"],
    )
    assert result.exit_code == 0, result.output
    assert "Created:" in result.output

    body = json.loads(route.calls.last.request.content)
    assert body["title"] == "lunch"
    assert body["amount_cents"] == -2500
    UUID(body["id"])


@respx.mock
def test_add_json_mode(configured):
    respx.post("https://api.example.com/v1/inbox").mock(
        return_value=httpx.Response(201, json=INBOX_RESPONSE)
    )
    result = runner.invoke(
        cli_app,
        ["inbox", "add", "--title", "lunch", "--amount", "-2500", "--json"],
    )
    assert result.exit_code == 0
    assert json.loads(result.output) == INBOX_RESPONSE
    assert "Created:" not in result.output


def test_update_no_flags_errors(configured):
    result = runner.invoke(cli_app, ["inbox", "update", "abc"])
    assert result.exit_code == 1
    assert "No fields to update" in result.output


@respx.mock
def test_update_partial_payload(configured):
    route = respx.put("https://api.example.com/v1/inbox/abc").mock(
        return_value=httpx.Response(200, json=INBOX_RESPONSE)
    )
    result = runner.invoke(cli_app, ["inbox", "update", "abc", "--title", "renamed"])
    assert result.exit_code == 0, result.output

    body = json.loads(route.calls.last.request.content)
    assert body == {"title": "renamed"}


def test_delete_requires_yes_in_non_tty(configured):
    result = runner.invoke(cli_app, ["inbox", "delete", "abc"])
    assert result.exit_code == 1
    assert "non-interactive" in result.output


@respx.mock
def test_delete_happy(configured):
    deleted = {**INBOX_RESPONSE, "deleted_at": "2026-04-24T10:00:00Z"}
    respx.delete("https://api.example.com/v1/inbox/abc").mock(
        return_value=httpx.Response(200, json=deleted)
    )
    result = runner.invoke(cli_app, ["inbox", "delete", "abc", "--yes"])
    assert result.exit_code == 0, result.output


@respx.mock
def test_restore_happy(configured):
    respx.post("https://api.example.com/v1/inbox/abc/restore").mock(
        return_value=httpx.Response(200, json=INBOX_RESPONSE)
    )
    result = runner.invoke(cli_app, ["inbox", "restore", "abc"])
    assert result.exit_code == 0, result.output


@respx.mock
def test_restore_409_prints_promoted_hint(configured):
    respx.post("https://api.example.com/v1/inbox/abc/restore").mock(
        return_value=httpx.Response(
            409,
            json={
                "error": {
                    "code": "CONFLICT",
                    "message": "Inbox item already promoted.",
                    "fields": None,
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["inbox", "restore", "abc"])
    assert result.exit_code == 1
    assert "promoted" in result.output
    assert "CONFLICT" in result.output


@respx.mock
def test_promote_happy(configured):
    transaction_response = {
        "id": "tx-id",
        "title": "lunch",
        "amount_cents": 2500,
        "transaction_type": 1,
        "inbox_id": "44444444-4444-4444-4444-444444444444",
    }
    route = respx.post(
        "https://api.example.com/v1/inbox/44444444-4444-4444-4444-444444444444/promote"
    ).mock(return_value=httpx.Response(201, json=transaction_response))
    result = runner.invoke(cli_app, ["inbox", "promote", "44444444-4444-4444-4444-444444444444"])
    assert result.exit_code == 0, result.output
    assert "Created transaction:" in result.output

    body = json.loads(route.calls.last.request.content)
    UUID(body["id"])


@respx.mock
def test_promote_422_prints_fix_hint(configured):
    respx.post("https://api.example.com/v1/inbox/abc/promote").mock(
        return_value=httpx.Response(
            422,
            json={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Inbox item not ready to promote.",
                    "fields": {
                        "title": "Must not be empty.",
                        "account_id": "Must reference an active account.",
                    },
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["inbox", "promote", "abc"])
    assert result.exit_code == 1
    assert "expense inbox update" in result.output
    assert "VALIDATION_ERROR" in result.output
    assert "title" in result.output
    assert "account_id" in result.output


@respx.mock
def test_list_include_deleted_reads_live_without_no_cache(cache_populated):
    """--include-deleted rows exist only engine-side — cache mode must route live (backlog 1.4)."""
    deleted = {
        **INBOX_RESPONSE,
        "id": "99999999-9999-9999-9999-999999999999",
        "title": "deleted draft",
        "deleted_at": "2026-06-01T09:00:00Z",
    }
    body = {"items": [INBOX_RESPONSE, deleted], "total": 2, "limit": 50, "offset": 0}
    route = respx.get("https://api.example.com/v1/inbox").mock(
        return_value=httpx.Response(200, json=body)
    )
    result = runner.invoke(cli_app, ["inbox", "list", "--include-deleted", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == body
    assert route.calls.last.request.url.params.get("include_deleted") == "true"


def test_list_replica_path(cache_populated):
    with respx.mock(base_url="https://api.example.com", assert_all_called=False) as router:
        inbox_route = router.get("/v1/inbox")
        result = runner.invoke(cli_app, ["inbox", "list"])
    assert result.exit_code == 0, result.output
    assert "lunch" in result.output
    assert not inbox_route.called


def test_list_replica_ready_filter(cache_populated):
    """--ready replicates engine predicate: title set + non-UNTITLED, amount nonzero,
    date <= today, account+category present and active."""
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(cli_app, ["inbox", "list", "--ready", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    ids = [r["id"] for r in payload["items"]]
    assert "ib-ready" in ids
    assert "ib-overdue" in ids  # also satisfies the predicate (date in past, all fields)
    assert "ib-no-account" not in ids
    assert "ib-archived-acct" not in ids
    assert "ib-future" not in ids


def test_list_replica_overdue_filter(cache_populated):
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(cli_app, ["inbox", "list", "--overdue", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    ids = [r["id"] for r in payload["items"]]
    assert "ib-overdue" in ids
    assert "ib-future" not in ids


def test_get_replica_path(cache_populated):
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(cli_app, ["inbox", "get", "ib-ready"])
    assert result.exit_code == 0, result.output
    assert "lunch" in result.output


def test_get_replica_not_found(cache_populated):
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(cli_app, ["inbox", "get", "missing"])
    assert result.exit_code == 1
    assert "NOT_FOUND" in result.output


@respx.mock
def test_list_auto_cold_start_when_cache_empty(configured):
    sync_route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=sync_payload(inbox=[INBOX_RESPONSE]))
    )
    inbox_route = respx.get("https://api.example.com/v1/inbox")
    result = runner.invoke(cli_app, ["inbox", "list"])
    assert result.exit_code == 0, result.output
    assert sync_route.called
    assert not inbox_route.called


@respx.mock
def test_add_triggers_post_write_sync(cache_populated):
    """Step 7b.3: a successful inbox write fires a follow-up GET /sync."""
    respx.post("https://api.example.com/v1/inbox").mock(
        return_value=httpx.Response(201, json=INBOX_RESPONSE)
    )
    sync_route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=sync_payload(inbox=[INBOX_RESPONSE]))
    )
    result = runner.invoke(
        cli_app,
        ["inbox", "add", "--title", "lunch", "--amount", "-1500"],
    )
    assert result.exit_code == 0, result.output
    assert sync_route.called
