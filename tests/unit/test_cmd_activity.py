import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from expense.commands import activity_cmd
from expense.commands.activity_cmd import app as activity_app
from tests.unit.helpers import FakeClient, make_cli_app

cli_app = make_cli_app(activity_app, "activity")

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
    assert "22222222" in result.output  # UUID prefix fallback (name lookup missed)
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
    # Snapshot contents not rendered; the live name lookup also misses (no route)
    # so "Coffee" stays out and the row falls back to the UUID prefix instead.
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
def test_list_resource_name_resolved_live(configured):
    """The Resource column shows the human name fetched from the engine."""
    respx.get("https://api.example.com/v1/activity").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    respx.get("https://api.example.com/v1/transactions/22222222-2222-2222-2222-222222222222").mock(
        return_value=httpx.Response(200, json={"id": "22222222", "title": "Latte"})
    )
    result = runner.invoke(cli_app, ["activity", "list"])
    assert result.exit_code == 0, result.output
    assert "Latte" in result.output
    # Name resolved cleanly, so the UUID prefix never reaches the Resource cell.
    assert "22222222" not in result.output


@respx.mock
def test_list_resource_name_fallback_to_uuid_prefix(configured):
    """A 404 on the live lookup (deleted row) degrades to the 8-char UUID."""
    respx.get("https://api.example.com/v1/activity").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    respx.get("https://api.example.com/v1/transactions/22222222-2222-2222-2222-222222222222").mock(
        return_value=httpx.Response(
            404, json={"error": {"code": "NOT_FOUND", "message": "gone", "fields": None}}
        )
    )
    result = runner.invoke(cli_app, ["activity", "list"])
    assert result.exit_code == 0, result.output
    assert "22222222" in result.output


# --- _resolve_resource_name, all six kinds (backlog 6.6a) -------------------


def _client(responses: dict) -> FakeClient:
    """A FakeClient answering the given GET paths; every other path 404s."""
    client = FakeClient()
    client.get_responses.update(responses)
    return client


@pytest.mark.parametrize(
    ("rtype", "path", "row", "expected"),
    [
        ("account", "/accounts/abc-123", {"name": "BCP"}, "BCP"),
        ("accounts", "/accounts/abc-123", {"name": "BCP"}, "BCP"),  # plural alias
        ("category", "/categories/abc-123", {"name": "Comida"}, "Comida"),
        ("categories", "/categories/abc-123", {"name": "Comida"}, "Comida"),
        ("hashtag", "/hashtags/abc-123", {"name": "viajes"}, "#viajes"),  # '#' prefix
        ("hashtags", "/hashtags/abc-123", {"name": "viajes"}, "#viajes"),
        ("inbox", "/inbox/abc-123", {"title": "Almuerzo"}, "Almuerzo"),
        ("inbox_items", "/inbox/abc-123", {"description": "nota"}, "nota"),  # title fallback
        ("transaction", "/transactions/abc-123", {"title": "Latte"}, "Latte"),
        (
            "expense_transactions",
            "/transactions/abc-123",
            {"description": "sin título"},
            "sin título",
        ),
    ],
)
def test_resolve_resource_name_per_kind(rtype, path, row, expected):
    client = _client({path: dict(row)})
    assert activity_cmd._resolve_resource_name(rtype, "abc-123", client) == expected
    assert client.requests == [("GET", path)]


def test_resolve_resource_name_miss_falls_back_to_prefix():
    """No row at that path (404) → the 8-char prefix, never an exception."""
    client = _client({})
    assert activity_cmd._resolve_resource_name("account", "0123456789ab", client) == "01234567"


def test_resolve_reconciliation_composite_labels():
    """date+account → 'date / name'; degrades to date-only, name-only, then prefix."""
    recon = {"statement_date": "2026-05-01T00:00:00Z", "account_id": "acc1"}

    client = _client({"/reconciliations/r-1": recon, "/accounts/acc1": {"name": "BCP"}})
    assert activity_cmd._resolve_resource_name("reconciliation", "r-1", client) == (
        "2026-05-01 / BCP"
    )

    client = _client({"/reconciliations/r-1": recon})  # account gone → date only
    assert activity_cmd._resolve_resource_name("reconciliations", "r-1", client) == "2026-05-01"

    client = _client(
        {"/reconciliations/r-1": {"account_id": "acc1"}, "/accounts/acc1": {"name": "BCP"}}
    )
    assert activity_cmd._resolve_resource_name("reconciliation", "r-1", client) == "BCP"  # no date

    client = _client({"/reconciliations/0123456789ab": {}})
    assert activity_cmd._resolve_resource_name("reconciliation", "0123456789ab", client) == (
        "01234567"
    )


def test_resolve_empty_name_falls_back_to_prefix():
    client = _client({"/hashtags/0123456789ab": {"name": ""}})
    assert activity_cmd._resolve_resource_name("hashtag", "0123456789ab", client) == "01234567"


def test_resolve_unknown_kind_and_bad_id():
    """Unknown kinds and null ids never reach the engine at all."""
    client = _client({})
    assert activity_cmd._resolve_resource_name("user", "0123456789ab", client) == "01234567"
    assert activity_cmd._resolve_resource_name(None, "0123456789ab", client) == "01234567"
    assert activity_cmd._resolve_resource_name("account", None, client) == "—"
    assert client.requests == []
