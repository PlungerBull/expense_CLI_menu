import json
from uuid import UUID

import httpx
import respx
from typer.testing import CliRunner

from expense.commands.hashtags_cmd import app as hashtags_app
from tests.unit.helpers import make_cli_app

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


@respx.mock
def test_list_include_archived_sends_param(configured):
    archived = {
        **HASHTAG_RESPONSE,
        "id": "55555555-5555-5555-5555-555555555555",
        "name": "old-tag",
        "is_archived": True,
    }
    route = respx.get("https://api.example.com/v1/hashtags").mock(
        return_value=httpx.Response(200, json=[HASHTAG_RESPONSE, archived])
    )
    result = runner.invoke(cli_app, ["hashtags", "list", "--include-archived"])
    assert result.exit_code == 0, result.output
    assert "lunch" in result.output
    assert "old-tag" in result.output

    request = route.calls.last.request
    assert request.url.params.get("include_archived") == "true"


@respx.mock
def test_list_bare_sends_no_include_params(configured):
    """A default list asks the engine for the default scope — no include_* flags."""
    route = respx.get("https://api.example.com/v1/hashtags").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["hashtags", "list"])
    assert result.exit_code == 0, result.output
    assert "lunch" in result.output

    params = route.calls.last.request.url.params
    assert params.get("include_archived") is None
    assert params.get("include_deleted") is None


@respx.mock
def test_list_include_deleted_sends_param(configured):
    deleted = {
        **HASHTAG_RESPONSE,
        "id": "99999999-9999-9999-9999-999999999999",
        "name": "retired-tag",
        "deleted_at": "2026-06-01T09:00:00Z",
    }
    route = respx.get("https://api.example.com/v1/hashtags").mock(
        return_value=httpx.Response(200, json=[HASHTAG_RESPONSE, deleted])
    )
    result = runner.invoke(cli_app, ["hashtags", "list", "--include-deleted"])
    assert result.exit_code == 0, result.output
    assert "retired-tag" in result.output
    assert route.calls.last.request.url.params.get("include_deleted") == "true"


@respx.mock
def test_list_pagination_hint(configured):
    paginated = {
        "items": [HASHTAG_RESPONSE],
        "total": 5,
        "limit": 1,
        "offset": 0,
    }
    respx.get("https://api.example.com/v1/hashtags").mock(
        return_value=httpx.Response(200, json=paginated)
    )
    result = runner.invoke(cli_app, ["hashtags", "list"])
    assert result.exit_code == 0, result.output
    assert "showing 1 of 5" in result.output


@respx.mock
def test_list_json_mode(configured):
    respx.get("https://api.example.com/v1/hashtags").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["hashtags", "list", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == LIST_RESPONSE


@respx.mock
def test_get_happy(configured):
    respx.get("https://api.example.com/v1/hashtags/abc").mock(
        return_value=httpx.Response(200, json=HASHTAG_RESPONSE)
    )
    result = runner.invoke(cli_app, ["hashtags", "get", "abc"])
    assert result.exit_code == 0, result.output
    assert "lunch" in result.output


@respx.mock
def test_get_404(configured):
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
    result = runner.invoke(cli_app, ["hashtags", "get", "missing"])
    assert result.exit_code == 1
    assert "NOT_FOUND" in result.output


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
    result = runner.invoke(cli_app, ["hashtags", "archive", "abc"])
    assert result.exit_code == 0, result.output
    assert "is_archived: True" in result.output


@respx.mock
def test_archive_is_prompt_free(configured):
    # Archive is a reversible toggle (2026-07-11): no confirmation, no --yes —
    # it succeeds bare even in non-TTY mode (CliRunner is non-TTY), where the
    # old confirm gate used to exit 1 with a "non-interactive" error.
    archived = {**HASHTAG_RESPONSE, "is_archived": True}
    respx.post("https://api.example.com/v1/hashtags/abc/archive").mock(
        return_value=httpx.Response(200, json=archived)
    )
    result = runner.invoke(cli_app, ["hashtags", "archive", "abc"])
    assert result.exit_code == 0, result.output
    assert "non-interactive" not in result.output


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
