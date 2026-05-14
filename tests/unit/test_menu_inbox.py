"""Step 9.5.3 — menu-driven Inbox flows.

Covers all 7 inbox verbs (add/list/get/update/delete/restore/promote)
plus the SKIP sentinel on `pick_account`/`pick_category` and the new
`pick_inbox` helper. HTTP is respx-mocked; cache reads (for pickers)
are monkeypatched directly.
"""

import json
from uuid import uuid4

import httpx
import pytest
import respx

from expense import config as config_module
from expense.menu import prompts
from expense.menu.groups import _common as menu_common
from expense.menu.groups import inbox as menu_inbox

INBOX_RESPONSE = {
    "id": "11111111-1111-1111-1111-111111111111",
    "user_id": "u_123",
    "title": "Lunch draft",
    "amount_cents": -1200,
    "date": "2026-05-10T12:00:00-05:00",
    "account_id": None,
    "category_id": None,
    "description": None,
    "cleared": None,
    "exchange_rate": None,
    "created_at": "2026-05-10T10:00:00Z",
    "updated_at": "2026-05-10T10:00:00Z",
    "version": 1,
    "deleted_at": None,
}

INBOX_LIST_RESPONSE = {
    "items": [INBOX_RESPONSE],
    "total": 1,
    "limit": 100,
    "offset": 0,
}

TRANSACTION_RESPONSE = {
    "id": "55555555-5555-5555-5555-555555555555",
    "title": "Lunch draft",
    "amount_cents": -1200,
}


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
    monkeypatch.setenv("EXPENSE_STATELESS", "1")
    monkeypatch.setenv("EXPENSE_NO_SYNC_AFTER", "1")
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
    monkeypatch.setattr(menu_inbox.questionary, "select", script)
    monkeypatch.setattr(prompts.questionary, "select", script)
    monkeypatch.setattr(prompts.questionary, "text", script)


class _StubCtx:
    def __init__(self):
        from expense.context import AppContext

        self.obj = AppContext(verbose=False, no_cache=True, no_sync_after=True)


def _make_ctx() -> _StubCtx:
    return _StubCtx()


# ----------------------------------------------------------- 1. Add


