import json
import re
from uuid import uuid4

import httpx
import pytest
import respx
import typer
from typer.testing import CliRunner

from expense import config as config_module
from expense.commands.sync_cmd import sync

cli_app = typer.Typer()


@cli_app.callback()
def _root() -> None:
    pass


cli_app.command("sync")(sync)

runner = CliRunner()


SYNC_RESPONSE = {
    "sync_token": "11111111-1111-1111-1111-111111111111",
    "accounts": [
        {"id": "a1", "name": "BCP Soles"},
        {"id": "a2", "name": "Cash"},
    ],
    "categories": [
        {"id": "c1", "name": "Food"},
        {"id": "c2", "name": "Transport"},
        {"id": "c3", "name": "Rent"},
    ],
    "hashtags": [{"id": "h1", "name": "#vacation"}],
    "inbox": [],
    "transactions": [
        {"id": "t1", "amount_cents": -1200},
        {"id": "t2", "amount_cents": -500},
        {"id": "t3", "amount_cents": 800000},
        {"id": "t4", "amount_cents": -250},
    ],
    "reconciliations": [{"id": "r1"}],
    "settings": {"main_currency": "USD"},
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
def test_sync_full_calls_engine_with_correct_params(configured):
    route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_RESPONSE)
    )
    result = runner.invoke(cli_app, ["sync", "--full"])
    assert result.exit_code == 0, result.stderr

    assert route.called
    request = route.calls.last.request
    assert request.url.params.get("sync_token") == "*"
    assert request.url.params.get("debit_as_negative") == "true"
    assert request.headers.get("X-Client-Id")


@respx.mock
def test_sync_bare_errors_without_calling_engine(configured):
    route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_RESPONSE)
    )
    result = runner.invoke(cli_app, ["sync"])
    assert result.exit_code == 2
    assert not route.called
    assert "--full" in result.stderr
    assert "delta-sync" in result.stderr or "replica" in result.stderr


@respx.mock
def test_sync_full_human_output(configured):
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_RESPONSE)
    )
    result = runner.invoke(cli_app, ["sync", "--full"])
    assert result.exit_code == 0, result.stderr

    out = result.stdout
    assert "Sync (full snapshot)" in out
    assert re.search(r"^\s+accounts\s+2$", out, re.MULTILINE)
    assert re.search(r"^\s+categories\s+3$", out, re.MULTILINE)
    assert re.search(r"^\s+hashtags\s+1$", out, re.MULTILINE)
    assert re.search(r"^\s+inbox\s+0$", out, re.MULTILINE)
    assert re.search(r"^\s+transactions\s+4$", out, re.MULTILINE)
    assert re.search(r"^\s+reconciliations\s+1$", out, re.MULTILINE)
    assert re.search(r"^\s+settings\s+present$", out, re.MULTILINE)
    assert "sync_token: 11111111-1111-1111-1111-111111111111" in out

    pulled_at_match = re.search(r"pulled_at:\s+(\S+)", out)
    assert pulled_at_match is not None
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", pulled_at_match.group(1))


@respx.mock
def test_sync_full_json_passthrough(configured):
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_RESPONSE)
    )
    result = runner.invoke(cli_app, ["sync", "--full", "--json"])
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == SYNC_RESPONSE
    assert "pulled_at" not in result.stdout
    assert "Sync (full snapshot)" not in result.stdout


@respx.mock
def test_sync_settings_null_renders_as_null(configured):
    payload = {**SYNC_RESPONSE, "settings": None}
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = runner.invoke(cli_app, ["sync", "--full"])
    assert result.exit_code == 0, result.stderr
    assert re.search(r"^\s+settings\s+\(null\)$", result.stdout, re.MULTILINE)


@respx.mock
def test_sync_empty_resources_render_zero(configured):
    payload = {
        "sync_token": "22222222-2222-2222-2222-222222222222",
        "accounts": [],
        "categories": [],
        "hashtags": [],
        "inbox": [],
        "transactions": [],
        "reconciliations": [],
        "settings": None,
    }
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = runner.invoke(cli_app, ["sync", "--full"])
    assert result.exit_code == 0, result.stderr
    out = result.stdout
    assert re.search(r"^\s+accounts\s+0$", out, re.MULTILINE)
    assert re.search(r"^\s+transactions\s+0$", out, re.MULTILINE)
    assert re.search(r"^\s+reconciliations\s+0$", out, re.MULTILINE)


@respx.mock
def test_sync_401_surfaces_engine_error(configured):
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(
            401,
            json={"error": {"code": "UNAUTHORIZED", "message": "bad token", "fields": None}},
        )
    )
    result = runner.invoke(cli_app, ["sync", "--full"])
    assert result.exit_code == 1
    assert "UNAUTHORIZED" in result.stderr
    assert "expense config set --token" in result.stderr


@respx.mock
def test_sync_422_surfaces_engine_error(configured):
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(
            422,
            json={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid sync token.",
                    "fields": {"sync_token": "Unknown token; retry with sync_token=*."},
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["sync", "--full"])
    assert result.exit_code == 1
    assert "VALIDATION_ERROR" in result.stderr


@respx.mock
def test_sync_connection_error_surfaces_cleanly(configured):
    respx.get("https://api.example.com/v1/sync").mock(side_effect=httpx.ConnectError("refused"))
    result = runner.invoke(cli_app, ["sync", "--full"])
    assert result.exit_code == 2
    assert "could not reach engine" in result.stderr
