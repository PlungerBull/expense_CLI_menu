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
from expense.context import AppContext

cli_app = typer.Typer()


@cli_app.callback()
def _root(
    ctx: typer.Context,
    no_cache: bool = typer.Option(False, "--no-cache", envvar="EXPENSE_STATELESS"),
) -> None:
    ctx.obj = AppContext(no_cache=no_cache)


cli_app.command("sync")(sync)

runner = CliRunner()


SYNC_RESPONSE = {
    "sync_token": "11111111-1111-1111-1111-111111111111",
    "accounts": [
        {
            "id": "a1",
            "user_id": "u1",
            "name": "BCP",
            "is_archived": False,
            "is_person": False,
            "deleted_at": None,
            "sort_order": 1,
            "version": 1,
        },
        {
            "id": "a2",
            "user_id": "u1",
            "name": "Cash",
            "is_archived": False,
            "is_person": False,
            "deleted_at": None,
            "sort_order": 2,
            "version": 1,
        },
    ],
    "categories": [
        {
            "id": "c1",
            "user_id": "u1",
            "name": "Food",
            "is_archived": False,
            "is_system": False,
            "deleted_at": None,
            "sort_order": 1,
            "version": 1,
        }
    ],
    "hashtags": [],
    "inbox": [],
    "transactions": [
        {
            "id": "t1",
            "user_id": "u1",
            "title": "Lunch",
            "amount_cents": -1200,
            "account_id": "a1",
            "category_id": "c1",
            "reconciliation_id": None,
            "parent_transaction_id": None,
            "transfer_transaction_id": None,
            "inbox_id": None,
            "date": "2026-04-25",
            "deleted_at": None,
            "version": 1,
            "updated_at": "2026-04-25T10:00:00Z",
            "hashtag_ids": [],
        }
    ],
    "reconciliations": [],
    "settings": {"user_id": "u1", "main_currency": "USD", "version": 1},
}


@pytest.fixture
def configured(tmp_path, monkeypatch):
    config_path = tmp_path / ".expense-config"
    cache_path = tmp_path / "cache.sqlite3"
    monkeypatch.setenv("EXPENSE_CONFIG", str(config_path))
    monkeypatch.setenv("EXPENSE_CACHE", str(cache_path))
    config_module.save(
        config_module.Config(
            engine_url="https://api.example.com",
            token="ewe_pat_test",
            client_id=uuid4(),
        )
    )
    yield


@respx.mock
def test_sync_full_cold_starts_cache(configured):
    route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_RESPONSE)
    )
    result = runner.invoke(cli_app, ["sync", "--full"])
    assert result.exit_code == 0, result.stderr
    assert route.called
    assert route.calls.last.request.url.params.get("sync_token") == "*"
    out = result.stdout
    assert "Sync (full snapshot)" in out
    assert re.search(r"^\s+accounts:\s+2$", out, re.MULTILINE)
    assert re.search(r"^\s+transactions:\s+1$", out, re.MULTILINE)
    assert re.search(r"^\s+settings:\s+present$", out, re.MULTILINE)
    assert "cache:" in out
    assert "sync_token: 11111111-1111-1111-1111-111111111111" in out


@respx.mock
def test_sync_bare_cold_starts_when_no_token(configured):
    route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_RESPONSE)
    )
    result = runner.invoke(cli_app, ["sync"])
    assert result.exit_code == 0, result.stderr
    assert route.called
    assert route.calls.last.request.url.params.get("sync_token") == "*"
    assert "Sync (full snapshot)" in result.stdout


@respx.mock
def test_sync_bare_does_delta_when_token_exists(configured):
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_RESPONSE)
    )
    runner.invoke(cli_app, ["sync"])

    delta_response = {
        "sync_token": "22222222-2222-2222-2222-222222222222",
        "accounts": [],
        "categories": [],
        "hashtags": [],
        "inbox": [],
        "transactions": [
            {
                "id": "t2",
                "user_id": "u1",
                "title": "Coffee",
                "amount_cents": -350,
                "account_id": "a1",
                "category_id": "c1",
                "reconciliation_id": None,
                "parent_transaction_id": None,
                "transfer_transaction_id": None,
                "inbox_id": None,
                "date": "2026-04-26",
                "deleted_at": None,
                "version": 1,
                "updated_at": "2026-04-26T08:00:00Z",
                "hashtag_ids": [],
            }
        ],
        "reconciliations": [],
        "settings": None,
    }
    route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=delta_response)
    )
    result = runner.invoke(cli_app, ["sync"])
    assert result.exit_code == 0, result.stderr
    assert (
        route.calls.last.request.url.params.get("sync_token")
        == "11111111-1111-1111-1111-111111111111"
    )
    out = result.stdout
    assert "Sync (delta)" in out
    assert "applied:" in out
    assert re.search(r"transactions:\s+\+1\s+~0\s+-0", out)
    assert re.search(r"settings:\s+unchanged", out)
    assert "sync_token: 22222222-2222-2222-2222-222222222222" in out


