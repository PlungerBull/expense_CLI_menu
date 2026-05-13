"""Step 9.5.9 — menu-driven Accounts flows.

Covers the 8 account verbs (list/get/create/update/archive/unarchive/
delete/restore), the no-op update guard, the destructive-confirm decline
path, the 409 archive hint on delete, and the picker filter variants
(only_archived / only_deleted).
"""

import json
from uuid import uuid4

import httpx
import pytest
import respx

from expense import config as config_module
from expense.cache import db as cache_db
from expense.menu import prompts
from expense.menu.groups import _common as menu_common
from expense.menu.groups import accounts as menu_accounts

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
    monkeypatch.setenv("EXPENSE_STATELESS", "1")
    monkeypatch.setenv("EXPENSE_NO_SYNC_AFTER", "1")
    yield


def _insert_account(conn, row: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO accounts "
        "(id, user_id, is_archived, is_person, deleted_at, sort_order, version, body) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            row["id"],
            row.get("user_id"),
            1 if row.get("is_archived") else 0,
            1 if row.get("is_person") else 0,
            row.get("deleted_at"),
            row.get("sort_order"),
            row.get("version"),
            json.dumps(row),
        ),
    )


@pytest.fixture
def cache_with_mixed_accounts(configured):
    """Active + archived + deleted accounts in the local cache."""
    conn = cache_db.connect()
    try:
        rows = [
            {**ACCOUNT_RESPONSE},
            {
                **ACCOUNT_RESPONSE,
                "id": "22222222-2222-2222-2222-222222222222",
                "name": "Old BCP",
                "is_archived": True,
            },
            {
                **ACCOUNT_RESPONSE,
                "id": "33333333-3333-3333-3333-333333333333",
                "name": "Trashed",
                "is_archived": False,
                "deleted_at": "2026-05-01T00:00:00Z",
            },
        ]
        for row in rows:
            _insert_account(conn, row)
    finally:
        conn.close()
    yield


class _FakeAsk:
    def __init__(self, answer):
        self._answer = answer

    def ask(self):
        if isinstance(self._answer, BaseException):
            raise self._answer
        return self._answer


class _PromptScript:
    def __init__(self, answers: list):
        self._queue = list(answers)

    def __call__(self, *_args, **_kwargs):
        if not self._queue:
            raise AssertionError("Prompt script exhausted — unexpected questionary call.")
        return _FakeAsk(self._queue.pop(0))

    @property
    def remaining(self) -> int:
        return len(self._queue)


def _patch_questionary(monkeypatch, script: _PromptScript) -> None:
    monkeypatch.setattr(menu_common.questionary, "text", script)
    monkeypatch.setattr(menu_common.questionary, "select", script)
    monkeypatch.setattr(menu_accounts.questionary, "select", script)
    monkeypatch.setattr(menu_accounts.questionary, "text", script)
    monkeypatch.setattr(prompts.questionary, "select", script)
    monkeypatch.setattr(prompts.questionary, "text", script)


class _StubCtx:
    def __init__(self):
        from expense.context import AppContext

        self.obj = AppContext(verbose=False, no_cache=True, no_sync_after=True)


def _make_ctx() -> _StubCtx:
    return _StubCtx()


# --------------------------------------------------------------- back / abort


@respx.mock
def test_menu_back_exits(configured, monkeypatch):
    route = respx.get("https://api.example.com/v1/accounts")
    script = _PromptScript(["← Back"])
    _patch_questionary(monkeypatch, script)
    menu_accounts.run_accounts_menu(_make_ctx())
    assert not route.called


# --------------------------------------------------------------- 1. List


