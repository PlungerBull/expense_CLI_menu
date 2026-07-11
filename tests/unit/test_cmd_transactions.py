import json
from uuid import UUID

import httpx
import pytest
import respx
from typer.testing import CliRunner

from expense import config as config_module
from expense.cache import db as cache_db
from expense.cache import state as cache_state
from expense.commands.transactions_cmd import app as transactions_app
from tests.unit.helpers import insert_transaction, make_cli_app, sync_payload

cli_app = make_cli_app(transactions_app, "transactions")

runner = CliRunner()


TRANSACTION_RESPONSE = {
    "id": "55555555-5555-5555-5555-555555555555",
    "user_id": "u_123",
    "title": "coffee",
    "amount_cents": 500,
    "amount_home_cents": 500,
    "date": "2026-04-24T12:00:00Z",
    "account_id": "acct-id",
    "category_id": "cat-id",
    "description": None,
    "cleared": False,
    "exchange_rate": 1.0,
    "transaction_type": 1,
    "transfer_transaction_id": None,
    "hashtag_ids": [],
    "inbox_id": None,
    "reconciliation_id": None,
    "created_at": "2026-04-24T10:00:00Z",
    "updated_at": "2026-04-24T10:00:00Z",
    "version": 1,
    "deleted_at": None,
    "warnings": [],
}

LIST_RESPONSE = {
    "items": [TRANSACTION_RESPONSE],
    "total": 1,
    "limit": 50,
    "offset": 0,
}


