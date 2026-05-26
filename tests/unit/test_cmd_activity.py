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
from expense.errors import EngineError

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
    # Cache may not be initialized in unit tests; force the resolver's
    # cache-miss fallback (UUID prefix) so tests don't depend on a live replica.
    monkeypatch.setenv("EXPENSE_STATELESS", "1")
    yield


@respx.mock
def test_list_happy_no_filters(configured):
    route = respx.get("https://api.example.com/v1/activity").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["activity", "list"])
    assert result.exit_code == 0, result.output
    # Table columns: action name, actor_type, resource_type, UUID prefix fallback.
    assert "CREATED" in result.output
    assert "user" in result.output
    assert "expense_transactions" in result.output
    assert "22222222" in result.output  # UUID prefix fallback (cache miss)
    # Header row is present (table format).
    assert "Date" in result.output
    assert "Resource" in result.output

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
    # Snapshot contents not rendered; resolver also misses (cache empty) so
    # "Coffee" stays out and the row falls back to the UUID prefix instead.
    assert "Coffee" not in result.output


@respx.mock
def test_list_unknown_action_code_falls_back_to_int(configured):
    weird = {**ACTIVITY_ROW, "action": 99}
    respx.get("https://api.example.com/v1/activity").mock(
        return_value=httpx.Response(200, json=[weird])
    )
    result = runner.invoke(cli_app, ["activity", "list"])
    assert result.exit_code == 0, result.output
    # Action column now just shows the raw int as a string.
    assert "99" in result.output


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


@respx.mock
def test_list_resource_name_resolved_from_cache(configured, monkeypatch):
    """When the cache has the row, the Resource column shows the human name."""
    from expense.cache import queries

    monkeypatch.setattr(queries, "get_transaction", lambda _id: {"id": _id, "title": "Latte"})
    respx.get("https://api.example.com/v1/activity").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["activity", "list"])
    assert result.exit_code == 0, result.output
    assert "Latte" in result.output
    # When name resolves cleanly, the UUID prefix is not in the Resource cell.
    # (It may still appear inside the JSON-only request body; we only assert
    #  it's absent from the rendered table row.)
    # The UUID literal "22222222" is the prefix; absent because Latte rendered.
    assert "22222222" not in result.output


@respx.mock
def test_list_resource_name_fallback_to_uuid_prefix(configured, monkeypatch):
    """When the cache raises NOT_FOUND, the Resource column shows the 8-char UUID."""
    from expense.cache import queries

    def _miss(_id: str) -> dict:
        raise EngineError(
            code="NOT_FOUND", message="not found", fields=None, status=404, raw_body={}
        )

    monkeypatch.setattr(queries, "get_transaction", _miss)
    respx.get("https://api.example.com/v1/activity").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["activity", "list"])
    assert result.exit_code == 0, result.output
    assert "22222222" in result.output
