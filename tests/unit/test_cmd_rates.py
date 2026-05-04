import json
from uuid import uuid4

import httpx
import pytest
import respx
import typer
from typer.testing import CliRunner

from expense import config as config_module
from expense.commands.rates_cmd import app as rates_app
from expense.context import AppContext

cli_app = typer.Typer()


@cli_app.callback()
def _root(ctx: typer.Context) -> None:
    ctx.obj = AppContext()


cli_app.add_typer(rates_app, name="rates")

runner = CliRunner()


RATE_RESPONSE = {
    "base": "USD",
    "target": "EUR",
    "date": "2026-05-03",
    "rate": "0.9234",
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
