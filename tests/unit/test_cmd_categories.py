import json
from uuid import UUID

import httpx
import respx
from typer.testing import CliRunner

from expense.commands.categories_cmd import app as categories_app
from tests.unit.helpers import make_cli_app

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


@respx.mock
def test_list_include_archived_sends_param(configured):
    archived = {
        **CATEGORY_RESPONSE,
        "id": "44444444-4444-4444-4444-444444444444",
        "name": "Crypto",
        "is_archived": True,
    }
    route = respx.get("https://api.example.com/v1/categories").mock(
        return_value=httpx.Response(200, json=[CATEGORY_RESPONSE, archived])
    )
    result = runner.invoke(cli_app, ["categories", "list", "--include-archived"])
    assert result.exit_code == 0, result.output
    assert "Food" in result.output
    assert "Crypto" in result.output

    request = route.calls.last.request
    assert request.url.params.get("include_archived") == "true"


@respx.mock
def test_list_bare_sends_no_include_params(configured):
    """A default list asks the engine for the default scope — no include_* flags."""
    route = respx.get("https://api.example.com/v1/categories").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["categories", "list"])
    assert result.exit_code == 0, result.output
    assert "Food" in result.output

    params = route.calls.last.request.url.params
    assert params.get("include_archived") is None
    assert params.get("include_deleted") is None


@respx.mock
def test_list_deleted_column_marks_soft_deleted_rows(configured):
    deleted = {
        **CATEGORY_RESPONSE,
        "id": "66666666-6666-6666-6666-666666666666",
        "name": "Old Hobby",
        "deleted_at": "2026-05-20T12:00:00Z",
    }
    route = respx.get("https://api.example.com/v1/categories").mock(
        return_value=httpx.Response(200, json=[CATEGORY_RESPONSE, deleted])
    )
    result = runner.invoke(cli_app, ["categories", "list", "--include-deleted"])
    assert result.exit_code == 0, result.output
    assert "Deleted" in result.output

    lines = result.output.splitlines()
    live_row = next(line for line in lines if "Food" in line)
    deleted_row = next(line for line in lines if "Old Hobby" in line)
    assert live_row.rstrip().endswith("no")
    assert deleted_row.rstrip().endswith("yes")

    request = route.calls.last.request
    assert request.url.params.get("include_deleted") == "true"


@respx.mock
def test_list_pagination_hint(configured):
    paginated = {
        "items": [CATEGORY_RESPONSE],
        "total": 5,
        "limit": 1,
        "offset": 0,
    }
    respx.get("https://api.example.com/v1/categories").mock(
        return_value=httpx.Response(200, json=paginated)
    )
    result = runner.invoke(cli_app, ["categories", "list"])
    assert result.exit_code == 0, result.output
    assert "showing 1 of 5" in result.output


@respx.mock
def test_list_json_mode(configured):
    respx.get("https://api.example.com/v1/categories").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["categories", "list", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == LIST_RESPONSE


@respx.mock
def test_get_happy(configured):
    respx.get("https://api.example.com/v1/categories/abc").mock(
        return_value=httpx.Response(200, json=CATEGORY_RESPONSE)
    )
    result = runner.invoke(cli_app, ["categories", "get", "abc"])
    assert result.exit_code == 0, result.output
    assert "Food" in result.output


@respx.mock
def test_get_404(configured):
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
    result = runner.invoke(cli_app, ["categories", "get", "missing"])
    assert result.exit_code == 1
    assert "NOT_FOUND" in result.output


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
    result = runner.invoke(cli_app, ["categories", "archive", "abc"])
    assert result.exit_code == 0, result.output
    assert "is_archived: True" in result.output


@respx.mock
def test_archive_is_prompt_free(configured):
    # Archive is a reversible toggle (2026-07-11): no confirmation, no --yes —
    # it succeeds bare even in non-TTY mode (CliRunner is non-TTY), where the
    # old confirm gate used to exit 1 with a "non-interactive" error.
    archived = {**CATEGORY_RESPONSE, "is_archived": True}
    respx.post("https://api.example.com/v1/categories/abc/archive").mock(
        return_value=httpx.Response(200, json=archived)
    )
    result = runner.invoke(cli_app, ["categories", "archive", "abc"])
    assert result.exit_code == 0, result.output
    assert "non-interactive" not in result.output


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
    result = runner.invoke(cli_app, ["categories", "archive", "sys"])
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
