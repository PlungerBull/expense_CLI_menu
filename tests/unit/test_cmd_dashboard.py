import json
from uuid import uuid4

import httpx
import pytest
import respx
import typer
from typer.testing import CliRunner

from expense import config as config_module
from expense.commands.dashboard_cmd import dashboard

cli_app = typer.Typer()


@cli_app.callback()
def _root() -> None:
    pass


cli_app.command("dashboard")(dashboard)

runner = CliRunner()


DASHBOARD_RESPONSE = {
    "month": {"year": 2026, "month": 4},
    "bank_accounts": [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "name": "BCP Soles",
            "currency_code": "PEN",
            "current_balance_cents": 125000,
            "current_balance_home_cents": 125000,
        }
    ],
    "people": [
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "name": "Alex",
            "currency_code": "PEN",
            "current_balance_cents": -4500,
            "current_balance_home_cents": -4500,
        }
    ],
    "categories": [
        {
            "id": "33333333-3333-3333-3333-333333333333",
            "name": "Food",
            "spent_cents": -50000,
            "spent_home_cents": -50000,
            "hashtag_breakdown": [
                {
                    "hashtag_ids": ["aaaa", "bbbb"],
                    "spent_cents": -30000,
                    "spent_home_cents": -30000,
                },
                {
                    "hashtag_ids": [],
                    "spent_cents": -20000,
                    "spent_home_cents": -20000,
                },
            ],
        }
    ],
    "totals": {
        "inflow_cents": 800000,
        "inflow_home_cents": 800000,
        "outflow_cents": 320000,
        "outflow_home_cents": 320000,
        "net_cents": 480000,
        "net_home_cents": 480000,
    },
    "archived_accounts": None,
    "archived_categories": None,
    "archived_hashtags": None,
}

DASHBOARD_WITH_ARCHIVED = {
    **DASHBOARD_RESPONSE,
    "archived_accounts": [
        {
            "id": "44444444-4444-4444-4444-444444444444",
            "name": "Old BCP",
            "currency_code": "PEN",
            "current_balance_cents": 0,
            "current_balance_home_cents": 0,
        }
    ],
    "archived_categories": [
        {
            "id": "55555555-5555-5555-5555-555555555555",
            "name": "Crypto",
            "lifetime_spent_cents": -250000,
            "lifetime_spent_home_cents": -250000,
        }
    ],
    "archived_hashtags": [
        {
            "id": "66666666-6666-6666-6666-666666666666",
            "name": "#vacation-2024",
            "lifetime_spent_cents": -480000,
            "lifetime_spent_home_cents": -480000,
        }
    ],
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
def test_dashboard_happy(configured):
    route = respx.get("https://api.example.com/v1/dashboard").mock(
        return_value=httpx.Response(200, json=DASHBOARD_RESPONSE)
    )
    result = runner.invoke(cli_app, ["dashboard"])
    assert result.exit_code == 0, result.output
    assert "Month: 2026-04" in result.output
    assert "BCP Soles (PEN)" in result.output
    assert "Alex (PEN)" in result.output
    assert "Food" in result.output
    assert "[aaaa, bbbb]: -30000" in result.output
    assert "(no hashtags): -20000" in result.output
    assert "inflow: 800000" in result.output

    request = route.calls.last.request
    assert "include_archived" not in request.url.params


@respx.mock
def test_dashboard_include_archived(configured):
    route = respx.get("https://api.example.com/v1/dashboard").mock(
        return_value=httpx.Response(200, json=DASHBOARD_WITH_ARCHIVED)
    )
    result = runner.invoke(cli_app, ["dashboard", "--include-archived"])
    assert result.exit_code == 0, result.output
    assert "Archived accounts:" in result.output
    assert "Old BCP" in result.output
    assert "Archived categories:" in result.output
    assert "Crypto" in result.output
    assert "lifetime spent: -250000" in result.output
    assert "Archived hashtags:" in result.output
    assert "#vacation-2024" in result.output

    request = route.calls.last.request
    assert request.url.params.get("include_archived") == "true"


@respx.mock
def test_dashboard_json_passthrough(configured):
    respx.get("https://api.example.com/v1/dashboard").mock(
        return_value=httpx.Response(200, json=DASHBOARD_RESPONSE)
    )
    result = runner.invoke(cli_app, ["dashboard", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == DASHBOARD_RESPONSE


@respx.mock
def test_dashboard_settings_missing_422(configured):
    respx.get("https://api.example.com/v1/dashboard").mock(
        return_value=httpx.Response(
            422,
            json={
                "error": {
                    "code": "SETTINGS_MISSING",
                    "message": "User settings have not been provisioned.",
                    "fields": {"user_settings": "Must be provisioned via POST /v1/auth/bootstrap."},
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["dashboard"])
    assert result.exit_code == 1
    assert "SETTINGS_MISSING" in result.output


@respx.mock
def test_dashboard_handles_empty_collections(configured):
    payload = {
        "month": {"year": 2026, "month": 4},
        "bank_accounts": [],
        "people": [],
        "categories": [],
        "totals": {
            "inflow_cents": 0,
            "inflow_home_cents": 0,
            "outflow_cents": 0,
            "outflow_home_cents": 0,
            "net_cents": 0,
            "net_home_cents": 0,
        },
        "archived_accounts": None,
        "archived_categories": None,
        "archived_hashtags": None,
    }
    respx.get("https://api.example.com/v1/dashboard").mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = runner.invoke(cli_app, ["dashboard"])
    assert result.exit_code == 0, result.output
    assert "Bank accounts:" in result.output
    assert "(no bank accounts)" in result.output
    assert "(no categories)" in result.output
    assert "People:" not in result.output


@respx.mock
def test_dashboard_404_surfaces_engine_error(configured):
    respx.get("https://api.example.com/v1/dashboard").mock(
        return_value=httpx.Response(
            404,
            json={"error": {"code": "NOT_FOUND", "message": "Not found", "fields": None}},
        )
    )
    result = runner.invoke(cli_app, ["dashboard"])
    assert result.exit_code == 1
    assert "NOT_FOUND" in result.output


@respx.mock
def test_dashboard_500_surfaces_engine_error(configured):
    respx.get("https://api.example.com/v1/dashboard").mock(
        return_value=httpx.Response(
            500,
            json={"error": {"code": "INTERNAL", "message": "boom", "fields": None}},
        )
    )
    result = runner.invoke(cli_app, ["dashboard"])
    assert result.exit_code == 1
    assert "INTERNAL" in result.output


@respx.mock
def test_dashboard_connection_error(configured):
    respx.get("https://api.example.com/v1/dashboard").mock(
        side_effect=httpx.ConnectError("refused")
    )
    result = runner.invoke(cli_app, ["dashboard"])
    assert result.exit_code == 2
    assert "could not reach engine" in result.output


@respx.mock
def test_dashboard_401_surfaces_config_set_hint(configured):
    respx.get("https://api.example.com/v1/dashboard").mock(
        return_value=httpx.Response(
            401,
            json={"error": {"code": "UNAUTHORIZED", "message": "bad token", "fields": None}},
        )
    )
    result = runner.invoke(cli_app, ["dashboard"])
    assert result.exit_code == 1
    assert "UNAUTHORIZED" in result.output
    assert "expense config set --token" in result.output
