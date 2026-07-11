import json

import httpx
import respx
from typer.testing import CliRunner

from expense.commands.rates_cmd import app as rates_app
from tests.unit.helpers import make_cli_app

cli_app = make_cli_app(rates_app, "rates")

runner = CliRunner()


RATE_RESPONSE = {
    "base": "USD",
    "target": "EUR",
    "date": "2026-05-03",
    "rate": "0.9234",
}


@respx.mock
def test_get_happy_default_base_and_date(configured):
    route = respx.get("https://api.example.com/v1/exchange-rates").mock(
        return_value=httpx.Response(200, json=RATE_RESPONSE)
    )
    result = runner.invoke(cli_app, ["rates", "get", "--target", "EUR"])
    assert result.exit_code == 0, result.output
    assert "EUR" in result.output
    assert "0.9234" in result.output

    request = route.calls.last.request
    assert request.url.params.get("target") == "EUR"
    # base and date omitted client-side so engine defaults apply
    assert request.url.params.get("base") is None
    assert request.url.params.get("date") is None


@respx.mock
def test_get_explicit_base_and_date(configured):
    route = respx.get("https://api.example.com/v1/exchange-rates").mock(
        return_value=httpx.Response(
            200,
            json={**RATE_RESPONSE, "base": "GBP", "date": "2026-04-01"},
        )
    )
    result = runner.invoke(
        cli_app,
        [
            "rates",
            "get",
            "--target",
            "EUR",
            "--base",
            "GBP",
            "--date",
            "2026-04-01",
        ],
    )
    assert result.exit_code == 0, result.output

    request = route.calls.last.request
    assert request.url.params.get("target") == "EUR"
    assert request.url.params.get("base") == "GBP"
    assert request.url.params.get("date") == "2026-04-01"


@respx.mock
def test_get_json_mode_passthrough(configured):
    respx.get("https://api.example.com/v1/exchange-rates").mock(
        return_value=httpx.Response(200, json=RATE_RESPONSE)
    )
    result = runner.invoke(cli_app, ["rates", "get", "--target", "EUR", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == RATE_RESPONSE


@respx.mock
def test_get_rate_unavailable_surfaces_engine_error(configured):
    """Per memory project_engine_fx_cron_unwired: cross-currency rates 422 today."""
    respx.get("https://api.example.com/v1/exchange-rates").mock(
        return_value=httpx.Response(
            422,
            json={
                "error": {
                    "code": "RATE_UNAVAILABLE",
                    "message": "No rate on or before 2026-05-03 for USD->EUR.",
                    "fields": {
                        "exchange_rate": (
                            "No rate on or before 2026-05-03 for USD->EUR. "
                            "Wait for the daily fetch or supply an explicit "
                            "exchange_rate."
                        )
                    },
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["rates", "get", "--target", "EUR"])
    assert result.exit_code == 1
    assert "RATE_UNAVAILABLE" in result.output
    assert "exchange_rate" in result.output


def test_get_target_required(configured):
    """Without --target, Typer should bail before any HTTP call."""
    result = runner.invoke(cli_app, ["rates", "get"])
    assert result.exit_code != 0
    assert "target" in result.output.lower()


HISTORY_RESPONSE = {
    "items": [
        {"base": "USD", "target": "PEN", "rate_date": "2026-07-05", "rate": 3.6},
        {"base": "EUR", "target": "PEN", "rate_date": "2026-07-05", "rate": 4.6},
        {"base": "USD", "target": "PEN", "rate_date": "2026-07-04", "rate": 3.59},
    ],
    "total": 3,
    "limit": 50,
    "offset": 0,
}


@respx.mock
def test_list_renders_table_newest_first(configured):
    route = respx.get("https://api.example.com/v1/exchange-rates/history").mock(
        return_value=httpx.Response(200, json=HISTORY_RESPONSE)
    )
    result = runner.invoke(cli_app, ["rates", "list"])
    assert result.exit_code == 0, result.output
    assert "3.6000" in result.output and "4.6000" in result.output  # 4-decimal display
    assert "showing 3 of 3" in result.output
    # bare human list → the 20-row default limit (2026-07-11); nothing else sent
    request = route.calls.last.request
    assert request.url.params.get("date") is None
    assert request.url.params.get("limit") == "20"
    assert request.url.params.get("offset") is None


@respx.mock
def test_list_passes_date_and_pagination(configured):
    route = respx.get("https://api.example.com/v1/exchange-rates/history").mock(
        return_value=httpx.Response(200, json={**HISTORY_RESPONSE, "items": [], "total": 0})
    )
    result = runner.invoke(
        cli_app, ["rates", "list", "--date", "2026-07-04", "--limit", "10", "--offset", "5"]
    )
    assert result.exit_code == 0, result.output
    assert "No rates stored for 2026-07-04." in result.output
    request = route.calls.last.request
    assert request.url.params.get("date") == "2026-07-04"
    assert request.url.params.get("limit") == "10"
    assert request.url.params.get("offset") == "5"


@respx.mock
def test_list_json_mode_passthrough(configured):
    respx.get("https://api.example.com/v1/exchange-rates/history").mock(
        return_value=httpx.Response(200, json=HISTORY_RESPONSE)
    )
    result = runner.invoke(cli_app, ["rates", "list", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == HISTORY_RESPONSE
