import json
from uuid import UUID

import httpx
import respx
from typer.testing import CliRunner

from expense.commands.inbox_cmd import app as inbox_app
from tests.unit.helpers import make_cli_app

cli_app = make_cli_app(inbox_app, "inbox")

runner = CliRunner()


INBOX_RESPONSE = {
    "id": "44444444-4444-4444-4444-444444444444",
    "user_id": "u_123",
    "status": 1,
    "title": "lunch",
    "amount_cents": 2500,
    "date": "2026-04-24T12:00:00Z",
    "account_id": None,
    "category_id": None,
    "description": None,
    # no `cleared` — InboxResponse has never carried it; a draft has not posted
    # anywhere yet. Removed 2026-08-16 (backlog 5.1).
    "transaction_type": 1,
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


@respx.mock
def test_list_happy(configured):
    route = respx.get("https://api.example.com/v1/inbox").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["inbox", "list", "--ready"])
    assert result.exit_code == 0, result.output
    assert "lunch" in result.output

    request = route.calls.last.request
    assert request.url.params.get("ready") == "true"
    assert request.url.params.get("debit_as_negative") == "true"


@respx.mock
def test_list_overdue_param(configured):
    route = respx.get("https://api.example.com/v1/inbox").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["inbox", "list", "--overdue"])
    assert result.exit_code == 0, result.output
    assert route.calls.last.request.url.params.get("overdue") == "true"


@respx.mock
def test_list_resolves_names_from_live_reference_lists(configured):
    """The renderer joins account/category ids against the live reference lists."""
    item = {**INBOX_RESPONSE, "account_id": "acct-id", "category_id": "cat-id"}
    respx.get("https://api.example.com/v1/inbox").mock(
        return_value=httpx.Response(
            200, json={"items": [item], "total": 1, "limit": 50, "offset": 0}
        )
    )
    accounts_route = respx.get("https://api.example.com/v1/accounts").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [{"id": "acct-id", "name": "BCP Soles"}],
                "total": 1,
                "limit": 200,
                "offset": 0,
            },
        )
    )
    categories_route = respx.get("https://api.example.com/v1/categories").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [{"id": "cat-id", "name": "Food"}],
                "total": 1,
                "limit": 200,
                "offset": 0,
            },
        )
    )
    result = runner.invoke(cli_app, ["inbox", "list"])
    assert result.exit_code == 0, result.output
    assert accounts_route.called and categories_route.called
    assert "BCP Soles" in result.output
    assert "Food" in result.output


@respx.mock
def test_list_unresolvable_names_degrade_to_short_ids(configured):
    """A reference list the engine won't serve must not break the table."""
    item = {
        **INBOX_RESPONSE,
        "account_id": "de37af15-0000-0000-0000-000000000000",
        "category_id": "ab99cc11-0000-0000-0000-000000000000",
    }
    respx.get("https://api.example.com/v1/inbox").mock(
        return_value=httpx.Response(
            200, json={"items": [item], "total": 1, "limit": 50, "offset": 0}
        )
    )
    result = runner.invoke(cli_app, ["inbox", "list"])
    assert result.exit_code == 0, result.output
    assert "de37af15" in result.output
    assert "ab99cc11" in result.output


@respx.mock
def test_list_json_mode(configured):
    respx.get("https://api.example.com/v1/inbox").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["inbox", "list", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == LIST_RESPONSE


@respx.mock
def test_list_include_deleted_param(configured):
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

    request = route.calls.last.request
    assert request.url.params.get("include_deleted") == "true"


@respx.mock
def test_get_happy(configured):
    route = respx.get("https://api.example.com/v1/inbox/abc").mock(
        return_value=httpx.Response(200, json=INBOX_RESPONSE)
    )
    result = runner.invoke(cli_app, ["inbox", "get", "abc"])
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
    result = runner.invoke(cli_app, ["inbox", "get", "missing"])
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


def test_add_and_update_reject_retired_cleared_flag(configured):
    """--cleared is gone from both inbox writes entirely.

    `expense_transaction_inbox` has no `cleared` column and never has, and the
    inbox write models are strict — so the field is rejected as an unknown input
    and the whole write is lost, not just the flag. Found against a real engine by
    the Phase 5 contract gate, 2026-08-16. Transactions keep the flag (it is a
    per-row boolean there, written only by the caller); see
    test_cmd_transactions.py.
    """
    for argv in (
        ["inbox", "add", "--title", "x", "--amount", "-100", "--cleared"],
        ["inbox", "update", "abc", "--cleared"],
    ):
        result = runner.invoke(cli_app, argv)
        assert result.exit_code == 2, f"{argv} should not parse"
        assert "No such option" in result.output
