"""Step 9.5.11 — menu-driven Hashtags flows.

Covers the 8 hashtag verbs (list/get/create/update/archive/unarchive/
delete/restore), the no-op update guard, destructive-confirm decline paths,
the delete-cascade warning surface, and the picker filter variants
(only_archived / only_deleted / mutex guard).
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
from expense.menu.groups import hashtags as menu_hashtags

HASHTAG_RESPONSE = {
    "id": "11111111-1111-1111-1111-111111111111",
    "user_id": "u1",
    "name": "lunch",
    "sort_order": 1,
    "is_archived": False,
    "deleted_at": None,
    "version": 1,
    "created_at": "2026-04-24T10:00:00Z",
    "updated_at": "2026-04-24T10:00:00Z",
}

LIST_RESPONSE = {
    "items": [HASHTAG_RESPONSE],
    "total": 1,
    "limit": 100,
    "offset": 0,
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
    monkeypatch.setenv("EXPENSE_STATELESS", "1")
    monkeypatch.setenv("EXPENSE_NO_SYNC_AFTER", "1")
    yield


def _insert_hashtag(conn, row: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO hashtags "
        "(id, user_id, is_archived, deleted_at, sort_order, version, body) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            row["id"],
            row.get("user_id"),
            1 if row.get("is_archived") else 0,
            row.get("deleted_at"),
            row.get("sort_order"),
            row.get("version"),
            json.dumps(row),
        ),
    )


@pytest.fixture
def cache_with_mixed_hashtags(configured):
    """Active + archived + deleted hashtags in the local cache."""
    conn = cache_db.connect()
    try:
        rows = [
            {**HASHTAG_RESPONSE},
            {
                **HASHTAG_RESPONSE,
                "id": "22222222-2222-2222-2222-222222222222",
                "name": "old-trip",
                "is_archived": True,
            },
            {
                **HASHTAG_RESPONSE,
                "id": "33333333-3333-3333-3333-333333333333",
                "name": "trashed",
                "deleted_at": "2026-05-01T00:00:00Z",
            },
        ]
        for row in rows:
            _insert_hashtag(conn, row)
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
    monkeypatch.setattr(menu_hashtags.questionary, "select", script)
    monkeypatch.setattr(menu_hashtags.questionary, "text", script)
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
    route = respx.get("https://api.example.com/v1/hashtags")
    script = _PromptScript(["← Back"])
    _patch_questionary(monkeypatch, script)
    menu_hashtags.run_hashtags_menu(_make_ctx())
    assert not route.called


# --------------------------------------------------------------- 1. List


@respx.mock
def test_list_no_toggles(configured, monkeypatch, capsys):
    route = respx.get("https://api.example.com/v1/hashtags").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    script = _PromptScript(
        [
            "List hashtags",
            False,  # archived
            False,  # deleted
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_hashtags.run_hashtags_menu(_make_ctx())
    assert route.called
    request = route.calls.last.request
    assert "include_archived" not in request.url.params
    assert "include_deleted" not in request.url.params
    assert "lunch" in capsys.readouterr().out


@respx.mock
def test_list_with_archived_toggle(configured, monkeypatch):
    route = respx.get("https://api.example.com/v1/hashtags").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    script = _PromptScript(
        [
            "List hashtags",
            True,  # archived
            False,
            "",
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_hashtags.run_hashtags_menu(_make_ctx())
    request = route.calls.last.request
    assert request.url.params.get("include_archived") == "true"


@respx.mock
def test_list_with_deleted_toggle(configured, monkeypatch):
    route = respx.get("https://api.example.com/v1/hashtags").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    script = _PromptScript(
        [
            "List hashtags",
            False,
            True,  # deleted
            "",
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_hashtags.run_hashtags_menu(_make_ctx())
    request = route.calls.last.request
    assert request.url.params.get("include_deleted") == "true"


# --------------------------------------------------------------- 2. Get


@respx.mock
def test_get_happy(configured, monkeypatch, capsys):
    route = respx.get(
        "https://api.example.com/v1/hashtags/11111111-1111-1111-1111-111111111111"
    ).mock(return_value=httpx.Response(200, json=HASHTAG_RESPONSE))
    # View now dumps the recent-25 tagged transactions inline.
    respx.get("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(200, json={"items": [], "total": 0, "limit": 25, "offset": 0})
    )
    monkeypatch.setattr(prompts, "pick_hashtag", lambda **_k: HASHTAG_RESPONSE["id"])
    script = _PromptScript(
        [
            "View a hashtag",
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_hashtags.run_hashtags_menu(_make_ctx())
    assert route.called
    out = capsys.readouterr().out
    assert "lunch" in out
    assert "Recent transactions (tagged with this hashtag)" in out


@respx.mock
def test_get_back_no_http(configured, monkeypatch):
    route = respx.get("https://api.example.com/v1/hashtags/11111111-1111-1111-1111-111111111111")
    monkeypatch.setattr(prompts, "pick_hashtag", lambda **_k: prompts.BACK)
    script = _PromptScript(
        [
            "View a hashtag",
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_hashtags.run_hashtags_menu(_make_ctx())
    assert not route.called


# --------------------------------------------------------------- 3. Create


@respx.mock
def test_create_happy(configured, monkeypatch, capsys):
    route = respx.post("https://api.example.com/v1/hashtags").mock(
        return_value=httpx.Response(201, json=HASHTAG_RESPONSE)
    )
    script = _PromptScript(
        [
            "Create a hashtag",
            "lunch",  # name
            "",  # sort order (skip)
            True,  # confirm? Yes
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_hashtags.run_hashtags_menu(_make_ctx())
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body["name"] == "lunch"
    assert "sort_order" not in body
    assert "Created:" in capsys.readouterr().out


@respx.mock
def test_create_with_sort_order(configured, monkeypatch):
    route = respx.post("https://api.example.com/v1/hashtags").mock(
        return_value=httpx.Response(201, json=HASHTAG_RESPONSE)
    )
    script = _PromptScript(
        [
            "Create a hashtag",
            "lunch",  # name
            "5",  # sort order
            True,  # confirm? Yes
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_hashtags.run_hashtags_menu(_make_ctx())
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body["name"] == "lunch"
    assert body["sort_order"] == 5


@respx.mock
def test_create_declined_no_http(configured, monkeypatch):
    route = respx.post("https://api.example.com/v1/hashtags")
    script = _PromptScript(
        [
            "Create a hashtag",
            "lunch",
            "",
            False,  # confirm? No
            "",  # pause after Aborted.
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_hashtags.run_hashtags_menu(_make_ctx())
    assert not route.called


# --------------------------------------------------------------- 4. Update


@respx.mock
def test_update_no_changes_no_http(configured, monkeypatch, cache_with_mixed_hashtags, capsys):
    route = respx.put("https://api.example.com/v1/hashtags/11111111-1111-1111-1111-111111111111")
    monkeypatch.setattr(prompts, "pick_hashtag", lambda **_k: HASHTAG_RESPONSE["id"])
    script = _PromptScript(
        [
            "Update a hashtag",
            False,  # change name? No
            False,  # change sort_order? No
            "",  # pause after No changes.
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_hashtags.run_hashtags_menu(_make_ctx())
    assert not route.called
    assert "No changes." in capsys.readouterr().out


@respx.mock
def test_update_name_only(configured, monkeypatch, cache_with_mixed_hashtags):
    route = respx.put(
        "https://api.example.com/v1/hashtags/11111111-1111-1111-1111-111111111111"
    ).mock(return_value=httpx.Response(200, json=HASHTAG_RESPONSE))
    monkeypatch.setattr(prompts, "pick_hashtag", lambda **_k: HASHTAG_RESPONSE["id"])
    script = _PromptScript(
        [
            "Update a hashtag",
            True,  # change name? Yes
            "lunch-work",  # new name
            False,  # change sort_order? No
            True,  # confirm? Yes
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_hashtags.run_hashtags_menu(_make_ctx())
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body == {"name": "lunch-work"}


@respx.mock
def test_update_name_and_sort(configured, monkeypatch, cache_with_mixed_hashtags):
    route = respx.put(
        "https://api.example.com/v1/hashtags/11111111-1111-1111-1111-111111111111"
    ).mock(return_value=httpx.Response(200, json=HASHTAG_RESPONSE))
    monkeypatch.setattr(prompts, "pick_hashtag", lambda **_k: HASHTAG_RESPONSE["id"])
    script = _PromptScript(
        [
            "Update a hashtag",
            True,  # change name? Yes
            "lunch-work",  # new name
            True,  # change sort_order? Yes
            "42",  # new sort order
            True,  # confirm? Yes
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_hashtags.run_hashtags_menu(_make_ctx())
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body == {"name": "lunch-work", "sort_order": 42}


# --------------------------------------------------------------- 5. Archive


@respx.mock
def test_archive_happy(configured, monkeypatch):
    route = respx.post(
        "https://api.example.com/v1/hashtags/11111111-1111-1111-1111-111111111111/archive"
    ).mock(return_value=httpx.Response(200, json=HASHTAG_RESPONSE))
    monkeypatch.setattr(prompts, "pick_hashtag", lambda **_k: HASHTAG_RESPONSE["id"])
    monkeypatch.setattr(prompts, "confirm_destructive", lambda *a, **k: True)
    script = _PromptScript(
        [
            "Archive a hashtag",
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_hashtags.run_hashtags_menu(_make_ctx())
    assert route.called


@respx.mock
def test_archive_declined_no_http(configured, monkeypatch):
    route = respx.post(
        "https://api.example.com/v1/hashtags/11111111-1111-1111-1111-111111111111/archive"
    )
    monkeypatch.setattr(prompts, "pick_hashtag", lambda **_k: HASHTAG_RESPONSE["id"])
    monkeypatch.setattr(prompts, "confirm_destructive", lambda *a, **k: False)
    script = _PromptScript(
        [
            "Archive a hashtag",
            "",  # pause after Aborted.
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_hashtags.run_hashtags_menu(_make_ctx())
    assert not route.called


# --------------------------------------------------------------- 6. Unarchive


@respx.mock
def test_unarchive_happy(configured, monkeypatch):
    route = respx.post(
        "https://api.example.com/v1/hashtags/22222222-2222-2222-2222-222222222222/unarchive"
    ).mock(
        return_value=httpx.Response(
            200, json={**HASHTAG_RESPONSE, "id": "22222222-2222-2222-2222-222222222222"}
        )
    )
    monkeypatch.setattr(
        prompts, "pick_hashtag", lambda **_k: "22222222-2222-2222-2222-222222222222"
    )
    script = _PromptScript(
        [
            "Unarchive a hashtag",
            True,  # confirm Yes
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_hashtags.run_hashtags_menu(_make_ctx())
    assert route.called


# --------------------------------------------------------------- 7. Delete


@respx.mock
def test_delete_happy(configured, monkeypatch):
    route = respx.delete(
        "https://api.example.com/v1/hashtags/11111111-1111-1111-1111-111111111111"
    ).mock(
        return_value=httpx.Response(
            200, json={**HASHTAG_RESPONSE, "deleted_at": "2026-05-12T00:00:00Z"}
        )
    )
    monkeypatch.setattr(prompts, "pick_hashtag", lambda **_k: HASHTAG_RESPONSE["id"])
    monkeypatch.setattr(prompts, "confirm_destructive", lambda *a, **k: True)
    script = _PromptScript(
        [
            "Delete a hashtag",
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_hashtags.run_hashtags_menu(_make_ctx())
    assert route.called


@respx.mock
def test_delete_warning_mentions_cascade(configured, monkeypatch):
    """Roadmap gate criterion: delete-cascade warning must surface before submit."""
    route = respx.delete(
        "https://api.example.com/v1/hashtags/11111111-1111-1111-1111-111111111111"
    ).mock(
        return_value=httpx.Response(
            200, json={**HASHTAG_RESPONSE, "deleted_at": "2026-05-12T00:00:00Z"}
        )
    )
    monkeypatch.setattr(prompts, "pick_hashtag", lambda **_k: HASHTAG_RESPONSE["id"])

    captured: dict = {}

    def capturing_confirm(message, warning=None):
        captured["message"] = message
        captured["warning"] = warning
        return True

    monkeypatch.setattr(prompts, "confirm_destructive", capturing_confirm)
    script = _PromptScript(
        [
            "Delete a hashtag",
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_hashtags.run_hashtags_menu(_make_ctx())
    assert route.called
    assert captured["warning"] is not None
    assert "junction" in captured["warning"].lower()
    assert "restore does not" in captured["warning"].lower()


@respx.mock
def test_delete_declined_no_http(configured, monkeypatch):
    route = respx.delete("https://api.example.com/v1/hashtags/11111111-1111-1111-1111-111111111111")
    monkeypatch.setattr(prompts, "pick_hashtag", lambda **_k: HASHTAG_RESPONSE["id"])
    monkeypatch.setattr(prompts, "confirm_destructive", lambda *a, **k: False)
    script = _PromptScript(
        [
            "Delete a hashtag",
            "",  # pause after Aborted.
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_hashtags.run_hashtags_menu(_make_ctx())
    assert not route.called


# --------------------------------------------------------------- 8. Restore


@respx.mock
def test_restore_happy(configured, monkeypatch):
    route = respx.post(
        "https://api.example.com/v1/hashtags/33333333-3333-3333-3333-333333333333/restore"
    ).mock(
        return_value=httpx.Response(
            200,
            json={**HASHTAG_RESPONSE, "id": "33333333-3333-3333-3333-333333333333"},
        )
    )
    monkeypatch.setattr(
        prompts, "pick_hashtag", lambda **_k: "33333333-3333-3333-3333-333333333333"
    )
    script = _PromptScript(
        [
            "Restore a deleted hashtag",
            True,  # confirm
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_hashtags.run_hashtags_menu(_make_ctx())
    assert route.called


# --------------------------------------------------------------- pick_hashtag filters


def test_pick_hashtag_only_archived_filters(cache_with_mixed_hashtags, monkeypatch):
    captured: dict = {}

    def fake_select(items, *, prompt, resource_plural, allow_skip):
        captured["items"] = items
        return prompts.BACK

    monkeypatch.setattr(prompts, "_select_id", fake_select)
    prompts.pick_hashtag(only_archived=True)
    ids = {item["id"] for item in captured["items"]}
    assert ids == {"22222222-2222-2222-2222-222222222222"}


def test_pick_hashtag_only_deleted_filters(cache_with_mixed_hashtags, monkeypatch):
    captured: dict = {}

    def fake_select(items, *, prompt, resource_plural, allow_skip):
        captured["items"] = items
        return prompts.BACK

    monkeypatch.setattr(prompts, "_select_id", fake_select)
    prompts.pick_hashtag(only_deleted=True)
    ids = {item["id"] for item in captured["items"]}
    assert ids == {"33333333-3333-3333-3333-333333333333"}


def test_pick_hashtag_only_flags_mutex():
    with pytest.raises(ValueError):
        prompts.pick_hashtag(only_archived=True, only_deleted=True)