@respx.mock
def test_sync_no_cache_is_stateless(configured, tmp_path):
    route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_RESPONSE)
    )
    result = runner.invoke(cli_app, ["--no-cache", "sync"])
    assert result.exit_code == 0, result.stderr
    assert route.called
    assert route.calls.last.request.url.params.get("sync_token") == "*"
    out = result.stdout
    assert "Sync (full snapshot)" in out
    assert "cache:" not in out
    cache_file = tmp_path / "cache.sqlite3"
    assert not cache_file.exists()


@respx.mock
def test_sync_env_stateless_is_stateless(configured, tmp_path, monkeypatch):
    monkeypatch.setenv("EXPENSE_STATELESS", "1")
    route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_RESPONSE)
    )
    result = runner.invoke(cli_app, ["sync"])
    assert result.exit_code == 0, result.stderr
    assert route.called
    assert "cache:" not in result.stdout
    cache_file = tmp_path / "cache.sqlite3"
    assert not cache_file.exists()


@respx.mock
def test_sync_no_cache_with_full_is_stateless(configured, tmp_path):
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_RESPONSE)
    )
    result = runner.invoke(cli_app, ["--no-cache", "sync", "--full"])
    assert result.exit_code == 0, result.stderr
    assert "cache:" not in result.stdout
    cache_file = tmp_path / "cache.sqlite3"
    assert not cache_file.exists()


@respx.mock
def test_sync_falls_back_to_cold_start_on_unknown_token(configured):
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_RESPONSE)
    )
    runner.invoke(cli_app, ["sync"])

    error_body = {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "sync_token is unknown for this client.",
            "fields": {"sync_token": "Unknown token; retry with sync_token=*."},
        }
    }
    sequence = [
        httpx.Response(422, json=error_body),
        httpx.Response(200, json={**SYNC_RESPONSE, "sync_token": "rebuilt"}),
    ]
    respx.get("https://api.example.com/v1/sync").mock(side_effect=sequence)

    result = runner.invoke(cli_app, ["sync"])
    assert result.exit_code == 0, result.stderr
    assert "Sync (full snapshot)" in result.stdout
    assert "sync_token: rebuilt" in result.stdout


@respx.mock
def test_sync_full_json_passthrough(configured):
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_RESPONSE)
    )
    result = runner.invoke(cli_app, ["sync", "--full", "--json"])
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == SYNC_RESPONSE
    assert "Sync (full snapshot)" not in result.stdout
    assert "cache:" not in result.stdout


@respx.mock
def test_sync_no_cache_json_passthrough(configured):
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=SYNC_RESPONSE)
    )
    result = runner.invoke(cli_app, ["--no-cache", "sync", "--json"])
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == SYNC_RESPONSE


@respx.mock
def test_sync_401_surfaces_engine_error(configured):
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(
            401,
            json={"error": {"code": "UNAUTHORIZED", "message": "bad token", "fields": None}},
        )
    )
    result = runner.invoke(cli_app, ["sync"])
    assert result.exit_code == 1
    assert "UNAUTHORIZED" in result.stderr
    assert "expense config set --token" in result.stderr


@respx.mock
def test_sync_connection_error_surfaces_cleanly(configured):
    respx.get("https://api.example.com/v1/sync").mock(side_effect=httpx.ConnectError("refused"))
    result = runner.invoke(cli_app, ["sync"])
    assert result.exit_code == 2
    assert "could not reach engine" in result.stderr


@respx.mock
def test_sync_empty_resources_render_zero(configured):
    payload = {
        "sync_token": "33333333-3333-3333-3333-333333333333",
        "accounts": [],
        "categories": [],
        "hashtags": [],
        "inbox": [],
        "transactions": [],
        "reconciliations": [],
        "settings": {"user_id": "u1", "main_currency": "USD", "version": 1},
    }
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = runner.invoke(cli_app, ["sync", "--full"])
    assert result.exit_code == 0, result.stderr
    out = result.stdout
    assert re.search(r"^\s+accounts:\s+0$", out, re.MULTILINE)
    assert re.search(r"^\s+transactions:\s+0$", out, re.MULTILINE)
