import json
from uuid import UUID

import httpx
import pytest
import respx
from typer.testing import CliRunner

from expense import config as config_module
from expense.cache import db as cache_db
from expense.cache import state as cache_state
from expense.commands.categories_cmd import app as categories_app
from tests.unit.helpers import insert_category, make_cli_app, sync_payload

cli_app = make_cli_app(categories_app, "categories")

runner = CliRunner()


CATEGORY_RESPONSE = {
    "id": "22222222-2222-2222-2222-222222222222",
    "user_id": "u1",
    "name": "Food",
    "color": "#00FF00",
    "sort_order": 1,
    "is_system": False,
    "system_key": None,
    "is_archived": False,
    "deleted_at": None,
    "version": 1,
    "created_at": "2026-04-24T10:00:00Z",
    "updated_at": "2026-04-24T10:00:00Z",
}

LIST_RESPONSE = [CATEGORY_RESPONSE]


@pytest.fixture
def cache_populated(configured):
    cfg = config_module.ensure_loaded()
    conn = cache_db.connect()
    try:
        rows = [
            CATEGORY_RESPONSE,
            {
                "id": "33333333-3333-3333-3333-333333333333",
                "user_id": "u1",
                "name": "Transport",
                "color": "#0000FF",
                "sort_order": 2,
                "is_system": False,
                "is_archived": False,
                "deleted_at": None,
                "version": 1,
            },
            {
                "id": "44444444-4444-4444-4444-444444444444",
                "user_id": "u1",
                "name": "Crypto",
                "color": "#FFA500",
                "sort_order": 99,
                "is_system": False,
                "is_archived": True,
                "deleted_at": None,
                "version": 1,
            },
        ]
        for row in rows:
            insert_category(conn, row)
        cache_state.write_identity(
            conn, user_id="u1", client_id=str(cfg.client_id), engine_url=cfg.engine_url
        )
        cache_state.write_token(conn, "tok-populated")
    finally:
        conn.close()
    yield


@respx.mock
def test_list_engine_path_with_no_cache(configured):
    route = respx.get("https://api.example.com/v1/categories").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["--no-cache", "categories", "list", "--include-archived"])
    assert result.exit_code == 0, result.output
    assert "Food" in result.output

    request = route.calls.last.request
    assert request.url.params.get("include_archived") == "true"


@respx.mock
def test_list_pagination_hint_engine_path(configured):
    paginated = {
        "items": [CATEGORY_RESPONSE],
        "total": 5,
        "limit": 1,
        "offset": 0,
    }
    respx.get("https://api.example.com/v1/categories").mock(
        return_value=httpx.Response(200, json=paginated)
    )
    result = runner.invoke(cli_app, ["--no-cache", "categories", "list"])
    assert result.exit_code == 0, result.output
    assert "showing 1 of 5" in result.output


