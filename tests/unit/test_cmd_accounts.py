import json
from uuid import UUID, uuid4

import httpx
import pytest
import respx
import typer
from typer.testing import CliRunner

from expense import config as config_module
from expense.commands.accounts_cmd import app as accounts_app

cli_app = typer.Typer()


@cli_app.callback()
def _root() -> None:
    pass


cli_app.add_typer(accounts_app, name="accounts")

runner = CliRunner()


ACCOUNT_RESPONSE = {
    "id": "11111111-1111-1111-1111-111111111111",
    "name": "BCP Soles",
    "currency_code": "PEN",
    "color": "#FF0000",
    "sort_order": 1,
    "is_person": False,
    "is_archived": False,
    "deleted_at": None,
    "version": 1,
    "created_at": "2026-04-24T10:00:00Z",
    "updated_at": "2026-04-24T10:00:00Z",
    "current_balance_cents": 125000,
    "current_balance_home_cents": 125000,
}

LIST_RESPONSE = [ACCOUNT_RESPONSE]


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
    route = respx.get("https://api.example.com/v1/accounts").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["accounts", "list", "--include-archived"])
    assert result.exit_code == 0, result.output
    assert "BCP Soles" in result.output

    request = route.calls.last.request
    assert request.url.params.get("include_archived") == "true"


@respx.mock
def test_list_json_mode(configured):
    respx.get("https://api.example.com/v1/accounts").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["accounts", "list", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == LIST_RESPONSE


@respx.mock
def test_get_happy(configured):
    respx.get("https://api.example.com/v1/accounts/abc").mock(
        return_value=httpx.Response(200, json=ACCOUNT_RESPONSE)
    )
    result = runner.invoke(cli_app, ["accounts", "get", "abc"])
    assert result.exit_code == 0, result.output
    assert "BCP Soles" in result.output


@respx.mock
def test_get_404(configured):
    respx.get("https://api.example.com/v1/accounts/missing").mock(
        return_value=httpx.Response(
            404,
            json={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Account not found",
                    "fields": None,
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["accounts", "get", "missing"])
    assert result.exit_code == 1
    assert "NOT_FOUND" in result.output


@respx.mock
def test_create_happy(configured):
    route = respx.post("https://api.example.com/v1/accounts").mock(
        return_value=httpx.Response(201, json=ACCOUNT_RESPONSE)
    )
    result = runner.invoke(
        cli_app,
        ["accounts", "create", "--name", "BCP Soles", "--currency-code", "PEN"],
    )
    assert result.exit_code == 0, result.output
    assert "Created:" in result.output

    body = json.loads(route.calls.last.request.content)
    assert body["name"] == "BCP Soles"
    assert body["currency_code"] == "PEN"
    UUID(body["id"])


@respx.mock
def test_create_json_mode(configured):
    respx.post("https://api.example.com/v1/accounts").mock(
        return_value=httpx.Response(201, json=ACCOUNT_RESPONSE)
    )
    result = runner.invoke(
        cli_app,
        [
            "accounts",
            "create",
            "--name",
            "BCP Soles",
            "--currency-code",
            "PEN",
            "--json",
        ],
    )
    assert result.exit_code == 0
    assert json.loads(result.output) == ACCOUNT_RESPONSE
    assert "Created:" not in result.output


def test_update_no_flags_errors(configured):
    result = runner.invoke(cli_app, ["accounts", "update", "abc"])
    assert result.exit_code == 1
    assert "No fields to update" in result.output


@respx.mock
def test_update_partial_payload(configured):
    route = respx.put("https://api.example.com/v1/accounts/abc").mock(
        return_value=httpx.Response(200, json=ACCOUNT_RESPONSE)
    )
    result = runner.invoke(cli_app, ["accounts", "update", "abc", "--name", "Renamed"])
    assert result.exit_code == 0, result.output

    body = json.loads(route.calls.last.request.content)
    assert body == {"name": "Renamed"}


def test_update_currency_flag_rejected_locally(configured):
    result = runner.invoke(
        cli_app,
        ["accounts", "update", "abc", "--currency-code", "USD"],
    )
    assert result.exit_code != 0
    assert "Currency cannot be changed" in result.output


def test_delete_requires_yes_in_non_tty(configured):
    result = runner.invoke(cli_app, ["accounts", "delete", "abc"])
    assert result.exit_code == 1
    assert "non-interactive" in result.output


@respx.mock
def test_delete_happy(configured):
    deleted = {**ACCOUNT_RESPONSE, "deleted_at": "2026-04-24T10:00:00Z"}
    respx.delete("https://api.example.com/v1/accounts/abc").mock(
        return_value=httpx.Response(200, json=deleted)
    )
    result = runner.invoke(cli_app, ["accounts", "delete", "abc", "--yes"])
    assert result.exit_code == 0, result.output


@respx.mock
def test_delete_409_prints_archive_hint(configured):
    respx.delete("https://api.example.com/v1/accounts/abc").mock(
        return_value=httpx.Response(
            409,
            json={
                "error": {
                    "code": "CONFLICT",
                    "message": "Account has transactions.",
                    "fields": None,
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["accounts", "delete", "abc", "--yes"])
    assert result.exit_code == 1
    assert "archive" in result.output
    assert "CONFLICT" in result.output


@respx.mock
def test_archive_happy(configured):
    archived = {**ACCOUNT_RESPONSE, "is_archived": True}
    respx.post("https://api.example.com/v1/accounts/abc/archive").mock(
        return_value=httpx.Response(200, json=archived)
    )
    result = runner.invoke(cli_app, ["accounts", "archive", "abc"])
    assert result.exit_code == 0, result.output
    assert "is_archived: True" in result.output


@respx.mock
def test_unarchive_happy(configured):
    respx.post("https://api.example.com/v1/accounts/abc/unarchive").mock(
        return_value=httpx.Response(200, json=ACCOUNT_RESPONSE)
    )
    result = runner.invoke(cli_app, ["accounts", "unarchive", "abc"])
    assert result.exit_code == 0, result.output


@respx.mock
def test_restore_happy(configured):
    respx.post("https://api.example.com/v1/accounts/abc/restore").mock(
        return_value=httpx.Response(200, json=ACCOUNT_RESPONSE)
    )
    result = runner.invoke(cli_app, ["accounts", "restore", "abc"])
    assert result.exit_code == 0, result.output
