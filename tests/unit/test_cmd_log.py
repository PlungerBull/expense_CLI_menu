import json
from datetime import datetime
from uuid import UUID, uuid4

import httpx
import pytest
import respx
import typer
from typer.testing import CliRunner

from expense import config as config_module
from expense.commands.log_cmd import log as log_impl

cli_app = typer.Typer()


@cli_app.callback()
def _root() -> None:
    pass


cli_app.command("log")(log_impl)

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
def test_log_happy(configured):
    route = respx.post("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(201, json=TRANSACTION_RESPONSE)
    )
    result = runner.invoke(
        cli_app,
        [
            "log",
            "--title",
            "coffee",
            "--amount",
            "-500",
            "--account-id",
            "acct-id",
            "--category-id",
            "cat-id",
            "--date",
            "2026-04-24T12:00:00Z",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Created:" in result.output

    body = json.loads(route.calls.last.request.content)
    assert body["title"] == "coffee"
    assert body["amount_cents"] == -500
    assert body["account_id"] == "acct-id"
    assert body["category_id"] == "cat-id"
    assert body["date"] == "2026-04-24T12:00:00Z"
    UUID(body["id"])


@respx.mock
def test_log_json_mode(configured):
    respx.post("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(201, json=TRANSACTION_RESPONSE)
    )
    result = runner.invoke(
        cli_app,
        [
            "log",
            "--title",
            "coffee",
            "--amount",
            "-500",
            "--account-id",
            "a",
            "--category-id",
            "c",
            "--json",
        ],
    )
    assert result.exit_code == 0
    assert json.loads(result.output) == TRANSACTION_RESPONSE
    assert "Created:" not in result.output


@respx.mock
def test_log_default_date_is_today(configured):
    route = respx.post("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(201, json=TRANSACTION_RESPONSE)
    )
    result = runner.invoke(
        cli_app,
        ["log", "--title", "coffee", "--amount", "-500", "--account-id", "a", "--category-id", "c"],
    )
    assert result.exit_code == 0, result.output

    body = json.loads(route.calls.last.request.content)
    parsed = datetime.fromisoformat(body["date"])
    assert parsed.tzinfo is not None
    assert parsed.date() == datetime.now().astimezone().date()


@respx.mock
def test_log_signed_negative_amount(configured):
    route = respx.post("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(201, json=TRANSACTION_RESPONSE)
    )
    runner.invoke(
        cli_app,
        ["log", "--title", "x", "--amount", "-2000", "--account-id", "a", "--category-id", "c"],
    )
    body = json.loads(route.calls.last.request.content)
    assert body["amount_cents"] == -2000


@respx.mock
def test_log_signed_positive_amount(configured):
    route = respx.post("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(201, json=TRANSACTION_RESPONSE)
    )
    runner.invoke(
        cli_app,
        ["log", "--title", "x", "--amount", "5000", "--account-id", "a", "--category-id", "c"],
    )
    body = json.loads(route.calls.last.request.content)
    assert body["amount_cents"] == 5000


@respx.mock
def test_log_422_rate_unavailable_prints_hint(configured):
    respx.post("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(
            422,
            json={
                "error": {
                    "code": "RATE_UNAVAILABLE",
                    "message": "No FX rate available.",
                    "fields": {"exchange_rate": "No rate on or before 2026-04-24 for USD->PEN."},
                }
            },
        )
    )
    result = runner.invoke(
        cli_app,
        ["log", "--title", "x", "--amount", "-100", "--account-id", "a", "--category-id", "c"],
    )
    assert result.exit_code == 1
    assert "--exchange-rate" in result.output
    assert "RATE_UNAVAILABLE" in result.output


@respx.mock
def test_log_422_settings_missing_prints_hint(configured):
    respx.post("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(
            422,
            json={
                "error": {
                    "code": "SETTINGS_MISSING",
                    "message": "User settings missing.",
                    "fields": {"user_settings": "Must be provisioned via bootstrap."},
                }
            },
        )
    )
    result = runner.invoke(
        cli_app,
        ["log", "--title", "x", "--amount", "-100", "--account-id", "a", "--category-id", "c"],
    )
    assert result.exit_code == 1
    assert "expense auth bootstrap" in result.output
    assert "SETTINGS_MISSING" in result.output
