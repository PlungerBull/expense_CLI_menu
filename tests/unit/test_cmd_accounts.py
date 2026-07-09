import json
from uuid import UUID

import httpx
import pytest
import respx
from typer.testing import CliRunner

from expense import config as config_module
from expense.cache import db as cache_db
from expense.cache import state as cache_state
from expense.commands.accounts_cmd import app as accounts_app
from tests.unit.helpers import insert_account, make_cli_app, sync_payload

cli_app = make_cli_app(accounts_app, "accounts")

runner = CliRunner()


ACCOUNT_RESPONSE = {
    "id": "11111111-1111-1111-1111-111111111111",
    "user_id": "u1",
    "name": "BCP Soles",
    "currency_code": "PEN",
    "color": "#FF0000",
    "sort_order": 1,
    "is_person": False,
    "is_archived": False,
    "deleted_at": None,
    "version": 1,
    "created_at": "2026-04-24T10:00:00Z",
    "updated_at": "2026-04-24T10:00:00Z",
    "current_balance_cents": 125000,
    "current_balance_home_cents": 125000,
}

LIST_RESPONSE = [ACCOUNT_RESPONSE]


@pytest.fixture
def cache_populated(configured):
    """Populate the cache directly via SQL — no respx involvement."""
    cfg = config_module.ensure_loaded()
    conn = cache_db.connect()
    try:
        rows = [
            {**ACCOUNT_RESPONSE, "current_balance_home_cents": None},
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "user_id": "u1",
                "name": "Cash",
                "currency_code": "PEN",
                "color": None,
                "sort_order": 2,
                "is_person": False,
                "is_archived": False,
                "deleted_at": None,
                "version": 1,
                "current_balance_cents": 5000,
                "current_balance_home_cents": None,
            },
            {
                "id": "33333333-3333-3333-3333-333333333333",
                "user_id": "u1",
                "name": "Old BCP",
                "currency_code": "PEN",
                "color": None,
                "sort_order": 99,
                "is_person": False,
                "is_archived": True,
                "deleted_at": None,
                "version": 1,
                "current_balance_cents": 0,
                "current_balance_home_cents": None,
            },
            {
                "id": "44444444-4444-4444-4444-444444444444",
                "user_id": "u1",
                "name": "Alex",
                "currency_code": "PEN",
                "color": None,
                "sort_order": 50,
                "is_person": True,
                "is_archived": False,
                "deleted_at": None,
                "version": 1,
                "current_balance_cents": -4500,
                "current_balance_home_cents": None,
            },
        ]
        for row in rows:
            insert_account(conn, row)
        cache_state.write_identity(
            conn,
            user_id="u1",
            client_id=str(cfg.client_id),
            engine_url=cfg.engine_url,
            token_fingerprint=cache_state.token_fingerprint(cfg.token),
        )
        cache_state.write_token(conn, "tok-populated")
    finally:
        conn.close()
    yield


@respx.mock
def test_list_engine_path_with_no_cache(configured):
    route = respx.get("https://api.example.com/v1/accounts").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["--no-cache", "accounts", "list", "--include-archived"])
    assert result.exit_code == 0, result.output
    assert "BCP Soles" in result.output

    request = route.calls.last.request
    assert request.url.params.get("include_archived") == "true"


@respx.mock
def test_list_deleted_column_marks_soft_deleted_rows(configured):
    deleted = {
        **ACCOUNT_RESPONSE,
        "id": "55555555-5555-5555-5555-555555555555",
        "name": "Closed USD",
        "deleted_at": "2026-06-01T09:00:00Z",
    }
    route = respx.get("https://api.example.com/v1/accounts").mock(
        return_value=httpx.Response(200, json=[ACCOUNT_RESPONSE, deleted])
    )
    result = runner.invoke(cli_app, ["--no-cache", "accounts", "list", "--include-deleted"])
    assert result.exit_code == 0, result.output
    assert "Deleted" in result.output

    lines = result.output.splitlines()
    live_row = next(line for line in lines if "BCP Soles" in line)
    deleted_row = next(line for line in lines if "Closed USD" in line)
    assert live_row.rstrip().endswith("no")
    assert deleted_row.rstrip().endswith("yes")

    request = route.calls.last.request
    assert request.url.params.get("include_deleted") == "true"


@respx.mock
def test_list_pagination_hint_engine_path(configured):
    paginated = {
        "items": [ACCOUNT_RESPONSE],
        "total": 5,
        "limit": 1,
        "offset": 0,
    }
    respx.get("https://api.example.com/v1/accounts").mock(
        return_value=httpx.Response(200, json=paginated)
    )
    result = runner.invoke(cli_app, ["--no-cache", "accounts", "list"])
    assert result.exit_code == 0, result.output
    assert "showing 1 of 5" in result.output


