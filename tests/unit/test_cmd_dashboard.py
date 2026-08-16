import json

import httpx
import respx
from typer.testing import CliRunner

from expense.commands.dashboard_cmd import dashboard
from tests.unit.helpers import make_cli_app

cli_app = make_cli_app(commands={"dashboard": dashboard})

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
    # Aggregates are home-currency ONLY since the engine's 2026-08-05 read-time
    # currency change: the native `spent_cents` / `{inflow,outflow,net}_cents`
    # were deleted, and every survivor is nullable with an `unconverted_count`.
    "categories": [
        {
            "id": "33333333-3333-3333-3333-333333333333",
            "name": "Food",
            "spent_home_cents": -50000,
            "unconverted_count": 0,
            "hashtag_breakdown": [
                {
                    "hashtag_ids": ["aaaa", "bbbb"],
                    "spent_home_cents": -30000,
                    "unconverted_count": 0,
                },
                {
                    "hashtag_ids": [],
                    "spent_home_cents": -20000,
                    "unconverted_count": 0,
                },
            ],
        }
    ],
    "totals": {
        "inflow_home_cents": 800000,
        "outflow_home_cents": 320000,
        "net_home_cents": 480000,
        "unconverted_count": 0,
    },
    "archived_accounts": None,
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
}

#: A month the engine refused to total, plus a category with nothing spent.
#: `Empty` must not be drawn at all; `Travel` must say how many rows are behind
#: its missing figure — a null is neither zero nor missing.
DASHBOARD_UNCONVERTIBLE = {
    **DASHBOARD_RESPONSE,
    "categories": [
        *DASHBOARD_RESPONSE["categories"],
        {
            "id": "77777777-7777-7777-7777-777777777777",
            "name": "Empty",
            "spent_home_cents": 0,
            "unconverted_count": 0,
            "hashtag_breakdown": [],
        },
        {
            "id": "88888888-8888-8888-8888-888888888888",
            "name": "Travel",
            "spent_home_cents": None,
            "unconverted_count": 3,
            "hashtag_breakdown": [
                {"hashtag_ids": [], "spent_home_cents": None, "unconverted_count": 3}
            ],
        },
    ],
    "totals": {
        "inflow_home_cents": None,
        "outflow_home_cents": None,
        "net_home_cents": None,
        "unconverted_count": 3,
    },
}


@respx.mock
def test_dashboard_happy(configured):
    route = respx.get("https://api.example.com/v1/dashboard").mock(
        return_value=httpx.Response(200, json=DASHBOARD_RESPONSE)
    )
    result = runner.invoke(cli_app, ["dashboard"])
    assert result.exit_code == 0, result.output
    assert "Month: 2026-04" in result.output
    # New tabular layout: Name + Currency + Balance in one row per account; no
    # parenthetical "(home: ...)" since the Home column was dropped.
    assert "Month: 2026-04" in result.output
    assert "BCP Soles" in result.output
    assert "PEN" in result.output
    assert "1,250.00" in result.output
    assert "Alex" in result.output
    assert "Food" in result.output
    # Hashtag sub-rows render inside the Categories table (Name col gets the
    # combo label, Spent col gets the amount — no `label: amount` colon).
    assert "aaaa + bbbb" in result.output
    assert "-300.00" in result.output
    assert "(no hashtags)" in result.output
    assert "-200.00" in result.output
    assert "inflow: 8,000.00" in result.output

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
    # The archived category / hashtag lifetime panels were deleted from the
    # engine on 2026-08-05 — an archived account still holds real money, an
    # archived category holds only history and soft delete already hides it from
    # the pickers. `--include-archived` now controls the accounts panel alone.
    assert "Archived categories:" not in result.output
    assert "Archived hashtags:" not in result.output
    assert "Lifetime spent" not in result.output

    request = route.calls.last.request
    assert request.url.params.get("include_archived") == "true"


@respx.mock
def test_dashboard_unconvertible_reports_the_count_never_zero(configured):
    """A null aggregate is neither zero nor missing — it says how many rows it hides."""
    respx.get("https://api.example.com/v1/dashboard").mock(
        return_value=httpx.Response(200, json=DASHBOARD_UNCONVERTIBLE)
    )
    result = runner.invoke(cli_app, ["dashboard"])
    assert result.exit_code == 0, result.output

    # The unpriceable category keeps its row and carries the count, on the
    # category and on its hashtag combo alike.
    assert "Travel" in result.output
    assert result.output.count("3 unrated") >= 2
    # Never a zero, never a native-currency fallback, never a bare "(null)".
    assert "(null)" not in result.output

    # The three totals share one count, so they fail together as one line.
    assert "3 unrated — no totals this month" in result.output
    assert "inflow:" not in result.output

    # A category with nothing spent is not drawn at all.
    assert "Empty" not in result.output
    # ...while one that did spend is unaffected.
    assert "Food" in result.output


@respx.mock
def test_dashboard_json_is_untouched_by_the_hiding(configured):
    """--json stays the raw engine body — including the rows the table hides."""
    respx.get("https://api.example.com/v1/dashboard").mock(
        return_value=httpx.Response(200, json=DASHBOARD_UNCONVERTIBLE)
    )
    result = runner.invoke(cli_app, ["dashboard", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == DASHBOARD_UNCONVERTIBLE


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
            "inflow_home_cents": 0,
            "outflow_home_cents": 0,
            "net_home_cents": 0,
            "unconverted_count": 0,
        },
        "archived_accounts": None,
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
    assert result.exit_code == 6
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