@respx.mock
def test_list_no_toggles(configured, monkeypatch, capsys):
    route = respx.get("https://api.example.com/v1/accounts").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    script = _PromptScript(
        [
            "List accounts",
            False,  # archived
            False,  # deleted
            False,  # people
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_accounts.run_accounts_menu(_make_ctx())
    assert route.called
    request = route.calls.last.request
    assert "include_archived" not in request.url.params
    assert "include_deleted" not in request.url.params
    assert "include_people" not in request.url.params
    assert "BCP Soles" in capsys.readouterr().out


@respx.mock
def test_list_with_archived_toggle(configured, monkeypatch):
    route = respx.get("https://api.example.com/v1/accounts").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    script = _PromptScript(
        [
            "List accounts",
            True,  # archived
            False,
            False,
            "",
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_accounts.run_accounts_menu(_make_ctx())
    request = route.calls.last.request
    assert request.url.params.get("include_archived") == "true"


# --------------------------------------------------------------- 2. Get


@respx.mock
def test_get_happy(configured, monkeypatch, capsys):
    route = respx.get(
        "https://api.example.com/v1/accounts/11111111-1111-1111-1111-111111111111"
    ).mock(return_value=httpx.Response(200, json=ACCOUNT_RESPONSE))
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: ACCOUNT_RESPONSE["id"])
    script = _PromptScript(
        [
            "View an account",
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_accounts.run_accounts_menu(_make_ctx())
    assert route.called
    out = capsys.readouterr().out
    assert "BCP Soles" in out


# --------------------------------------------------------------- 3. Create


@respx.mock
def test_create_happy(configured, monkeypatch, capsys):
    route = respx.post("https://api.example.com/v1/accounts").mock(
        return_value=httpx.Response(201, json=ACCOUNT_RESPONSE)
    )
    script = _PromptScript(
        [
            "Create an account",
            "BCP Soles",  # name
            "PEN",  # currency
            "",  # color (skip)
            "",  # sort order (skip)
            True,  # confirm? Yes
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_accounts.run_accounts_menu(_make_ctx())
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body["name"] == "BCP Soles"
    assert body["currency_code"] == "PEN"
    assert "color" not in body
    assert "sort_order" not in body
    out = capsys.readouterr().out
    assert "Created:" in out


@respx.mock
def test_create_declined_no_http(configured, monkeypatch):
    route = respx.post("https://api.example.com/v1/accounts")
    script = _PromptScript(
        [
            "Create an account",
            "BCP Soles",
            "PEN",
            "",
            "",
            False,  # confirm? No
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_accounts.run_accounts_menu(_make_ctx())
    assert not route.called


# --------------------------------------------------------------- 4. Update


@respx.mock
def test_update_no_changes_no_http(configured, monkeypatch, cache_with_mixed_accounts, capsys):
    route = respx.put("https://api.example.com/v1/accounts/11111111-1111-1111-1111-111111111111")
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: ACCOUNT_RESPONSE["id"])
    script = _PromptScript(
        [
            "Update an account",
            False,  # change name? No
            False,  # change color? No
            False,  # change sort_order? No
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_accounts.run_accounts_menu(_make_ctx())
    assert not route.called
    assert "No changes." in capsys.readouterr().out


@respx.mock
def test_update_name_only(configured, monkeypatch, cache_with_mixed_accounts):
    route = respx.put(
        "https://api.example.com/v1/accounts/11111111-1111-1111-1111-111111111111"
    ).mock(return_value=httpx.Response(200, json=ACCOUNT_RESPONSE))
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: ACCOUNT_RESPONSE["id"])
    script = _PromptScript(
        [
            "Update an account",
            True,  # change name? Yes
            "BCP Soles (joint)",  # new name
            False,  # change color? No
            False,  # change sort_order? No
            True,  # confirm? Yes
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_accounts.run_accounts_menu(_make_ctx())
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body == {"name": "BCP Soles (joint)"}


# --------------------------------------------------------------- 5. Archive


@respx.mock
def test_archive_happy(configured, monkeypatch):
    route = respx.post(
        "https://api.example.com/v1/accounts/11111111-1111-1111-1111-111111111111/archive"
    ).mock(return_value=httpx.Response(200, json=ACCOUNT_RESPONSE))
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: ACCOUNT_RESPONSE["id"])
    monkeypatch.setattr(prompts, "confirm_destructive", lambda *a, **k: True)
    script = _PromptScript(
        [
            "Archive an account",
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_accounts.run_accounts_menu(_make_ctx())
    assert route.called


@respx.mock
def test_archive_declined_no_http(configured, monkeypatch):
    route = respx.post(
        "https://api.example.com/v1/accounts/11111111-1111-1111-1111-111111111111/archive"
    )
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: ACCOUNT_RESPONSE["id"])
    monkeypatch.setattr(prompts, "confirm_destructive", lambda *a, **k: False)
    script = _PromptScript(
        [
            "Archive an account",
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_accounts.run_accounts_menu(_make_ctx())
    assert not route.called


# --------------------------------------------------------------- 6. Unarchive


@respx.mock
def test_unarchive_happy(configured, monkeypatch):
    route = respx.post(
        "https://api.example.com/v1/accounts/22222222-2222-2222-2222-222222222222/unarchive"
    ).mock(
        return_value=httpx.Response(
            200, json={**ACCOUNT_RESPONSE, "id": "22222222-2222-2222-2222-222222222222"}
        )
    )
    monkeypatch.setattr(
        prompts, "pick_account", lambda **_k: "22222222-2222-2222-2222-222222222222"
    )
    script = _PromptScript(
        [
            "Unarchive an account",
            True,  # confirm Yes
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_accounts.run_accounts_menu(_make_ctx())
    assert route.called


# --------------------------------------------------------------- 7. Delete


@respx.mock
def test_delete_happy(configured, monkeypatch):
    route = respx.delete(
        "https://api.example.com/v1/accounts/11111111-1111-1111-1111-111111111111"
    ).mock(
        return_value=httpx.Response(
            200, json={**ACCOUNT_RESPONSE, "deleted_at": "2026-05-12T00:00:00Z"}
        )
    )
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: ACCOUNT_RESPONSE["id"])
    monkeypatch.setattr(prompts, "confirm_destructive", lambda *a, **k: True)
    script = _PromptScript(
        [
            "Delete an account",
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_accounts.run_accounts_menu(_make_ctx())
    assert route.called


@respx.mock
def test_delete_409_archive_hint(configured, monkeypatch, capsys):
    route = respx.delete(
        "https://api.example.com/v1/accounts/11111111-1111-1111-1111-111111111111"
    ).mock(
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
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: ACCOUNT_RESPONSE["id"])
    monkeypatch.setattr(prompts, "confirm_destructive", lambda *a, **k: True)
    script = _PromptScript(
        [
            "Delete an account",
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_accounts.run_accounts_menu(_make_ctx())
    assert route.called
    err = capsys.readouterr().err
    assert "accounts archive" in err


# --------------------------------------------------------------- 8. Restore


@respx.mock
def test_restore_happy(configured, monkeypatch):
    route = respx.post(
        "https://api.example.com/v1/accounts/33333333-3333-3333-3333-333333333333/restore"
    ).mock(
        return_value=httpx.Response(
            200,
            json={**ACCOUNT_RESPONSE, "id": "33333333-3333-3333-3333-333333333333"},
        )
    )
    monkeypatch.setattr(
        prompts, "pick_account", lambda **_k: "33333333-3333-3333-3333-333333333333"
    )
    script = _PromptScript(
        [
            "Restore a deleted account",
            True,  # confirm
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_accounts.run_accounts_menu(_make_ctx())
    assert route.called


# --------------------------------------------------------------- pick_account filters


def test_pick_account_only_archived_filters_to_archived(cache_with_mixed_accounts, monkeypatch):
    captured: dict = {}

    def fake_select(items, *, prompt, resource_plural, allow_skip):
        captured["items"] = items
        return prompts.BACK

    monkeypatch.setattr(prompts, "_select_id", fake_select)
    prompts.pick_account(only_archived=True)
    ids = {item["id"] for item in captured["items"]}
    assert ids == {"22222222-2222-2222-2222-222222222222"}


def test_pick_account_only_deleted_filters_to_deleted(cache_with_mixed_accounts, monkeypatch):
    captured: dict = {}

    def fake_select(items, *, prompt, resource_plural, allow_skip):
        captured["items"] = items
        return prompts.BACK

    monkeypatch.setattr(prompts, "_select_id", fake_select)
    prompts.pick_account(only_deleted=True)
    ids = {item["id"] for item in captured["items"]}
    assert ids == {"33333333-3333-3333-3333-333333333333"}


def test_pick_account_only_flags_mutex():
    with pytest.raises(ValueError):
        prompts.pick_account(only_archived=True, only_deleted=True)
