import json
from datetime import datetime
from uuid import UUID

import httpx
import respx
from typer.testing import CliRunner

from expense.commands import log_cmd
from expense.commands.log_cmd import log as log_impl
from tests.unit.helpers import make_cli_app

cli_app = make_cli_app(commands={"log": log_impl})

runner = CliRunner()


TRANSACTION_RESPONSE = {
    "id": "55555555-5555-5555-5555-555555555555",
    "user_id": "u_123",
    "title": "coffee",
    "amount_cents": 500,
    "date": "2026-04-24T12:00:00Z",
    "account_id": "acct-id",
    "category_id": "cat-id",
    "description": None,
    "transaction_type": 1,
    "hashtag_ids": [],
    "inbox_id": None,
    "reconciliation_id": None,
    "created_at": "2026-04-24T10:00:00Z",
    "updated_at": "2026-04-24T10:00:00Z",
    "version": 1,
    "deleted_at": None,
}


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
def test_log_default_date_is_today(configured, monkeypatch):
    # Freeze the CLI's clock so the sent date and the compared date are the same
    # instant — recomputing "today" at assert time could straddle midnight and
    # flake (backlog §5). Patch the seam the default flows through (log_cmd.py:88).
    frozen = "2026-04-24T09:30:00-05:00"
    monkeypatch.setattr(log_cmd, "now_local_iso", lambda: frozen)
    route = respx.post("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(201, json=TRANSACTION_RESPONSE)
    )
    result = runner.invoke(
        cli_app,
        ["log", "--title", "coffee", "--amount", "-500", "--account-id", "a", "--category-id", "c"],
    )
    assert result.exit_code == 0, result.output

    body = json.loads(route.calls.last.request.content)
    assert body["date"] == frozen  # the default is now_local_iso(), used verbatim
    parsed = datetime.fromisoformat(body["date"])
    assert parsed.tzinfo is not None


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
