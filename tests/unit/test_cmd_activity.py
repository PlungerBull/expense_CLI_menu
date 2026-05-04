import json
from uuid import uuid4

import httpx
import pytest
import respx
import typer
from typer.testing import CliRunner

from expense import config as config_module
from expense.commands.activity_cmd import app as activity_app
from expense.context import AppContext

cli_app = typer.Typer()


@cli_app.callback()
def _root(ctx: typer.Context) -> None:
    ctx.obj = AppContext()


cli_app.add_typer(activity_app, name="activity")

runner = CliRunner()


ACTIVITY_ROW = {
    "id": "11111111-1111-1111-1111-111111111111",
    "user_id": "u1",
    "resource_type": "expense_transactions",
    "resource_id": "22222222-2222-2222-2222-222222222222",
    "action": 1,
    "before_snapshot": None,
    "after_snapshot": {"id": "22222222-2222-2222-2222-222222222222", "title": "Coffee"},
    "changed_by": "u1",
    "actor_type": "user",
    "created_at": "2026-05-03T10:00:00Z",
}

LIST_RESPONSE = [ACTIVITY_ROW]


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
def test_list_happy_no_filters(configured):
    route = respx.get("https://api.example.com/v1/activity").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["activity", "list"])
    assert result.exit_code == 0, result.output
    assert "CREATED" in result.output
    assert "expense_transactions" in result.output
    assert "u1 (user)" in result.output

    # No filters → no params on the request
    request = route.calls.last.request
    assert request.url.params.get("resource_type") is None
    assert request.url.params.get("resource_id") is None


@respx.mock
def test_list_with_filters_and_pagination_params(configured):
    route = respx.get("https://api.example.com/v1/activity").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(
        cli_app,
        [
            "activity",
            "list",
            "--resource-type",
            "expense_transactions",
            "--resource-id",
            "22222222-2222-2222-2222-222222222222",
            "--limit",
            "5",
            "--offset",
            "0",
        ],
    )
    assert result.exit_code == 0, result.output

    request = route.calls.last.request
    assert request.url.params.get("resource_type") == "expense_transactions"
    assert request.url.params.get("resource_id") == "22222222-2222-2222-2222-222222222222"
    assert request.url.params.get("limit") == "5"
    assert request.url.params.get("offset") == "0"


@respx.mock
def test_list_pagination_hint(configured):
    paginated = {
        "items": [ACTIVITY_ROW],
        "total": 5,
        "limit": 1,
        "offset": 0,
    }
    respx.get("https://api.example.com/v1/activity").mock(
        return_value=httpx.Response(200, json=paginated)
    )
    result = runner.invoke(cli_app, ["activity", "list"])
    assert result.exit_code == 0, result.output
    assert "showing 1 of 5" in result.output


@respx.mock
def test_list_json_mode_passthrough(configured):
    respx.get("https://api.example.com/v1/activity").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["activity", "list", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == LIST_RESPONSE


@respx.mock
def test_list_empty(configured):
    respx.get("https://api.example.com/v1/activity").mock(return_value=httpx.Response(200, json=[]))
    result = runner.invoke(cli_app, ["activity", "list"])
    assert result.exit_code == 0, result.output
    assert "(no activity)" in result.output


@respx.mock
def test_list_human_renderer_omits_snapshots(configured):
    """Snapshots are large nested dicts; only --json should surface them."""
    respx.get("https://api.example.com/v1/activity").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["activity", "list"])
    assert result.exit_code == 0, result.output
    assert "before_snapshot" not in result.output
    assert "after_snapshot" not in result.output
    assert "Coffee" not in result.output  # snapshot contents not rendered


@respx.mock
def test_list_unknown_action_code_falls_back_to_int(configured):
    weird = {**ACTIVITY_ROW, "action": 99}
    respx.get("https://api.example.com/v1/activity").mock(
        return_value=httpx.Response(200, json=[weird])
    )
    result = runner.invoke(cli_app, ["activity", "list"])
    assert result.exit_code == 0, result.output
    assert "action      99" in result.output


@respx.mock
def test_list_422_bad_resource_id(configured):
    respx.get("https://api.example.com/v1/activity").mock(
        return_value=httpx.Response(
            422,
            json={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "resource_id must be a UUID",
                    "fields": {"resource_id": "not a UUID"},
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["activity", "list", "--resource-id", "not-a-uuid"])
    assert result.exit_code == 1
    assert "VALIDATION_ERROR" in result.output
    assert "resource_id" in result.output
