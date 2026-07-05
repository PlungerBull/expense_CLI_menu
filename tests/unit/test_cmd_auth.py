import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from expense import config as config_module
from expense.cache import db as cache_db
from expense.commands.auth_cmd import app as auth_app
from expense.commands.auth_cmd import whoami as whoami_impl
from tests.unit.helpers import make_cli_app, sync_payload

cli_app = make_cli_app(auth_app, "auth", commands={"whoami": whoami_impl})

runner = CliRunner()


BOOTSTRAP_RESPONSE = {
    "user": {
        "id": "u_123",
        "email": "x@y.com",
        "display_name": "Alex",
        "last_login_at": "2026-04-23T10:00:00Z",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-04-23T10:00:00Z",
    },
    "settings": {
        "user_id": "u_123",
        "theme": 0,
        "start_of_week": 0,
        "main_currency": "USD",
        "transaction_sort_preference": 0,
        "display_timezone": "America/Lima",
        "sidebar_show_bank_accounts": True,
        "sidebar_show_people": True,
        "sidebar_show_categories": True,
        "version": 1,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-04-23T10:00:00Z",
        "deleted_at": None,
    },
}


@pytest.fixture
def cache_present(configured):
    """Auth writes refresh the replica only when the cache file already exists."""
    conn = cache_db.connect()
    conn.close()
    yield


@respx.mock
def test_bootstrap_caches_main_currency(configured):
    respx.post("https://api.example.com/v1/auth/bootstrap").mock(
        return_value=httpx.Response(200, json=BOOTSTRAP_RESPONSE)
    )
    result = runner.invoke(
        cli_app,
        [
            "auth",
            "bootstrap",
            "--display-name",
            "Alex",
            "--timezone",
            "America/Lima",
        ],
    )
    assert result.exit_code == 0, result.output

    cfg = config_module.load()
    assert cfg.main_currency == "USD"


@respx.mock
def test_me_refreshes_main_currency_cache(configured):
    updated_response = {
        **BOOTSTRAP_RESPONSE,
        "settings": {**BOOTSTRAP_RESPONSE["settings"], "main_currency": "PEN"},
    }
    respx.get("https://api.example.com/v1/auth/me").mock(
        return_value=httpx.Response(200, json=updated_response)
    )
    result = runner.invoke(cli_app, ["auth", "me"])
    assert result.exit_code == 0

    cfg = config_module.load()
    assert cfg.main_currency == "PEN"


