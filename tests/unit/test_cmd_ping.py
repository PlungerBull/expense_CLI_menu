import json
from uuid import uuid4

import httpx
import pytest
import respx
import typer
from typer.testing import CliRunner

from expense import config as config_module
from expense.commands.ping_cmd import ping

cli_app = typer.Typer()


@cli_app.callback()
def _root() -> None:
    pass


cli_app.command("ping")(ping)

runner = CliRunner()


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
def test_ping_success_human_mode(configured):
    respx.get("https://api.example.com/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    result = runner.invoke(cli_app, ["ping"])
    assert result.exit_code == 0
    assert "ok" in result.output


@respx.mock
def test_ping_success_json_mode(configured):
    respx.get("https://api.example.com/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    result = runner.invoke(cli_app, ["ping", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data == {"status": "ok"}


@respx.mock
def test_ping_connection_error(configured):
    respx.get("https://api.example.com/health").mock(side_effect=httpx.ConnectError("refused"))
    result = runner.invoke(cli_app, ["ping"])
    assert result.exit_code == 2
    assert "could not reach engine" in result.output


@respx.mock
def test_ping_500_engine_error(configured):
    respx.get("https://api.example.com/health").mock(
        return_value=httpx.Response(
            500,
            json={"error": {"code": "INTERNAL", "message": "boom", "fields": None}},
        )
    )
    result = runner.invoke(cli_app, ["ping"])
    assert result.exit_code == 1
    assert "INTERNAL" in result.output


@respx.mock
def test_ping_timeout(configured):
    respx.get("https://api.example.com/health").mock(side_effect=httpx.ReadTimeout("timeout"))
    result = runner.invoke(cli_app, ["ping"])
    assert result.exit_code == 2
    assert "could not reach engine" in result.output


def test_ping_without_config_errors_cleanly(tmp_path, monkeypatch):
    config_path = tmp_path / ".expense-config"
    monkeypatch.setenv("EXPENSE_CONFIG", str(config_path))
    result = runner.invoke(cli_app, ["ping"])
    assert result.exit_code == 3
    assert "config set" in result.output
