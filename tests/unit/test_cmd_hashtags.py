import json
from uuid import UUID

import httpx
import pytest
import respx
from typer.testing import CliRunner

from expense import config as config_module
from expense.cache import db as cache_db
from expense.cache import state as cache_state
from expense.commands.hashtags_cmd import app as hashtags_app
from tests.unit.helpers import insert_hashtag, make_cli_app, sync_payload

cli_app = make_cli_app(hashtags_app, "hashtags")

runner = CliRunner()


HASHTAG_RESPONSE = {
    "id": "33333333-3333-3333-3333-333333333333",
    "user_id": "u1",
    "name": "lunch",
    "sort_order": 1,
    "is_archived": False,
    "deleted_at": None,
    "version": 1,
    "created_at": "2026-04-24T10:00:00Z",
    "updated_at": "2026-04-24T10:00:00Z",
}

LIST_RESPONSE = [HASHTAG_RESPONSE]


@pytest.fixture
def cache_populated(configured):
    cfg = config_module.ensure_loaded()
    conn = cache_db.connect()
    try:
        rows = [
            HASHTAG_RESPONSE,
            {
                "id": "44444444-4444-4444-4444-444444444444",
                "user_id": "u1",
                "name": "vacation",
                "sort_order": 2,
                "is_archived": False,
                "deleted_at": None,
                "version": 1,
            },
            {
                "id": "55555555-5555-5555-5555-555555555555",
                "user_id": "u1",
                "name": "old-tag",
                "sort_order": 99,
                "is_archived": True,
                "deleted_at": None,
                "version": 1,
            },
        ]
        for row in rows:
            insert_hashtag(conn, row)
        cache_state.write_identity(
            conn, user_id="u1", client_id=str(cfg.client_id), engine_url=cfg.engine_url
        )
        cache_state.write_token(conn, "tok-populated")
    finally:
        conn.close()
    yield


@respx.mock
def test_list_engine_path_with_no_cache(configured):
    route = respx.get("https://api.example.com/v1/hashtags").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["--no-cache", "hashtags", "list", "--include-archived"])
    assert result.exit_code == 0, result.output
    assert "lunch" in result.output

    request = route.calls.last.request
    assert request.url.params.get("include_archived") == "true"


@respx.mock
def test_list_pagination_hint_engine_path(configured):
    paginated = {
        "items": [HASHTAG_RESPONSE],
        "total": 5,
        "limit": 1,
        "offset": 0,
    }
    respx.get("https://api.example.com/v1/hashtags").mock(
        return_value=httpx.Response(200, json=paginated)
    )
    result = runner.invoke(cli_app, ["--no-cache", "hashtags", "list"])
    assert result.exit_code == 0, result.output
    assert "showing 1 of 5" in result.output