@pytest.fixture
def cache_populated(configured):
    cfg = config_module.ensure_loaded()
    conn = cache_db.connect()
    try:
        rows = [
            {
                **TRANSACTION_RESPONSE,
                "id": "tx-coffee",
                "title": "Coffee shop",
                "description": "downtown",
                "user_id": "u1",
                "date": "2026-04-25",
                "account_id": "acct-1",
                "hashtag_ids": ["h1"],
                "cleared": True,
            },
            {
                **TRANSACTION_RESPONSE,
                "id": "tx-lunch",
                "title": "Lunch",
                "description": "with COWORKER",
                "user_id": "u1",
                "date": "2026-04-24",
                "account_id": "acct-1",
                "hashtag_ids": ["h2"],
                "cleared": False,
            },
            {
                **TRANSACTION_RESPONSE,
                "id": "tx-cab",
                "title": "Cab",
                "description": None,
                "user_id": "u1",
                "date": "2026-04-23",
                "account_id": "acct-2",
                "hashtag_ids": [],
                "cleared": False,
            },
        ]
        for row in rows:
            insert_transaction(conn, row)
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


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@respx.mock
def test_list_happy(configured):
    route = respx.get("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["--no-cache", "transactions", "list"])
    assert result.exit_code == 0, result.output
    assert "coffee" in result.output
    # Amount renders as grouped major units, not raw cents.
    assert "5.00" in result.output
    assert "500" not in result.output
    # Signed output is not opt-in; human mode adds the 20-row default (2026-07-11).
    assert dict(route.calls.last.request.url.params) == {
        "debit_as_negative": "true",
        "limit": "20",
    }


@respx.mock
def test_list_all_filters_pass_through(configured):
    route = respx.get("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(
        cli_app,
        [
            "--no-cache",
            "transactions",
            "list",
            "--account-id",
            "a-1",
            "--category-id",
            "c-1",
            "--hashtag-id",
            "h-1",
            "--reconciliation-id",
            "r-1",
            "--from",
            "2026-04-01",
            "--to",
            "2026-04-30",
            "--cleared",
            "--search",
            "coffee",
            "--limit",
            "25",
            "--offset",
            "10",
            "--include-deleted",
        ],
    )
    assert result.exit_code == 0, result.output

    params = dict(route.calls.last.request.url.params)
    assert params == {
        "account_id": "a-1",
        "category_id": "c-1",
        "hashtag_id": "h-1",
        "reconciliation_id": "r-1",
        "date_from": "2026-04-01",
        "date_to": "2026-04-30",
        "cleared": "true",
        "search": "coffee",
        "limit": "25",
        "offset": "10",
        "include_deleted": "true",
        "debit_as_negative": "true",
    }


@respx.mock
def test_list_no_cleared_sends_false(configured):
    route = respx.get("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["--no-cache", "transactions", "list", "--no-cleared"])
    assert result.exit_code == 0, result.output
    assert route.calls.last.request.url.params.get("cleared") == "false"


@respx.mock
def test_list_pagination_hint_when_truncated(configured):
    paged = {
        "items": [TRANSACTION_RESPONSE, TRANSACTION_RESPONSE],
        "total": 17,
        "limit": 2,
        "offset": 0,
    }
    respx.get("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(200, json=paged)
    )
    result = runner.invoke(cli_app, ["--no-cache", "transactions", "list", "--limit", "2"])
    assert result.exit_code == 0, result.output
    assert "showing 2 of 17" in result.output
    assert "--offset 2 --limit 2" in result.output


@respx.mock
def test_list_json_pass_through(configured):
    route = respx.get("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["--no-cache", "transactions", "list", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == LIST_RESPONSE
    # --json keeps the raw request: no human-mode default limit (2026-07-11)
    assert route.calls.last.request.url.params.get("limit") is None


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


@respx.mock
def test_get_happy(configured):
    respx.get("https://api.example.com/v1/transactions/abc").mock(
        return_value=httpx.Response(200, json=TRANSACTION_RESPONSE)
    )
    result = runner.invoke(cli_app, ["--no-cache", "transactions", "get", "abc"])
    assert result.exit_code == 0, result.output
    assert "coffee" in result.output
    # The single-record dump formats *_cents fields as major units.
    assert "amount_cents: 5.00" in result.output


@respx.mock
def test_get_always_sends_debit_as_negative(configured):
    route = respx.get("https://api.example.com/v1/transactions/abc").mock(
        return_value=httpx.Response(200, json=TRANSACTION_RESPONSE)
    )
    result = runner.invoke(cli_app, ["--no-cache", "transactions", "get", "abc"])
    assert result.exit_code == 0, result.output
    assert route.calls.last.request.url.params.get("debit_as_negative") == "true"


@respx.mock
def test_get_404(configured):
    respx.get("https://api.example.com/v1/transactions/missing").mock(
        return_value=httpx.Response(
            404,
            json={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Transaction not found",
                    "fields": None,
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["--no-cache", "transactions", "get", "missing"])
    assert result.exit_code == 1
    assert "NOT_FOUND" in result.output


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


def test_update_no_flags_errors(configured):
    result = runner.invoke(cli_app, ["transactions", "update", "abc"])
    assert result.exit_code == 1
    assert "No fields to update" in result.output


@respx.mock
def test_update_partial_payload(configured):
    route = respx.put("https://api.example.com/v1/transactions/abc").mock(
        return_value=httpx.Response(200, json=TRANSACTION_RESPONSE)
    )
    result = runner.invoke(
        cli_app,
        ["transactions", "update", "abc", "--title", "renamed", "--cleared"],
    )
    assert result.exit_code == 0, result.output

    body = json.loads(route.calls.last.request.content)
    assert body == {"title": "renamed", "cleared": True}


@respx.mock
def test_update_hashtag_ids_parsed_to_list(configured):
    route = respx.put("https://api.example.com/v1/transactions/abc").mock(
        return_value=httpx.Response(200, json=TRANSACTION_RESPONSE)
    )
    result = runner.invoke(
        cli_app,
        ["transactions", "update", "abc", "--hashtag-ids", "h-1, h-2,h-3"],
    )
    assert result.exit_code == 0, result.output
    body = json.loads(route.calls.last.request.content)
    assert body == {"hashtag_ids": ["h-1", "h-2", "h-3"]}


@respx.mock
def test_update_422_reconciliation_lock_hint(configured):
    respx.put("https://api.example.com/v1/transactions/abc").mock(
        return_value=httpx.Response(
            422,
            json={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Field is read-only on a completed reconciliation.",
                    "fields": {"amount_cents": "Locked by completed reconciliation."},
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["transactions", "update", "abc", "--amount", "-100"])
    assert result.exit_code == 1
    assert "reconcile revert" in result.output
    assert "VALIDATION_ERROR" in result.output


@respx.mock
def test_update_422_transfer_guard_hint(configured):
    respx.put("https://api.example.com/v1/transactions/abc").mock(
        return_value=httpx.Response(
            422,
            json={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Field is read-only on a transfer pair leg.",
                    "fields": {"amount_cents": "Read-only on transfer leg."},
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["transactions", "update", "abc", "--amount", "-100"])
    assert result.exit_code == 1
    assert "delete and recreate" in result.output


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def test_delete_requires_yes_in_non_tty(configured):
    result = runner.invoke(cli_app, ["transactions", "delete", "abc"])
    assert result.exit_code == 1
    assert "non-interactive" in result.output


@respx.mock
def test_delete_happy_renders_warnings(configured):
    deleted = {
        **TRANSACTION_RESPONSE,
        "deleted_at": "2026-04-24T10:00:00Z",
        "warnings": ["Transaction belonged to a completed reconciliation. Totals may be stale."],
    }
    respx.delete("https://api.example.com/v1/transactions/abc").mock(
        return_value=httpx.Response(200, json=deleted)
    )
    result = runner.invoke(cli_app, ["transactions", "delete", "abc", "--yes"])
    assert result.exit_code == 0, result.output
    assert "Warning: Transaction belonged" in result.output


@respx.mock
def test_delete_json_passes_through(configured):
    deleted = {**TRANSACTION_RESPONSE, "deleted_at": "2026-04-24T10:00:00Z"}
    respx.delete("https://api.example.com/v1/transactions/abc").mock(
        return_value=httpx.Response(200, json=deleted)
    )
    result = runner.invoke(cli_app, ["transactions", "delete", "abc", "--yes", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == deleted


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------


@respx.mock
def test_restore_happy(configured):
    respx.post("https://api.example.com/v1/transactions/abc/restore").mock(
        return_value=httpx.Response(200, json=TRANSACTION_RESPONSE)
    )
    result = runner.invoke(cli_app, ["transactions", "restore", "abc"])
    assert result.exit_code == 0, result.output


@respx.mock
def test_restore_warnings_rendered(configured):
    restored = {
        **TRANSACTION_RESPONSE,
        "warnings": ["Transaction unlinked from completed reconciliation."],
    }
    respx.post("https://api.example.com/v1/transactions/abc/restore").mock(
        return_value=httpx.Response(200, json=restored)
    )
    result = runner.invoke(cli_app, ["transactions", "restore", "abc"])
    assert result.exit_code == 0, result.output
    assert "Warning: Transaction unlinked" in result.output


@respx.mock
def test_restore_422_archived_hint(configured):
    respx.post("https://api.example.com/v1/transactions/abc/restore").mock(
        return_value=httpx.Response(
            422,
            json={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Referenced rows are no longer active.",
                    "fields": {"category_id": "Must reference an active, non-archived category."},
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["transactions", "restore", "abc"])
    assert result.exit_code == 1
    assert "Unarchive or restore" in result.output


@respx.mock
def test_restore_409_asymmetric_pair_hint(configured):
    respx.post("https://api.example.com/v1/transactions/abc/restore").mock(
        return_value=httpx.Response(
            409,
            json={
                "error": {
                    "code": "CONFLICT",
                    "message": "Transfer sibling missing.",
                    "fields": None,
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["transactions", "restore", "abc"])
    assert result.exit_code == 1
    assert "transfer pair" in result.output


# ---------------------------------------------------------------------------
# batch
# ---------------------------------------------------------------------------


@respx.mock
def test_batch_happy_from_stdin(configured):
    items_in = [
        {
            "title": "a",
            "amount_cents": -100,
            "date": "2026-04-24T12:00:00Z",
            "account_id": "acct-1",
            "category_id": "cat-1",
        },
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "title": "b",
            "amount_cents": -200,
            "date": "2026-04-24T12:00:00Z",
            "account_id": "acct-1",
            "category_id": "cat-1",
        },
    ]
    response = {"created": [TRANSACTION_RESPONSE, TRANSACTION_RESPONSE]}
    route = respx.post("https://api.example.com/v1/transactions/batch").mock(
        return_value=httpx.Response(201, json=response)
    )
    result = runner.invoke(cli_app, ["transactions", "batch"], input=json.dumps(items_in))
    assert result.exit_code == 0, result.output

    sent = json.loads(route.calls.last.request.content)
    assert "transactions" in sent
    assert len(sent["transactions"]) == 2
    UUID(sent["transactions"][0]["id"])
    assert sent["transactions"][1]["id"] == "11111111-1111-1111-1111-111111111111"
    assert "Created:" in result.output
    assert "Created 2 transactions." in result.output
    # The envelope must never leak as a Python repr in human mode.
    assert "created: [" not in result.output


@respx.mock
def test_batch_singular_count(configured):
    items_in = [
        {
            "title": "a",
            "amount_cents": -100,
            "date": "2026-04-24T12:00:00Z",
            "account_id": "acct-1",
            "category_id": "cat-1",
        }
    ]
    respx.post("https://api.example.com/v1/transactions/batch").mock(
        return_value=httpx.Response(201, json={"created": [TRANSACTION_RESPONSE]})
    )
    result = runner.invoke(cli_app, ["transactions", "batch"], input=json.dumps(items_in))
    assert result.exit_code == 0, result.output
    assert "Created 1 transaction." in result.output


@respx.mock
def test_batch_json_passthrough(configured):
    items_in = [
        {
            "title": "a",
            "amount_cents": -100,
            "date": "2026-04-24T12:00:00Z",
            "account_id": "acct-1",
            "category_id": "cat-1",
        }
    ]
    response = {"created": [TRANSACTION_RESPONSE]}
    respx.post("https://api.example.com/v1/transactions/batch").mock(
        return_value=httpx.Response(201, json=response)
    )
    result = runner.invoke(cli_app, ["transactions", "batch", "--json"], input=json.dumps(items_in))
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == response


_BATCH_TRANSFER_ITEMS = [
    {
        "title": "a",
        "amount_cents": -100,
        "date": "2026-04-24T12:00:00Z",
        "account_id": "acct-1",
        "category_id": "cat-1",
        "transfer": {
            "id": "x",
            "account_id": "acct-2",
            "amount_cents": 50,
        },
    }
]

# Verified engine envelope for a transfer item in a batch
# (engine app/helpers/transactions.py — fields key is transactions[i].transfer).
_BATCH_TRANSFER_422 = {
    "error": {
        "code": "VALIDATION_ERROR",
        "message": "Transfers are not supported in batch creates.",
        "fields": {"transactions[0].transfer": "Must not be present in batch."},
    }
}


@respx.mock
def test_batch_transfer_422_surfaces_with_hint(configured):
    route = respx.post("https://api.example.com/v1/transactions/batch").mock(
        return_value=httpx.Response(422, json=_BATCH_TRANSFER_422)
    )
    result = runner.invoke(
        cli_app, ["transactions", "batch"], input=json.dumps(_BATCH_TRANSFER_ITEMS)
    )
    assert result.exit_code == 1
    # thin wrapper: the request reaches the engine — no client pre-emption
    assert route.called
    assert "VALIDATION_ERROR" in result.output
    assert "Transfers are not supported in batch creates." in result.output
    assert "transactions[0].transfer" in result.output
    assert "Hint: transfers are not supported in batch creates" in result.output


@respx.mock
def test_batch_transfer_422_json_mode_passes_envelope_verbatim(configured):
    respx.post("https://api.example.com/v1/transactions/batch").mock(
        return_value=httpx.Response(422, json=_BATCH_TRANSFER_422)
    )
    result = runner.invoke(
        cli_app, ["transactions", "batch", "--json"], input=json.dumps(_BATCH_TRANSFER_ITEMS)
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout) == _BATCH_TRANSFER_422
    assert "Hint:" in result.stderr


@respx.mock
def test_batch_other_422_prints_no_transfer_hint(configured):
    envelope = {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Duplicate id within batch.",
            "fields": {"transactions[1].id": "Duplicate id within batch."},
        }
    }
    respx.post("https://api.example.com/v1/transactions/batch").mock(
        return_value=httpx.Response(422, json=envelope)
    )
    items = [
        {
            "title": "a",
            "amount_cents": -100,
            "date": "2026-04-24T12:00:00Z",
            "account_id": "acct-1",
            "category_id": "cat-1",
        }
    ]
    result = runner.invoke(cli_app, ["transactions", "batch"], input=json.dumps(items))
    assert result.exit_code == 1
    assert "Duplicate id within batch." in result.output
    assert "Hint:" not in result.output


def test_batch_invalid_json_errors(configured):
    result = runner.invoke(cli_app, ["transactions", "batch"], input="not json")
    assert result.exit_code == 1
    assert "Invalid JSON" in result.output


def test_batch_empty_array_errors(configured):
    result = runner.invoke(cli_app, ["transactions", "batch"], input="[]")
    assert result.exit_code == 1
    assert "non-empty JSON array" in result.output


# ---------------------------------------------------------------------------
# Replica-path tests (Step 7b.2.3)
# ---------------------------------------------------------------------------


@respx.mock
def test_list_include_deleted_reads_live_without_no_cache(cache_populated):
    """--include-deleted rows exist only engine-side — cache mode must route live (backlog 1.4)."""
    deleted = {
        **TRANSACTION_RESPONSE,
        "id": "99999999-9999-9999-9999-999999999999",
        "title": "refunded dinner",
        "deleted_at": "2026-06-01T09:00:00Z",
    }
    body = {"items": [TRANSACTION_RESPONSE, deleted], "total": 2, "limit": 50, "offset": 0}
    route = respx.get("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(200, json=body)
    )
    result = runner.invoke(cli_app, ["transactions", "list", "--include-deleted"])
    assert result.exit_code == 0, result.output
    assert "refunded dinner" in result.output
    assert route.calls.last.request.url.params.get("include_deleted") == "true"


def test_list_replica_path(cache_populated):
    with respx.mock(base_url="https://api.example.com", assert_all_called=False) as router:
        tx_route = router.get("/v1/transactions")
        result = runner.invoke(cli_app, ["transactions", "list"])
    assert result.exit_code == 0, result.output
    assert "Coffee shop" in result.output
    assert "Lunch" in result.output
    assert "Cab" in result.output
    assert not tx_route.called


def test_list_replica_account_filter(cache_populated):
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(
            cli_app, ["transactions", "list", "--account-id", "acct-1", "--json"]
        )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    ids = [r["id"] for r in payload["items"]]
    assert sorted(ids) == ["tx-coffee", "tx-lunch"]


def test_list_replica_hashtag_filter(cache_populated):
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(cli_app, ["transactions", "list", "--hashtag-id", "h1", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert [r["id"] for r in payload["items"]] == ["tx-coffee"]


def test_list_replica_search_case_insensitive(cache_populated):
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(cli_app, ["transactions", "list", "--search", "COWORKER", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert [r["id"] for r in payload["items"]] == ["tx-lunch"]


def test_list_replica_date_range(cache_populated):
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(
            cli_app,
            [
                "transactions",
                "list",
                "--from",
                "2026-04-24",
                "--to",
                "2026-04-25",
                "--json",
            ],
        )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    ids = [r["id"] for r in payload["items"]]
    assert sorted(ids) == ["tx-coffee", "tx-lunch"]


def test_list_replica_cleared_filter(cache_populated):
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(cli_app, ["transactions", "list", "--cleared", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert [r["id"] for r in payload["items"]] == ["tx-coffee"]


def test_list_replica_includes_hashtag_ids(cache_populated):
    """Engine A+ embeds hashtag_ids on every transaction-returning endpoint;
    cache mirrors that — list responses carry hashtag_ids."""
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(cli_app, ["transactions", "list", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    for item in payload["items"]:
        assert "hashtag_ids" in item
        assert isinstance(item["hashtag_ids"], list)


def test_get_replica_path(cache_populated):
    """Engine A+ embeds hashtag_ids on GET /v1/transactions/{id}; cache mirrors."""
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(cli_app, ["transactions", "get", "tx-coffee", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["id"] == "tx-coffee"
    assert "hashtag_ids" in payload
    assert isinstance(payload["hashtag_ids"], list)


def test_get_replica_not_found(cache_populated):
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(cli_app, ["transactions", "get", "nope"])
    assert result.exit_code == 1
    assert "NOT_FOUND" in result.output


@respx.mock
def test_list_auto_cold_start_when_cache_empty(configured):
    sync_route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(
            200, json=sync_payload(transactions=[{**TRANSACTION_RESPONSE, "user_id": "u1"}])
        )
    )
    tx_route = respx.get("https://api.example.com/v1/transactions")
    result = runner.invoke(cli_app, ["transactions", "list"])
    assert result.exit_code == 0, result.output
    assert sync_route.called
    assert not tx_route.called


@respx.mock
def test_update_triggers_post_write_sync(cache_populated):
    """Step 7b.3: a successful transactions write fires a follow-up GET /sync."""
    respx.put("https://api.example.com/v1/transactions/abc").mock(
        return_value=httpx.Response(200, json=TRANSACTION_RESPONSE)
    )
    sync_route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(
            200, json=sync_payload(transactions=[{**TRANSACTION_RESPONSE, "user_id": "u1"}])
        )
    )
    result = runner.invoke(cli_app, ["transactions", "update", "abc", "--title", "renamed"])
    assert result.exit_code == 0, result.output
    assert sync_route.called