@respx.mock
def test_list_json_mode_engine_path(configured):
    respx.get("https://api.example.com/v1/accounts").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["--no-cache", "accounts", "list", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == LIST_RESPONSE


@respx.mock
def test_get_happy_engine_path(configured):
    respx.get("https://api.example.com/v1/accounts/abc").mock(
        return_value=httpx.Response(200, json=ACCOUNT_RESPONSE)
    )
    result = runner.invoke(cli_app, ["--no-cache", "accounts", "get", "abc"])
    assert result.exit_code == 0, result.output
    assert "BCP Soles" in result.output


@respx.mock
def test_get_404_engine_path(configured):
    respx.get("https://api.example.com/v1/accounts/missing").mock(
        return_value=httpx.Response(
            404,
            json={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Account not found",
                    "fields": None,
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["--no-cache", "accounts", "get", "missing"])
    assert result.exit_code == 1
    assert "NOT_FOUND" in result.output


@respx.mock
def test_list_include_deleted_reads_live_without_no_cache(cache_populated):
    """--include-deleted rows exist only engine-side — cache mode must route live (backlog 1.4)."""
    deleted = {
        **ACCOUNT_RESPONSE,
        "id": "66666666-6666-6666-6666-666666666666",
        "name": "Closed USD",
        "deleted_at": "2026-06-01T09:00:00Z",
    }
    route = respx.get("https://api.example.com/v1/accounts").mock(
        return_value=httpx.Response(200, json=[ACCOUNT_RESPONSE, deleted])
    )
    result = runner.invoke(cli_app, ["accounts", "list", "--include-deleted"])
    assert result.exit_code == 0, result.output
    assert "Closed USD" in result.output
    assert route.calls.last.request.url.params.get("include_deleted") == "true"


def test_list_replica_path(cache_populated):
    """Default `expense accounts list` reads from the local cache."""
    with respx.mock(base_url="https://api.example.com", assert_all_called=False) as router:
        accounts_route = router.get("/v1/accounts")
        result = runner.invoke(cli_app, ["accounts", "list"])

    assert result.exit_code == 0, result.output
    assert "BCP Soles" in result.output
    assert "Cash" in result.output
    # Balance renders as grouped major units (Cash: 5000 cents → 50.00).
    assert "50.00" in result.output
    assert "Old BCP" not in result.output  # archived excluded by default
    assert "Alex" not in result.output  # people excluded by default
    assert not accounts_route.called  # engine NOT called


def test_list_replica_include_archived(cache_populated):
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(cli_app, ["accounts", "list", "--include-archived"])
    assert result.exit_code == 0, result.output
    assert "Old BCP" in result.output


def test_list_replica_include_people(cache_populated):
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(cli_app, ["accounts", "list", "--include-people"])
    assert result.exit_code == 0, result.output
    assert "Alex" in result.output


def test_list_replica_json_mode(cache_populated):
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(cli_app, ["accounts", "list", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    names = [a["name"] for a in payload]
    assert "BCP Soles" in names
    assert "Cash" in names


def test_list_replica_balance_home_cents_is_null(cache_populated):
    """Cached reads return null current_balance_home_cents (the documented drift behavior)."""
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(cli_app, ["accounts", "list", "--json"])
    payload = json.loads(result.output)
    bcp = next(a for a in payload if a["name"] == "BCP Soles")
    assert bcp["current_balance_home_cents"] is None
    assert bcp["current_balance_cents"] == 125000


def test_get_replica_path(cache_populated):
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(cli_app, ["accounts", "get", "11111111-1111-1111-1111-111111111111"])
    assert result.exit_code == 0, result.output
    assert "BCP Soles" in result.output


def test_get_replica_not_found(cache_populated):
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(cli_app, ["accounts", "get", "00000000-0000-0000-0000-000000000000"])
    assert result.exit_code == 1
    assert "NOT_FOUND" in result.output


@respx.mock
def test_list_auto_cold_start_when_cache_empty(configured):
    """First-time read triggers a cold-start and prints the stderr notice."""
    sync_route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=sync_payload(accounts=[ACCOUNT_RESPONSE]))
    )
    accounts_route = respx.get("https://api.example.com/v1/accounts")
    result = runner.invoke(cli_app, ["accounts", "list"])
    assert result.exit_code == 0, result.output
    assert sync_route.called
    assert not accounts_route.called
    assert "BCP Soles" in result.output
    assert cache_db.cache_path().exists()


@respx.mock
def test_list_no_auto_cold_start_when_cache_healthy(cache_populated):
    """A healthy cache means no /v1/sync call on subsequent reads."""
    sync_route = respx.get("https://api.example.com/v1/sync")
    result = runner.invoke(cli_app, ["accounts", "list"])
    assert result.exit_code == 0, result.output
    assert not sync_route.called


@respx.mock
def test_list_no_cache_does_not_open_cache_file(configured, tmp_path):
    respx.get("https://api.example.com/v1/accounts").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    runner.invoke(cli_app, ["--no-cache", "accounts", "list"])
    cache_file = tmp_path / "cache.sqlite3"
    assert not cache_file.exists()


def test_list_engine_url_swap_triggers_cold_start(cache_populated):
    """If config's engine_url no longer matches what the cache stored, cold-start fires."""
    conn = cache_db.connect()
    try:
        cache_state.write_identity(
            conn,
            user_id="u1",
            client_id=str(config_module.ensure_loaded().client_id),
            engine_url="https://stale.example.com",  # mismatch vs cfg
            token_fingerprint=cache_state.token_fingerprint(config_module.ensure_loaded().token),
        )
    finally:
        conn.close()

    with respx.mock(base_url="https://api.example.com") as router:
        sync_route = router.get("/v1/sync").mock(
            return_value=httpx.Response(200, json=sync_payload(accounts=[ACCOUNT_RESPONSE]))
        )
        result = runner.invoke(cli_app, ["accounts", "list"])

    assert result.exit_code == 0, result.output
    assert sync_route.called


@respx.mock
def test_create_happy(configured):
    route = respx.post("https://api.example.com/v1/accounts").mock(
        return_value=httpx.Response(201, json=ACCOUNT_RESPONSE)
    )
    result = runner.invoke(
        cli_app,
        ["accounts", "create", "--name", "BCP Soles", "--currency-code", "PEN"],
    )
    assert result.exit_code == 0, result.output
    assert "Created:" in result.output

    body = json.loads(route.calls.last.request.content)
    assert body["name"] == "BCP Soles"
    assert body["currency_code"] == "PEN"
    UUID(body["id"])


@respx.mock
def test_create_json_mode(configured):
    respx.post("https://api.example.com/v1/accounts").mock(
        return_value=httpx.Response(201, json=ACCOUNT_RESPONSE)
    )
    result = runner.invoke(
        cli_app,
        [
            "accounts",
            "create",
            "--name",
            "BCP Soles",
            "--currency-code",
            "PEN",
            "--json",
        ],
    )
    assert result.exit_code == 0
    assert json.loads(result.output) == ACCOUNT_RESPONSE
    assert "Created:" not in result.output


def test_update_no_flags_errors(configured):
    result = runner.invoke(cli_app, ["accounts", "update", "abc"])
    assert result.exit_code == 1
    assert "No fields to update" in result.output


@respx.mock
def test_update_partial_payload(configured):
    route = respx.put("https://api.example.com/v1/accounts/abc").mock(
        return_value=httpx.Response(200, json=ACCOUNT_RESPONSE)
    )
    result = runner.invoke(cli_app, ["accounts", "update", "abc", "--name", "Renamed"])
    assert result.exit_code == 0, result.output

    body = json.loads(route.calls.last.request.content)
    assert body == {"name": "Renamed"}


def test_update_currency_flag_rejected_locally(configured):
    result = runner.invoke(
        cli_app,
        ["accounts", "update", "abc", "--currency-code", "USD"],
    )
    assert result.exit_code != 0
    assert "Currency cannot be changed" in result.output


def test_delete_requires_yes_in_non_tty(configured):
    result = runner.invoke(cli_app, ["accounts", "delete", "abc"])
    assert result.exit_code == 1
    assert "non-interactive" in result.output


@respx.mock
def test_delete_happy(configured):
    deleted = {**ACCOUNT_RESPONSE, "deleted_at": "2026-04-24T10:00:00Z"}
    respx.delete("https://api.example.com/v1/accounts/abc").mock(
        return_value=httpx.Response(200, json=deleted)
    )
    result = runner.invoke(cli_app, ["accounts", "delete", "abc", "--yes"])
    assert result.exit_code == 0, result.output


@respx.mock
def test_delete_409_prints_archive_hint(configured):
    respx.delete("https://api.example.com/v1/accounts/abc").mock(
        return_value=httpx.Response(
            409,
            json={
                "error": {
                    "code": "CONFLICT",
                    "message": "Account has transactions.",
                    "fields": None,
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["accounts", "delete", "abc", "--yes"])
    assert result.exit_code == 1
    assert "archive" in result.output
    assert "CONFLICT" in result.output


@respx.mock
def test_archive_happy(configured):
    archived = {**ACCOUNT_RESPONSE, "is_archived": True}
    respx.post("https://api.example.com/v1/accounts/abc/archive").mock(
        return_value=httpx.Response(200, json=archived)
    )
    result = runner.invoke(cli_app, ["accounts", "archive", "abc", "--yes"])
    assert result.exit_code == 0, result.output
    assert "is_archived: True" in result.output


def test_archive_requires_yes_in_non_tty(configured):
    result = runner.invoke(cli_app, ["accounts", "archive", "abc"])
    assert result.exit_code == 1
    assert "non-interactive" in result.output


@respx.mock
def test_unarchive_happy(configured):
    respx.post("https://api.example.com/v1/accounts/abc/unarchive").mock(
        return_value=httpx.Response(200, json=ACCOUNT_RESPONSE)
    )
    result = runner.invoke(cli_app, ["accounts", "unarchive", "abc"])
    assert result.exit_code == 0, result.output


@respx.mock
def test_restore_happy(configured):
    respx.post("https://api.example.com/v1/accounts/abc/restore").mock(
        return_value=httpx.Response(200, json=ACCOUNT_RESPONSE)
    )
    result = runner.invoke(cli_app, ["accounts", "restore", "abc"])
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# Step 7b.3: post-write cache refresh
# ---------------------------------------------------------------------------


@respx.mock
def test_create_triggers_post_write_sync(cache_populated):
    """A successful write fires a follow-up GET /sync to refresh the replica."""
    respx.post("https://api.example.com/v1/accounts").mock(
        return_value=httpx.Response(201, json=ACCOUNT_RESPONSE)
    )
    sync_route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=sync_payload(accounts=[ACCOUNT_RESPONSE]))
    )
    result = runner.invoke(
        cli_app,
        ["accounts", "create", "--name", "BCP Soles", "--currency-code", "PEN"],
    )
    assert result.exit_code == 0, result.output
    assert sync_route.called


@respx.mock
def test_create_with_no_sync_after_skips_sync(cache_populated):
    """--no-sync-after suppresses the post-write delta sync."""
    respx.post("https://api.example.com/v1/accounts").mock(
        return_value=httpx.Response(201, json=ACCOUNT_RESPONSE)
    )
    sync_route = respx.get("https://api.example.com/v1/sync")
    result = runner.invoke(
        cli_app,
        [
            "--no-sync-after",
            "accounts",
            "create",
            "--name",
            "BCP Soles",
            "--currency-code",
            "PEN",
        ],
    )
    assert result.exit_code == 0, result.output
    assert not sync_route.called


@respx.mock
def test_post_write_sync_failure_is_non_fatal(cache_populated):
    """A 5xx on the follow-up sync prints a stderr warning and exits 0."""
    respx.post("https://api.example.com/v1/accounts").mock(
        return_value=httpx.Response(201, json=ACCOUNT_RESPONSE)
    )
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(
            500,
            json={"error": {"code": "INTERNAL", "message": "boom", "fields": None}},
        )
    )
    result = runner.invoke(
        cli_app,
        ["accounts", "create", "--name", "BCP Soles", "--currency-code", "PEN"],
    )
    assert result.exit_code == 0, result.output
    assert "Cache refresh failed after write" in result.output


@respx.mock
def test_archive_triggers_post_write_sync_via_run_toggle(cache_populated):
    """run_toggle (used by archive/unarchive/restore) refreshes the cache too."""
    respx.post("https://api.example.com/v1/accounts/abc/archive").mock(
        return_value=httpx.Response(200, json={**ACCOUNT_RESPONSE, "is_archived": True})
    )
    sync_route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=sync_payload(accounts=[ACCOUNT_RESPONSE]))
    )
    result = runner.invoke(cli_app, ["accounts", "archive", "abc", "--yes"])
    assert result.exit_code == 0, result.output
    assert sync_route.called


@respx.mock
def test_list_before_bootstrap_hints_instead_of_traceback(configured):
    """Fresh PAT + never-bootstrapped account: the cold start can't derive a
    user_id and must exit 5 with the auth-bootstrap hint, not a raw
    RuntimeError traceback (backlog 6.1b)."""
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=sync_payload(settings=None))
    )
    result = runner.invoke(cli_app, ["accounts", "list"])
    assert result.exit_code == 5, result.output
    assert "auth bootstrap" in result.output
    assert "Traceback" not in result.output