@respx.mock
def test_list_json_mode_engine_path(configured):
    respx.get("https://api.example.com/v1/hashtags").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["--no-cache", "hashtags", "list", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == LIST_RESPONSE


@respx.mock
def test_get_happy_engine_path(configured):
    respx.get("https://api.example.com/v1/hashtags/abc").mock(
        return_value=httpx.Response(200, json=HASHTAG_RESPONSE)
    )
    result = runner.invoke(cli_app, ["--no-cache", "hashtags", "get", "abc"])
    assert result.exit_code == 0, result.output
    assert "lunch" in result.output


@respx.mock
def test_get_404_engine_path(configured):
    respx.get("https://api.example.com/v1/hashtags/missing").mock(
        return_value=httpx.Response(
            404,
            json={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Hashtag not found",
                    "fields": None,
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["--no-cache", "hashtags", "get", "missing"])
    assert result.exit_code == 1
    assert "NOT_FOUND" in result.output


def test_list_replica_path(cache_populated):
    with respx.mock(base_url="https://api.example.com", assert_all_called=False) as router:
        ht_route = router.get("/v1/hashtags")
        result = runner.invoke(cli_app, ["hashtags", "list"])
    assert result.exit_code == 0, result.output
    assert "lunch" in result.output
    assert "vacation" in result.output
    assert "old-tag" not in result.output  # archived excluded
    assert not ht_route.called


def test_list_replica_include_archived(cache_populated):
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(cli_app, ["hashtags", "list", "--include-archived"])
    assert result.exit_code == 0, result.output
    assert "old-tag" in result.output


def test_get_replica_path(cache_populated):
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(cli_app, ["hashtags", "get", "33333333-3333-3333-3333-333333333333"])
    assert result.exit_code == 0, result.output
    assert "lunch" in result.output


def test_get_replica_not_found(cache_populated):
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(cli_app, ["hashtags", "get", "00000000-0000-0000-0000-000000000000"])
    assert result.exit_code == 1
    assert "NOT_FOUND" in result.output


@respx.mock
def test_list_auto_cold_start_when_cache_empty(configured):
    sync_route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=sync_payload(hashtags=[HASHTAG_RESPONSE]))
    )
    ht_route = respx.get("https://api.example.com/v1/hashtags")
    result = runner.invoke(cli_app, ["hashtags", "list"])
    assert result.exit_code == 0, result.output
    assert sync_route.called
    assert not ht_route.called
    assert "lunch" in result.output


@respx.mock
def test_create_happy(configured):
    route = respx.post("https://api.example.com/v1/hashtags").mock(
        return_value=httpx.Response(201, json=HASHTAG_RESPONSE)
    )
    result = runner.invoke(cli_app, ["hashtags", "create", "--name", "lunch"])
    assert result.exit_code == 0, result.output
    assert "Created:" in result.output

    body = json.loads(route.calls.last.request.content)
    assert body["name"] == "lunch"
    UUID(body["id"])


@respx.mock
def test_create_json_mode(configured):
    respx.post("https://api.example.com/v1/hashtags").mock(
        return_value=httpx.Response(201, json=HASHTAG_RESPONSE)
    )
    result = runner.invoke(cli_app, ["hashtags", "create", "--name", "lunch", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == HASHTAG_RESPONSE
    assert "Created:" not in result.output


def test_update_no_flags_errors(configured):
    result = runner.invoke(cli_app, ["hashtags", "update", "abc"])
    assert result.exit_code == 1
    assert "No fields to update" in result.output


@respx.mock
def test_update_partial_payload(configured):
    route = respx.put("https://api.example.com/v1/hashtags/abc").mock(
        return_value=httpx.Response(200, json=HASHTAG_RESPONSE)
    )
    result = runner.invoke(cli_app, ["hashtags", "update", "abc", "--name", "renamed"])
    assert result.exit_code == 0, result.output

    body = json.loads(route.calls.last.request.content)
    assert body == {"name": "renamed"}


def test_delete_requires_yes_in_non_tty(configured):
    result = runner.invoke(cli_app, ["hashtags", "delete", "abc"])
    assert result.exit_code == 1
    assert "non-interactive" in result.output


@respx.mock
def test_delete_happy(configured):
    deleted = {**HASHTAG_RESPONSE, "deleted_at": "2026-04-24T10:00:00Z"}
    respx.delete("https://api.example.com/v1/hashtags/abc").mock(
        return_value=httpx.Response(200, json=deleted)
    )
    result = runner.invoke(cli_app, ["hashtags", "delete", "abc", "--yes"])
    assert result.exit_code == 0, result.output


@respx.mock
def test_archive_happy(configured):
    archived = {**HASHTAG_RESPONSE, "is_archived": True}
    respx.post("https://api.example.com/v1/hashtags/abc/archive").mock(
        return_value=httpx.Response(200, json=archived)
    )
    result = runner.invoke(cli_app, ["hashtags", "archive", "abc", "--yes"])
    assert result.exit_code == 0, result.output
    assert "is_archived: True" in result.output


def test_archive_requires_yes_in_non_tty(configured):
    result = runner.invoke(cli_app, ["hashtags", "archive", "abc"])
    assert result.exit_code == 1
    assert "non-interactive" in result.output


@respx.mock
def test_unarchive_happy(configured):
    respx.post("https://api.example.com/v1/hashtags/abc/unarchive").mock(
        return_value=httpx.Response(200, json=HASHTAG_RESPONSE)
    )
    result = runner.invoke(cli_app, ["hashtags", "unarchive", "abc"])
    assert result.exit_code == 0, result.output


@respx.mock
def test_restore_happy(configured):
    respx.post("https://api.example.com/v1/hashtags/abc/restore").mock(
        return_value=httpx.Response(200, json=HASHTAG_RESPONSE)
    )
    result = runner.invoke(cli_app, ["hashtags", "restore", "abc"])
    assert result.exit_code == 0, result.output


@respx.mock
def test_create_triggers_post_write_sync(cache_populated):
    """Step 7b.3: a successful write fires a follow-up GET /sync."""
    respx.post("https://api.example.com/v1/hashtags").mock(
        return_value=httpx.Response(201, json=HASHTAG_RESPONSE)
    )
    sync_route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=sync_payload(hashtags=[HASHTAG_RESPONSE]))
    )
    result = runner.invoke(cli_app, ["hashtags", "create", "--name", "lunch"])
    assert result.exit_code == 0, result.output
    assert sync_route.called