@respx.mock
def test_me_404_prints_bootstrap_hint(configured):
    respx.get("https://api.example.com/v1/auth/me").mock(
        return_value=httpx.Response(
            404,
            json={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "User not found",
                    "fields": None,
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["auth", "me"])
    assert result.exit_code == 1
    assert "bootstrap" in result.output


@respx.mock
def test_whoami_equivalent_to_me(configured):
    route = respx.get("https://api.example.com/v1/auth/me").mock(
        return_value=httpx.Response(200, json=BOOTSTRAP_RESPONSE)
    )
    me_result = runner.invoke(cli_app, ["auth", "me", "--json"])
    whoami_result = runner.invoke(cli_app, ["whoami", "--json"])

    assert me_result.exit_code == 0
    assert whoami_result.exit_code == 0
    assert me_result.output == whoami_result.output
    assert route.call_count == 2


def test_settings_no_flags_errors(configured):
    result = runner.invoke(cli_app, ["auth", "settings"])
    assert result.exit_code == 1
    assert "No settings to update" in result.output


@respx.mock
def test_settings_non_currency_change_no_prompt(configured):
    # Engine always includes `recalculation` per null-over-omission; null when no recalc.
    response_body = {**BOOTSTRAP_RESPONSE["settings"], "recalculation": None}
    route = respx.put("https://api.example.com/v1/auth/settings").mock(
        return_value=httpx.Response(200, json=response_body)
    )
    result = runner.invoke(cli_app, ["auth", "settings", "--no-sidebar-show-people"])
    assert result.exit_code == 0, result.output

    req_body = json.loads(route.calls.last.request.content)
    assert req_body == {"sidebar_show_people": False}
    # Renderer must skip the recalculation key entirely when null — no "Rewrote" line.
    assert "Rewrote" not in result.output


@respx.mock
def test_settings_drops_none_fields_from_payload(configured):
    route = respx.put("https://api.example.com/v1/auth/settings").mock(
        return_value=httpx.Response(200, json=BOOTSTRAP_RESPONSE["settings"])
    )
    result = runner.invoke(cli_app, ["auth", "settings", "--theme", "1"])
    assert result.exit_code == 0

    req_body = json.loads(route.calls.last.request.content)
    assert req_body == {"theme": 1}


@respx.mock
def test_settings_main_currency_requires_yes_in_non_tty(configured):
    respx.put("https://api.example.com/v1/auth/settings").mock(
        return_value=httpx.Response(200, json=BOOTSTRAP_RESPONSE["settings"])
    )
    result = runner.invoke(cli_app, ["auth", "settings", "--main-currency", "PEN"])
    assert result.exit_code == 1
    assert "non-interactive" in result.output


@respx.mock
def test_settings_main_currency_with_yes_surfaces_recalc(configured):
    updated_settings = {
        **BOOTSTRAP_RESPONSE["settings"],
        "main_currency": "PEN",
        "recalculation": {
            "regular_transactions": 142,
            "transfer_transactions": 6,
            "orphan_transfer_legs": 0,
            "inbox_items": 3,
            "total": 151,
        },
    }
    respx.put("https://api.example.com/v1/auth/settings").mock(
        return_value=httpx.Response(200, json=updated_settings)
    )
    result = runner.invoke(cli_app, ["auth", "settings", "--main-currency", "PEN", "--yes"])
    assert result.exit_code == 0, result.output

    cfg = config_module.load()
    assert cfg.main_currency == "PEN"
    assert "Rewrote 151 transaction(s) in home currency." in result.output
    # No orphans → no warning line.
    assert "need attention" not in result.output


@respx.mock
def test_settings_main_currency_orphan_warning(configured):
    updated_settings = {
        **BOOTSTRAP_RESPONSE["settings"],
        "main_currency": "PEN",
        "recalculation": {
            "regular_transactions": 100,
            "transfer_transactions": 8,
            "orphan_transfer_legs": 2,
            "inbox_items": 0,
            "total": 108,
        },
    }
    respx.put("https://api.example.com/v1/auth/settings").mock(
        return_value=httpx.Response(200, json=updated_settings)
    )
    result = runner.invoke(cli_app, ["auth", "settings", "--main-currency", "PEN", "--yes"])
    assert result.exit_code == 0, result.output
    assert "Rewrote 108 transaction(s)" in result.output
    assert "2 transfer leg(s) need attention" in result.output


@respx.mock
def test_me_json_mode(configured):
    respx.get("https://api.example.com/v1/auth/me").mock(
        return_value=httpx.Response(200, json=BOOTSTRAP_RESPONSE)
    )
    result = runner.invoke(cli_app, ["auth", "me", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data == BOOTSTRAP_RESPONSE


def test_profile_no_flags_errors(configured):
    result = runner.invoke(cli_app, ["auth", "profile"])
    assert result.exit_code == 1
    assert "No profile fields to update" in result.output


@respx.mock
def test_profile_display_name_success(configured):
    updated_user = {**BOOTSTRAP_RESPONSE["user"], "display_name": "Alex"}
    route = respx.put("https://api.example.com/v1/auth/profile").mock(
        return_value=httpx.Response(200, json=updated_user)
    )
    result = runner.invoke(cli_app, ["auth", "profile", "--display-name", "Alex"])
    assert result.exit_code == 0, result.output

    req_body = json.loads(route.calls.last.request.content)
    assert req_body == {"display_name": "Alex"}
    assert "display_name: Alex" in result.output


@respx.mock
def test_profile_json_mode(configured):
    updated_user = {**BOOTSTRAP_RESPONSE["user"], "display_name": "Alex"}
    respx.put("https://api.example.com/v1/auth/profile").mock(
        return_value=httpx.Response(200, json=updated_user)
    )
    result = runner.invoke(cli_app, ["auth", "profile", "--display-name", "Alex", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == updated_user


@respx.mock
def test_profile_422_renders_engine_error(configured):
    respx.put("https://api.example.com/v1/auth/profile").mock(
        return_value=httpx.Response(
            422,
            json={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid input.",
                    "fields": {"display_name": "Must not be null."},
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["auth", "profile", "--display-name", "Alex"])
    assert result.exit_code == 1
    assert "VALIDATION_ERROR" in result.output
    assert "display_name" in result.output


@respx.mock
def test_bootstrap_timezone_auto_detected_from_tz_env(configured, monkeypatch):
    monkeypatch.setenv("TZ", "America/Lima")
    route = respx.post("https://api.example.com/v1/auth/bootstrap").mock(
        return_value=httpx.Response(200, json=BOOTSTRAP_RESPONSE)
    )
    result = runner.invoke(cli_app, ["auth", "bootstrap", "--display-name", "Alex"])
    assert result.exit_code == 0, result.output
    assert "Using timezone: America/Lima" in result.output

    req_body = json.loads(route.calls.last.request.content)
    assert req_body == {"display_name": "Alex", "timezone": "America/Lima"}


# ---------------------------------------------------------------------------
# Post-write replica refresh (polish backlog 1.7)
# ---------------------------------------------------------------------------


@respx.mock
def test_settings_triggers_post_write_sync(cache_present):
    respx.put("https://api.example.com/v1/auth/settings").mock(
        return_value=httpx.Response(200, json=BOOTSTRAP_RESPONSE["settings"])
    )
    sync_route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(
            200,
            json=sync_payload(settings={"user_id": "u_123", "main_currency": "USD", "version": 1}),
        )
    )
    result = runner.invoke(cli_app, ["auth", "settings", "--theme", "1"])
    assert result.exit_code == 0, result.output
    assert sync_route.called


@respx.mock
def test_profile_triggers_post_write_sync(cache_present):
    respx.put("https://api.example.com/v1/auth/profile").mock(
        return_value=httpx.Response(200, json=BOOTSTRAP_RESPONSE["user"])
    )
    sync_route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(
            200,
            json=sync_payload(settings={"user_id": "u_123", "main_currency": "USD", "version": 1}),
        )
    )
    result = runner.invoke(cli_app, ["auth", "profile", "--display-name", "Alex"])
    assert result.exit_code == 0, result.output
    assert sync_route.called


@respx.mock
def test_bootstrap_triggers_post_write_sync(cache_present):
    respx.post("https://api.example.com/v1/auth/bootstrap").mock(
        return_value=httpx.Response(200, json=BOOTSTRAP_RESPONSE)
    )
    sync_route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(
            200,
            json=sync_payload(settings={"user_id": "u_123", "main_currency": "USD", "version": 1}),
        )
    )
    result = runner.invoke(
        cli_app,
        ["auth", "bootstrap", "--display-name", "Alex", "--timezone", "America/Lima"],
    )
    assert result.exit_code == 0, result.output
    assert sync_route.called
