import json
from uuid import UUID

import httpx
import respx
from typer.testing import CliRunner

from expense.commands.transactions_cmd import app as transactions_app
from tests.unit.helpers import make_cli_app

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


# The three reference lists the human list renderer joins against for names.
ACCOUNT_ROW = {"id": "acct-id", "name": "BCP Soles"}
CATEGORY_ROW = {"id": "cat-id", "name": "Food"}
HASHTAG_ROW = {"id": "h-1", "name": "lunch"}


def _reference_envelope(rows: list[dict]) -> dict:
    return {"items": rows, "total": len(rows), "limit": 200, "offset": 0}


def _mock_name_maps() -> tuple:
    """Route the three reference lists so the renderer resolves real names.

    Without these routes the helpers swallow the unmatched request and return
    `{}`, and every reference cell degrades to an 8-char short id.
    """
    return (
        respx.get("https://api.example.com/v1/accounts").mock(
            return_value=httpx.Response(200, json=_reference_envelope([ACCOUNT_ROW]))
        ),
        respx.get("https://api.example.com/v1/categories").mock(
            return_value=httpx.Response(200, json=_reference_envelope([CATEGORY_ROW]))
        ),
        respx.get("https://api.example.com/v1/hashtags").mock(
            return_value=httpx.Response(200, json=_reference_envelope([HASHTAG_ROW]))
        ),
    )


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@respx.mock
def test_list_happy(configured):
    route = respx.get("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["transactions", "list"])
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
def test_list_resolves_names_from_live_reference_lists(configured):
    """The renderer joins account/category/hashtag ids against live lists."""
    item = {**TRANSACTION_RESPONSE, "hashtag_ids": ["h-1"]}
    respx.get("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(
            200, json={"items": [item], "total": 1, "limit": 50, "offset": 0}
        )
    )
    reference_routes = _mock_name_maps()
    result = runner.invoke(cli_app, ["transactions", "list"])
    assert result.exit_code == 0, result.output
    assert all(route.called for route in reference_routes)
    assert "BCP Soles" in result.output
    assert "Food" in result.output
    assert "lunch" in result.output


@respx.mock
def test_list_unresolvable_names_degrade_to_short_ids(configured):
    """A reference list the engine won't serve must not break the table."""
    item = {
        **TRANSACTION_RESPONSE,
        "account_id": "de37af15-0000-0000-0000-000000000000",
        "category_id": "ab99cc11-0000-0000-0000-000000000000",
        "hashtag_ids": [],
    }
    respx.get("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(
            200, json={"items": [item], "total": 1, "limit": 50, "offset": 0}
        )
    )
    result = runner.invoke(cli_app, ["transactions", "list"])
    assert result.exit_code == 0, result.output
    assert "de37af15" in result.output
    assert "ab99cc11" in result.output


@respx.mock
def test_list_all_filters_pass_through(configured):
    route = respx.get("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(
        cli_app,
        [
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
    result = runner.invoke(cli_app, ["transactions", "list", "--no-cleared"])
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
    result = runner.invoke(cli_app, ["transactions", "list", "--limit", "2"])
    assert result.exit_code == 0, result.output
    assert "showing 2 of 17" in result.output
    assert "--offset 2 --limit 2" in result.output


@respx.mock
def test_list_json_pass_through(configured):
    route = respx.get("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["transactions", "list", "--json"])
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
    result = runner.invoke(cli_app, ["transactions", "get", "abc"])
    assert result.exit_code == 0, result.output
    assert "coffee" in result.output
    # The single-record dump formats *_cents fields as major units.
    assert "amount_cents: 5.00" in result.output


@respx.mock
def test_get_always_sends_debit_as_negative(configured):
    route = respx.get("https://api.example.com/v1/transactions/abc").mock(
        return_value=httpx.Response(200, json=TRANSACTION_RESPONSE)
    )
    result = runner.invoke(cli_app, ["transactions", "get", "abc"])
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
    result = runner.invoke(cli_app, ["transactions", "get", "missing"])
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
