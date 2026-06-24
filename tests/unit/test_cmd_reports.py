import json
import re
from uuid import uuid4

import httpx
import pytest
import respx
import typer
from typer.testing import CliRunner

from expense import config as config_module
from expense.cache import db as cache_db
from expense.cache import state as cache_state
from expense.commands import reports_cmd
from expense.commands.reports_cmd import app as reports_app

cli_app = typer.Typer()


@cli_app.callback()
def _root() -> None:
    pass


cli_app.add_typer(reports_app, name="reports")

runner = CliRunner()


_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[mGKH]")


def _strip_panel(output: str) -> str:
    """Typer wraps long error messages across box-drawn panel lines.

    Strip ANSI color codes (which CI emits but local doesn't), box-drawing
    characters, and collapse line breaks so substring asserts work regardless
    of terminal width or color support. Spaces inside the message are preserved.
    """
    no_ansi = _ANSI_ESCAPE_RE.sub("", output)
    no_box = "".join(c for c in no_ansi if c not in "│╭╮╰╯─\n\t")
    return " ".join(no_box.split())


SINGLE_MONTH_RESPONSE = {
    "month": {"year": 2026, "month": 3},
    "categories": [
        {
            "id": "cat-food",
            "name": "Food",
            "spent_cents": -50000,
            "spent_home_cents": -50000,
            "hashtag_breakdown": [
                {
                    "hashtag_ids": ["aaaa"],
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
        "outflow_cents": 50000,
        "outflow_home_cents": 50000,
        "net_cents": 750000,
        "net_home_cents": 750000,
    },
}

RANGE_RESPONSE = {
    "months": [
        {
            "month": {"year": 2025, "month": 11},
            "categories": [
                {
                    "id": "cat-food",
                    "name": "Food",
                    "spent_cents": -10000,
                    "spent_home_cents": -10000,
                    "hashtag_breakdown": [],
                },
                {
                    "id": "cat-rent",
                    "name": "Rent",
                    "spent_cents": -200000,
                    "spent_home_cents": -200000,
                    "hashtag_breakdown": [],
                },
            ],
            "totals": {
                "inflow_cents": 0,
                "inflow_home_cents": 0,
                "outflow_cents": 210000,
                "outflow_home_cents": 210000,
                "net_cents": -210000,
                "net_home_cents": -210000,
            },
        },
        {
            "month": {"year": 2025, "month": 12},
            "categories": [
                {
                    "id": "cat-food",
                    "name": "Food",
                    "spent_cents": -15000,
                    "spent_home_cents": -15000,
                    "hashtag_breakdown": [],
                },
                {
                    "id": "cat-rent",
                    "name": "Rent",
                    "spent_cents": -200000,
                    "spent_home_cents": -200000,
                    "hashtag_breakdown": [],
                },
            ],
            "totals": {
                "inflow_cents": 100000,
                "inflow_home_cents": 100000,
                "outflow_cents": 215000,
                "outflow_home_cents": 215000,
                "net_cents": -115000,
                "net_home_cents": -115000,
            },
        },
    ]
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
    # Seed a healthy (empty) replica so the single-month report's hashtag-name
    # warming (ensure_synced) is a no-op — no /v1/sync round-trip to mock here.
    cfg = config_module.ensure_loaded()
    conn = cache_db.connect()
    try:
        cache_state.write_identity(
            conn, user_id="u1", client_id=str(cfg.client_id), engine_url=cfg.engine_url
        )
        cache_state.write_token(conn, "tok-test")
    finally:
        conn.close()
    yield


@pytest.fixture
def configured_cold(tmp_path, monkeypatch):
    """Config present but the replica is cold (never synced)."""
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


def _sync_payload_with_hashtag() -> dict:
    return {
        "sync_token": "tok-1",
        "accounts": [],
        "categories": [],
        "hashtags": [
            {
                "id": "aaaa",
                "user_id": "u1",
                "name": "Groceries",
                "is_archived": False,
                "deleted_at": None,
                "sort_order": 1,
                "version": 1,
            }
        ],
        "inbox": [],
        "transactions": [],
        "reconciliations": [],
        "settings": {"user_id": "u1", "main_currency": "PEN", "version": 1},
    }


@respx.mock
def test_monthly_single_cold_cache_warms_and_resolves_names(configured_cold):
    """A cold cache is warmed via GET /v1/sync so hashtag UUIDs render as names.

    This is the bug the screenshot showed: with an empty replica the breakdown
    fell back to raw ids. The report now triggers a cold-start sync first.
    """
    sync_route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=_sync_payload_with_hashtag())
    )
    respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(200, json=SINGLE_MONTH_RESPONSE)
    )
    result = runner.invoke(cli_app, ["reports", "monthly", "--date", "2026-03"])
    assert result.exit_code == 0, result.output
    assert sync_route.called
    # The "aaaa" combo now resolves to its name instead of the raw id.
    assert "Groceries" in result.output


@respx.mock
def test_monthly_single_no_cache_skips_warm(configured_cold):
    """no_cache (stateless) suppresses the warming sync entirely."""
    sync_route = respx.get("https://api.example.com/v1/sync")
    respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(200, json=SINGLE_MONTH_RESPONSE)
    )
    cfg = config_module.ensure_loaded()
    reports_cmd.run_single_month(cfg, year=2026, month=3, no_cache=True)
    assert not sync_route.called