@respx.mock
def test_add_required_only_happy_path(configured, monkeypatch):
    route = respx.post("https://api.example.com/v1/inbox").mock(
        return_value=httpx.Response(201, json=INBOX_RESPONSE)
    )
    script = _PromptScript(
        [
            "Lunch draft",  # title
            "-1200",  # amount
            False,  # set additional? No
            True,  # confirm? Yes
            "",  # pause
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_inbox.run_add(_make_ctx())
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body["title"] == "Lunch draft"
    assert body["amount_cents"] == -1200
    assert "account_id" not in body
    assert "category_id" not in body
    assert "date" not in body


@respx.mock
def test_add_with_account_and_category(configured, monkeypatch):
    route = respx.post("https://api.example.com/v1/inbox").mock(
        return_value=httpx.Response(201, json=INBOX_RESPONSE)
    )
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: "acct-1")
    monkeypatch.setattr(prompts, "pick_category", lambda **_k: "cat-1")
    script = _PromptScript(
        [
            "Lunch",
            "-1200",
            True,  # set additional? Yes
            "",  # date (skip)
            "",  # description (skip)
            "unset",  # cleared (Default)
            "",  # exchange rate (skip)
            True,  # confirm
            "",  # pause
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_inbox.run_add(_make_ctx())
    body = json.loads(route.calls.last.request.content)
    assert body["account_id"] == "acct-1"
    assert body["category_id"] == "cat-1"


@respx.mock
def test_add_skips_account_via_skip_sentinel(configured, monkeypatch):
    route = respx.post("https://api.example.com/v1/inbox").mock(
        return_value=httpx.Response(201, json=INBOX_RESPONSE)
    )
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: prompts.SKIP)
    monkeypatch.setattr(prompts, "pick_category", lambda **_k: "cat-1")
    script = _PromptScript(
        [
            "Lunch",
            "-1200",
            True,  # set additional? Yes
            "",  # date
            "",  # description
            "unset",  # cleared
            "",  # exchange rate
            True,  # confirm
            "",  # pause
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_inbox.run_add(_make_ctx())
    body = json.loads(route.calls.last.request.content)
    assert "account_id" not in body  # SKIP → not in payload
    assert body["category_id"] == "cat-1"


# ----------------------------------------------------------- 2. List


@respx.mock
def test_list_filter_ready(configured, monkeypatch):
    route = respx.get("https://api.example.com/v1/inbox").mock(
        return_value=httpx.Response(200, json=INBOX_LIST_RESPONSE)
    )
    script = _PromptScript(
        [
            "ready",  # filter
            False,  # include-deleted? No
            "",  # pause
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_inbox.run_list(_make_ctx())
    assert route.called
    assert route.calls.last.request.url.params.get("ready") == "true"
    assert route.calls.last.request.url.params.get("overdue") is None


@respx.mock
def test_list_filter_overdue_with_deleted(configured, monkeypatch):
    route = respx.get("https://api.example.com/v1/inbox").mock(
        return_value=httpx.Response(200, json=INBOX_LIST_RESPONSE)
    )
    script = _PromptScript(
        [
            "overdue",
            True,  # include-deleted? Yes
            "",  # pause
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_inbox.run_list(_make_ctx())
    assert route.calls.last.request.url.params.get("overdue") == "true"
    assert route.calls.last.request.url.params.get("include_deleted") == "true"


# ----------------------------------------------------------- 3. Get


@respx.mock
def test_get_happy(configured, monkeypatch):
    route = respx.get("https://api.example.com/v1/inbox/11111111-1111-1111-1111-111111111111").mock(
        return_value=httpx.Response(200, json=INBOX_RESPONSE)
    )
    monkeypatch.setattr(prompts, "pick_inbox", lambda **_k: "11111111-1111-1111-1111-111111111111")
    script = _PromptScript([""])  # pause
    _patch_questionary(monkeypatch, script)
    menu_inbox.run_get(_make_ctx())
    assert route.called


# ----------------------------------------------------------- 4. Update


@respx.mock
def test_update_partial_change(configured, monkeypatch):
    route = respx.put("https://api.example.com/v1/inbox/11111111-1111-1111-1111-111111111111").mock(
        return_value=httpx.Response(200, json=INBOX_RESPONSE)
    )
    monkeypatch.setattr(prompts, "pick_inbox", lambda **_k: "11111111-1111-1111-1111-111111111111")
    monkeypatch.setattr(menu_inbox.queries, "get_inbox", lambda _id: INBOX_RESPONSE)
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: "acct-new")
    script = _PromptScript(
        [
            False,  # update title? No
            False,  # update amount? No
            True,  # update account? Yes
            False,  # update category? No
            False,  # update date? No
            False,  # update description? No
            False,  # update cleared? No
            False,  # update exchange rate? No
            True,  # confirm
            "",  # pause
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_inbox.run_update(_make_ctx())
    body = json.loads(route.calls.last.request.content)
    assert body == {"account_id": "acct-new"}


@respx.mock
def test_update_no_changes_no_http(configured, monkeypatch):
    route = respx.put("https://api.example.com/v1/inbox/11111111-1111-1111-1111-111111111111").mock(
        return_value=httpx.Response(200, json=INBOX_RESPONSE)
    )
    monkeypatch.setattr(prompts, "pick_inbox", lambda **_k: "11111111-1111-1111-1111-111111111111")
    monkeypatch.setattr(menu_inbox.queries, "get_inbox", lambda _id: INBOX_RESPONSE)
    # 8 declines + 1 pause-Enter after "No changes." (Step 9.5.11b).
    script = _PromptScript([False] * 8 + [""])
    _patch_questionary(monkeypatch, script)
    menu_inbox.run_update(_make_ctx())
    assert not route.called


# ----------------------------------------------------------- 5. Delete


@respx.mock
def test_delete_happy(configured, monkeypatch):
    route = respx.delete(
        "https://api.example.com/v1/inbox/11111111-1111-1111-1111-111111111111"
    ).mock(return_value=httpx.Response(200, json=INBOX_RESPONSE))
    monkeypatch.setattr(prompts, "pick_inbox", lambda **_k: "11111111-1111-1111-1111-111111111111")
    monkeypatch.setattr(prompts, "confirm_destructive", lambda *a, **k: True)
    script = _PromptScript([""])  # pause
    _patch_questionary(monkeypatch, script)
    menu_inbox.run_delete(_make_ctx())
    assert route.called


# ----------------------------------------------------------- 6. Promote


@respx.mock
def test_promote_happy(configured, monkeypatch):
    route = respx.post(
        "https://api.example.com/v1/inbox/11111111-1111-1111-1111-111111111111/promote"
    ).mock(return_value=httpx.Response(201, json=TRANSACTION_RESPONSE))
    monkeypatch.setattr(prompts, "pick_inbox", lambda **_k: "11111111-1111-1111-1111-111111111111")
    monkeypatch.setattr(prompts, "confirm_destructive", lambda *a, **k: True)
    script = _PromptScript([""])  # pause
    _patch_questionary(monkeypatch, script)
    menu_inbox.run_promote(_make_ctx())
    assert route.called


@respx.mock
def test_promote_422_does_not_kill_flow(configured, monkeypatch):
    respx.post(
        "https://api.example.com/v1/inbox/11111111-1111-1111-1111-111111111111/promote"
    ).mock(
        return_value=httpx.Response(
            422,
            json={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Inbox item not ready to promote.",
                    "fields": {"title": "Must not be empty."},
                }
            },
        )
    )
    monkeypatch.setattr(prompts, "pick_inbox", lambda **_k: "11111111-1111-1111-1111-111111111111")
    monkeypatch.setattr(prompts, "confirm_destructive", lambda *a, **k: True)
    script = _PromptScript([""])  # pause — must be reached
    _patch_questionary(monkeypatch, script)
    menu_inbox.run_promote(_make_ctx())
    # Pause prompt reached = flow returned cleanly, did not raise typer.Exit
    assert script.remaining == 0


# ----------------------------------------------------------- 7. Restore


@respx.mock
def test_restore_happy(configured, monkeypatch):
    route = respx.post(
        "https://api.example.com/v1/inbox/11111111-1111-1111-1111-111111111111/restore"
    ).mock(return_value=httpx.Response(200, json=INBOX_RESPONSE))
    monkeypatch.setattr(prompts, "pick_inbox", lambda **_k: "11111111-1111-1111-1111-111111111111")
    script = _PromptScript([""])  # pause
    _patch_questionary(monkeypatch, script)
    menu_inbox.run_restore(_make_ctx())
    assert route.called


# ----------------------------------------------------------- recap helper


def test_print_recap_bare_command_no_flags(capsys):
    menu_common.print_recap("inbox add", [])
    out = capsys.readouterr().out
    assert "About to call:" in out
    assert "expense inbox add" in out
    assert "\\" not in out  # no continuation backslash when no flags


def test_print_recap_with_bare_flag(capsys):
    menu_common.print_recap("log", [("--title", '"Coffee"'), ("--transfer", "")])
    out = capsys.readouterr().out
    assert '--title "Coffee"' in out
    assert "--transfer" in out
    # Bare flag emits without a trailing value
    lines = [line for line in out.splitlines() if "--transfer" in line]
    assert lines and lines[0].rstrip().endswith("--transfer")