@respx.mock
def test_list_json_mode_engine_path(configured):
    respx.get("https://api.example.com/v1/categories").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["--no-cache", "categories", "list", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == LIST_RESPONSE


@respx.mock
def test_get_happy_engine_path(configured):
    respx.get("https://api.example.com/v1/categories/abc").mock(
        return_value=httpx.Response(200, json=CATEGORY_RESPONSE)
    )
    result = runner.invoke(cli_app, ["--no-cache", "categories", "get", "abc"])
    assert result.exit_code == 0, result.output
    assert "Food" in result.output


@respx.mock
def test_get_404_engine_path(configured):
    respx.get("https://api.example.com/v1/categories/missing").mock(
        return_value=httpx.Response(
            404,
            json={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Category not found",
                    "fields": None,
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["--no-cache", "categories", "get", "missing"])
    assert result.exit_code == 1
    assert "NOT_FOUND" in result.output


def test_list_replica_path(cache_populated):
    with respx.mock(base_url="https://api.example.com", assert_all_called=False) as router:
        cat_route = router.get("/v1/categories")
        result = runner.invoke(cli_app, ["categories", "list"])
    assert result.exit_code == 0, result.output
    assert "Food" in result.output
    assert "Transport" in result.output
    assert "Crypto" not in result.output  # archived excluded
    assert not cat_route.called


def test_list_replica_include_archived(cache_populated):
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(cli_app, ["categories", "list", "--include-archived"])
    assert result.exit_code == 0, result.output
    assert "Crypto" in result.output


def test_list_replica_paginated_shape(cache_populated):
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(cli_app, ["categories", "list", "--limit", "1", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["total"] == 2  # only 2 active (Crypto archived)
    assert payload["limit"] == 1
    assert payload["offset"] == 0
    assert len(payload["items"]) == 1


def test_get_replica_path(cache_populated):
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(
            cli_app, ["categories", "get", "22222222-2222-2222-2222-222222222222"]
        )
    assert result.exit_code == 0, result.output
    assert "Food" in result.output


def test_get_replica_not_found(cache_populated):
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(
            cli_app, ["categories", "get", "00000000-0000-0000-0000-000000000000"]
        )
    assert result.exit_code == 1
    assert "NOT_FOUND" in result.output


@respx.mock
def test_list_auto_cold_start_when_cache_empty(configured):
    sync_route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=sync_payload(categories=[CATEGORY_RESPONSE]))
    )
    cat_route = respx.get("https://api.example.com/v1/categories")
    result = runner.invoke(cli_app, ["categories", "list"])
    assert result.exit_code == 0, result.output
    assert sync_route.called
    assert not cat_route.called
    assert "Food" in result.output


@respx.mock
def test_create_happy(configured):
    route = respx.post("https://api.example.com/v1/categories").mock(
        return_value=httpx.Response(201, json=CATEGORY_RESPONSE)
    )
    result = runner.invoke(
        cli_app,
        ["categories", "create", "--name", "Food", "--color", "#00FF00"],
    )
    assert result.exit_code == 0, result.output
    assert "Created:" in result.output

    body = json.loads(route.calls.last.request.content)
    assert body["name"] == "Food"
    assert body["color"] == "#00FF00"
    UUID(body["id"])


@respx.mock
def test_create_json_mode(configured):
    respx.post("https://api.example.com/v1/categories").mock(
        return_value=httpx.Response(201, json=CATEGORY_RESPONSE)
    )
    result = runner.invoke(
        cli_app,
        [
            "categories",
            "create",
            "--name",
            "Food",
            "--color",
            "#00FF00",
            "--json",
        ],
    )
    assert result.exit_code == 0
    assert json.loads(result.output) == CATEGORY_RESPONSE
    assert "Created:" not in result.output


def test_update_no_flags_errors(configured):
    result = runner.invoke(cli_app, ["categories", "update", "abc"])
    assert result.exit_code == 1
    assert "No fields to update" in result.output


@respx.mock
def test_update_partial_payload(configured):
    route = respx.put("https://api.example.com/v1/categories/abc").mock(
        return_value=httpx.Response(200, json=CATEGORY_RESPONSE)
    )
    result = runner.invoke(cli_app, ["categories", "update", "abc", "--name", "Renamed"])
    assert result.exit_code == 0, result.output

    body = json.loads(route.calls.last.request.content)
    assert body == {"name": "Renamed"}


def test_delete_requires_yes_in_non_tty(configured):
    result = runner.invoke(cli_app, ["categories", "delete", "abc"])
    assert result.exit_code == 1
    assert "non-interactive" in result.output


@respx.mock
def test_delete_happy(configured):
    deleted = {**CATEGORY_RESPONSE, "deleted_at": "2026-04-24T10:00:00Z"}
    respx.delete("https://api.example.com/v1/categories/abc").mock(
        return_value=httpx.Response(200, json=deleted)
    )
    result = runner.invoke(cli_app, ["categories", "delete", "abc", "--yes"])
    assert result.exit_code == 0, result.output


@respx.mock
def test_delete_403_prints_system_hint(configured):
    respx.delete("https://api.example.com/v1/categories/sys").mock(
        return_value=httpx.Response(
            403,
            json={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "System category cannot be modified.",
                    "fields": None,
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["categories", "delete", "sys", "--yes"])
    assert result.exit_code == 1
    assert "System categories" in result.output
    assert "FORBIDDEN" in result.output


@respx.mock
def test_archive_happy(configured):
    archived = {**CATEGORY_RESPONSE, "is_archived": True}
    respx.post("https://api.example.com/v1/categories/abc/archive").mock(
        return_value=httpx.Response(200, json=archived)
    )
    result = runner.invoke(cli_app, ["categories", "archive", "abc", "--yes"])
    assert result.exit_code == 0, result.output
    assert "is_archived: True" in result.output


def test_archive_requires_yes_in_non_tty(configured):
    result = runner.invoke(cli_app, ["categories", "archive", "abc"])
    assert result.exit_code == 1
    assert "non-interactive" in result.output


@respx.mock
def test_archive_403_prints_system_hint(configured):
    respx.post("https://api.example.com/v1/categories/sys/archive").mock(
        return_value=httpx.Response(
            403,
            json={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "System category cannot be archived.",
                    "fields": None,
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["categories", "archive", "sys", "--yes"])
    assert result.exit_code == 1
    assert "System categories" in result.output


@respx.mock
def test_unarchive_happy(configured):
    respx.post("https://api.example.com/v1/categories/abc/unarchive").mock(
        return_value=httpx.Response(200, json=CATEGORY_RESPONSE)
    )
    result = runner.invoke(cli_app, ["categories", "unarchive", "abc"])
    assert result.exit_code == 0, result.output


@respx.mock
def test_restore_happy(configured):
    respx.post("https://api.example.com/v1/categories/abc/restore").mock(
        return_value=httpx.Response(200, json=CATEGORY_RESPONSE)
    )
    result = runner.invoke(cli_app, ["categories", "restore", "abc"])
    assert result.exit_code == 0, result.output


@respx.mock
def test_restore_409_prints_name_hint(configured):
    respx.post("https://api.example.com/v1/categories/abc/restore").mock(
        return_value=httpx.Response(
            409,
            json={
                "error": {
                    "code": "CONFLICT",
                    "message": "An active category with this name already exists.",
                    "fields": None,
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["categories", "restore", "abc"])
    assert result.exit_code == 1
    assert "Rename the existing one first" in result.output
    assert "CONFLICT" in result.output


@respx.mock
def test_create_triggers_post_write_sync(cache_populated):
    """Step 7b.3: a successful write fires a follow-up GET /sync."""
    respx.post("https://api.example.com/v1/categories").mock(
        return_value=httpx.Response(201, json=CATEGORY_RESPONSE)
    )
    sync_route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=sync_payload(categories=[CATEGORY_RESPONSE]))
    )
    result = runner.invoke(
        cli_app,
        ["categories", "create", "--name", "Food", "--color", "#FF0000"],
    )
    assert result.exit_code == 0, result.output
    assert sync_route.called
