import json
from uuid import UUID, uuid4

import httpx
import pytest
import respx
import typer
from typer.testing import CliRunner

from expense import config as config_module
from expense.commands.categories_cmd import app as categories_app

cli_app = typer.Typer()


@cli_app.callback()
def _root() -> None:
    pass


cli_app.add_typer(categories_app, name="categories")

runner = CliRunner()


CATEGORY_RESPONSE = {
    "id": "22222222-2222-2222-2222-222222222222",
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
    yield


@respx.mock
def test_list_happy(configured):
    route = respx.get("https://api.example.com/v1/categories").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["categories", "list", "--include-archived"])
    assert result.exit_code == 0, result.output
    assert "Food" in result.output

    request = route.calls.last.request
    assert request.url.params.get("include_archived") == "true"


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
