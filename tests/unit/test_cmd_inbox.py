import json
from uuid import UUID, uuid4

import httpx
import pytest
import respx
import typer
from typer.testing import CliRunner

from expense import config as config_module
from expense.commands.inbox_cmd import app as inbox_app

cli_app = typer.Typer()


@cli_app.callback()
def _root() -> None:
    pass


cli_app.add_typer(inbox_app, name="inbox")

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
def configured(tmp_path, monkeypatch):
    config_path = tmp_path / ".expense-config"
    monkeypatch.setenv("EXPENSE_CONFIG", str(config_path))
    config_module.save(
        config_module.Config(
            engine_url="https://api.example.com",
            token="ewe_pat_test",
            client_id=uuid4(),
        )
    )
    yield


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
    route = respx.get("https://api.example.com/v1/inbox").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["inbox", "list", "--include-deleted"])
    assert result.exit_code == 0, result.output

    request = route.calls.last.request
    assert request.url.params.get("include_deleted") == "true"


@respx.mock
def test_get_happy(configured):
    respx.get("https://api.example.com/v1/inbox/abc").mock(
        return_value=httpx.Response(200, json=INBOX_RESPONSE)
    )
    result = runner.invoke(cli_app, ["inbox", "get", "abc"])
    assert result.exit_code == 0, result.output
    assert "lunch" in result.output


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