@respx.mock
def test_monthly_single_happy(configured):
    route = respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(200, json=SINGLE_MONTH_RESPONSE)
    )
    result = runner.invoke(cli_app, ["reports", "monthly", "--date", "2026-03"])
    assert result.exit_code == 0, result.output
    assert "Month: 2026-03" in result.output
    assert "Food" in result.output
    # New table layout: hashtag sub-rows are indented in the Name column with
    # spent/home as right-aligned cells (no `label: amount` colon syntax).
    assert "aaaa" in result.output
    assert "-300.00" in result.output
    assert "(no hashtags)" in result.output
    assert "-200.00" in result.output
    assert "net: 7,500.00" in result.output

    request = route.calls.last.request
    assert request.url.params.get("year") == "2026"
    assert request.url.params.get("month") == "3"
    assert "from_year" not in request.url.params


@respx.mock
def test_monthly_single_json_passthrough(configured):
    respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(200, json=SINGLE_MONTH_RESPONSE)
    )
    result = runner.invoke(cli_app, ["reports", "monthly", "--date", "2026-03", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == SINGLE_MONTH_RESPONSE


@respx.mock
def test_monthly_range_happy(configured):
    route = respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(200, json=RANGE_RESPONSE)
    )
    result = runner.invoke(cli_app, ["reports", "monthly", "--from", "2025-11", "--to", "2025-12"])
    assert result.exit_code == 0, result.output
    assert "2025-11" in result.output
    assert "2025-12" in result.output
    assert "Food" in result.output
    assert "Rent" in result.output
    assert "Totals (net)" in result.output
    assert "-2,100.00" in result.output
    assert "-1,150.00" in result.output

    request = route.calls.last.request
    assert request.url.params.get("from_year") == "2025"
    assert request.url.params.get("from_month") == "11"
    assert request.url.params.get("to_year") == "2025"
    assert request.url.params.get("to_month") == "12"
    assert "year" not in request.url.params


@respx.mock
def test_monthly_range_json_passthrough(configured):
    respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(200, json=RANGE_RESPONSE)
    )
    result = runner.invoke(
        cli_app, ["reports", "monthly", "--from", "2025-11", "--to", "2025-12", "--json"]
    )
    assert result.exit_code == 0
    assert json.loads(result.output) == RANGE_RESPONSE


@respx.mock
def test_monthly_no_args_errors_before_http(configured):
    route = respx.get("https://api.example.com/v1/reports/monthly")
    result = runner.invoke(cli_app, ["reports", "monthly"])
    assert result.exit_code != 0
    assert "Pass either --date" in _strip_panel(result.output)
    assert route.call_count == 0


@respx.mock
def test_monthly_both_forms_errors_before_http(configured):
    route = respx.get("https://api.example.com/v1/reports/monthly")
    result = runner.invoke(
        cli_app, ["reports", "monthly", "--date", "2026-03", "--from", "2025-11"]
    )
    assert result.exit_code != 0
    assert "mutually exclusive" in _strip_panel(result.output)
    assert route.call_count == 0


@respx.mock
def test_monthly_partial_range_errors_before_http(configured):
    route = respx.get("https://api.example.com/v1/reports/monthly")
    result = runner.invoke(cli_app, ["reports", "monthly", "--from", "2025-11"])
    assert result.exit_code != 0
    assert "must be passed together" in _strip_panel(result.output)
    assert route.call_count == 0


@respx.mock
def test_monthly_range_too_wide_errors_before_http(configured):
    route = respx.get("https://api.example.com/v1/reports/monthly")
    result = runner.invoke(cli_app, ["reports", "monthly", "--from", "2024-01", "--to", "2026-04"])
    assert result.exit_code != 0
    assert "max is 24" in _strip_panel(result.output)
    assert route.call_count == 0


@respx.mock
def test_monthly_range_inverted_errors_before_http(configured):
    route = respx.get("https://api.example.com/v1/reports/monthly")
    result = runner.invoke(cli_app, ["reports", "monthly", "--from", "2026-04", "--to", "2025-11"])
    assert result.exit_code != 0
    assert "must be on or before" in _strip_panel(result.output)
    assert route.call_count == 0


@respx.mock
def test_monthly_invalid_date_shape_errors_before_http(configured):
    route = respx.get("https://api.example.com/v1/reports/monthly")
    result = runner.invoke(cli_app, ["reports", "monthly", "--date", "2026-3"])
    assert result.exit_code != 0
    assert "YYYY-MM" in _strip_panel(result.output)
    assert route.call_count == 0


@respx.mock
def test_monthly_engine_422_surfaces_validation_error(configured):
    respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(
            422,
            json={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid month payload.",
                    "fields": {"year": "Must be between 2000 and 2100."},
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["reports", "monthly", "--date", "2026-04"])
    assert result.exit_code == 1
    assert "VALIDATION_ERROR" in result.output
    assert "year" in result.output


@respx.mock
def test_monthly_engine_500(configured):
    respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(
            500,
            json={"error": {"code": "INTERNAL", "message": "boom", "fields": None}},
        )
    )
    result = runner.invoke(cli_app, ["reports", "monthly", "--date", "2026-04"])
    assert result.exit_code == 1
    assert "INTERNAL" in result.output


@respx.mock
def test_monthly_connection_error(configured):
    respx.get("https://api.example.com/v1/reports/monthly").mock(
        side_effect=httpx.ConnectError("refused")
    )
    result = runner.invoke(cli_app, ["reports", "monthly", "--date", "2026-04"])
    assert result.exit_code == 2
    assert "could not reach engine" in result.output
