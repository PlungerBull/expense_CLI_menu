"""Step 9.5.14 — menu-driven Activity log flows.

Covers the three submenu entries (List all / Filter by type / Filter by
specific record) plus the interactive `Show next page?` pagination loop.
HTTP is respx-mocked; cache reads (for pickers) are monkeypatched
directly.
"""

from uuid import uuid4

import httpx
import pytest
import respx

from expense import config as config_module
from expense.menu import prompts
from expense.menu.groups import _common as menu_common
from expense.menu.groups import activity_log as menu_activity

ACTIVITY_ROW = {
    "id": "11111111-1111-1111-1111-111111111111",
    "resource_type": "expense_transactions",
    "resource_id": "22222222-2222-2222-2222-222222222222",
    "action": 1,
    "before_snapshot": None,
    "after_snapshot": None,
    "changed_by": "u1",
    "actor_type": "user",
    "created_at": "2026-05-03T10:00:00Z",
}

PAGE_50 = {
    "items": [ACTIVITY_ROW] * 50,
    "total": 312,
    "limit": 50,
    "offset": 0,
}

PAGE_50_FROM_50 = {
    "items": [ACTIVITY_ROW] * 50,
    "total": 312,
    "limit": 50,
    "offset": 50,
}

SINGLE_PAGE = {
    "items": [ACTIVITY_ROW] * 3,
    "total": 3,
    "limit": 50,
    "offset": 0,
}

EMPTY_PAGE = {
    "items": [],
    "total": 0,
    "limit": 50,
    "offset": 0,
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
    monkeypatch.setattr(menu_activity.questionary, "select", script)
    monkeypatch.setattr(prompts.questionary, "select", script)
    monkeypatch.setattr(prompts.questionary, "text", script)


class _StubCtx:
    def __init__(self):
        from expense.context import AppContext

        self.obj = AppContext(verbose=False, no_cache=True, no_sync_after=True)


def _make_ctx() -> _StubCtx:
    return _StubCtx()


# ----------------------------------------------------------- 1. List all


@respx.mock
def test_run_list_all_single_page(configured, monkeypatch):
    """One page fits everything → no `Show next page?` prompt is asked."""
    route = respx.get("https://api.example.com/v1/activity").mock(
        return_value=httpx.Response(200, json=SINGLE_PAGE)
    )
    script = _PromptScript([""])  # pause only
    _patch_questionary(monkeypatch, script)
    menu_activity.run_list_all(_make_ctx())
    assert route.call_count == 1
    # No offset on the only request.
    assert route.calls.last.request.url.params.get("offset") is None


@respx.mock
def test_run_list_all_multi_page_yes_then_no(configured, monkeypatch):
    """`Show next page?` advances offset; next answer ends the loop."""
    route = respx.get("https://api.example.com/v1/activity").mock(
        side_effect=[
            httpx.Response(200, json=PAGE_50),
            httpx.Response(200, json=PAGE_50_FROM_50),
        ]
    )
    script = _PromptScript(
        [
            True,  # Show next page? → Yes
            False,  # Show next page? → No
            "",  # pause
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_activity.run_list_all(_make_ctx())
    assert route.call_count == 2
    # Second request carries offset=50.
    assert route.calls[1].request.url.params.get("offset") == "50"


@respx.mock
def test_run_list_all_stops_at_total(configured, monkeypatch):
    """When `shown >= total`, the next-page prompt is not asked."""
    last_page = {
        "items": [ACTIVITY_ROW] * 12,
        "total": 62,
        "limit": 50,
        "offset": 50,
    }
    route = respx.get("https://api.example.com/v1/activity").mock(
        side_effect=[
            httpx.Response(200, json=PAGE_50),
            httpx.Response(200, json=last_page),
        ]
    )
    script = _PromptScript(
        [
            True,  # advance to page 2
            "",  # pause (no next-page prompt this turn)
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_activity.run_list_all(_make_ctx())
    assert route.call_count == 2
    assert script.remaining == 0  # all scripted prompts consumed exactly


@respx.mock
def test_run_list_all_empty(configured, monkeypatch):
    respx.get("https://api.example.com/v1/activity").mock(
        return_value=httpx.Response(200, json=EMPTY_PAGE)
    )
    script = _PromptScript([""])  # pause only
    _patch_questionary(monkeypatch, script)
    menu_activity.run_list_all(_make_ctx())  # no exception = pass


# ----------------------------------------------------------- 2. Filter by type


@respx.mock
def test_run_list_by_resource_type_passes_filter(configured, monkeypatch):
    route = respx.get("https://api.example.com/v1/activity").mock(
        return_value=httpx.Response(200, json=SINGLE_PAGE)
    )
    script = _PromptScript(
        [
            "expense_transactions",  # resource_type picker
            "",  # pause
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_activity.run_list_by_resource_type(_make_ctx())
    assert route.called
    assert route.calls.last.request.url.params.get("resource_type") == "expense_transactions"


def test_run_list_by_resource_type_back_returns(configured, monkeypatch):
    script = _PromptScript([menu_activity.BACK_LABEL])
    _patch_questionary(monkeypatch, script)
    menu_activity.run_list_by_resource_type(_make_ctx())  # silent return = pass


# ----------------------------------------------------------- 3. Filter by record


@respx.mock
def test_run_list_by_record_passes_both_filters(configured, monkeypatch):
    route = respx.get("https://api.example.com/v1/activity").mock(
        return_value=httpx.Response(200, json=SINGLE_PAGE)
    )
    txn_id = "22222222-2222-2222-2222-222222222222"
    monkeypatch.setattr(prompts, "pick_transaction", lambda **_k: txn_id)
    script = _PromptScript(
        [
            "expense_transactions",  # resource_type picker
            "",  # pause
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_activity.run_list_by_record(_make_ctx())
    assert route.called
    params = route.calls.last.request.url.params
    assert params.get("resource_type") == "expense_transactions"
    assert params.get("resource_id") == txn_id


def test_run_list_by_record_picker_back_returns(configured, monkeypatch):
    monkeypatch.setattr(prompts, "pick_transaction", lambda **_k: prompts.BACK)
    script = _PromptScript(["expense_transactions"])
    _patch_questionary(monkeypatch, script)
    menu_activity.run_list_by_record(_make_ctx())  # silent return = pass


def test_run_list_by_record_excludes_reconciliations(configured):
    """Reconciliations must NOT appear in the by-record picker
    (no pick_reconciliation without account context)."""
    assert "reconciliations" in menu_activity._RESOURCE_TYPES
    assert "reconciliations" not in menu_activity._RESOURCE_TYPES_WITH_PICKERS


# ----------------------------------------------------------- 4. Submenu loop


@respx.mock
def test_submenu_dispatches_list_all(configured, monkeypatch):
    """The submenu loop wires the 'List all recent activity' choice to run_list_all."""
    respx.get("https://api.example.com/v1/activity").mock(
        return_value=httpx.Response(200, json=SINGLE_PAGE)
    )
    script = _PromptScript(
        [
            "List all recent activity",  # root submenu select
            "",  # pause
            menu_activity.BACK_LABEL,  # exit loop
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_activity.run_activity_log_menu(_make_ctx())
    assert script.remaining == 0


def test_submenu_back_returns_immediately(configured, monkeypatch):
    script = _PromptScript([menu_activity.BACK_LABEL])
    _patch_questionary(monkeypatch, script)
    menu_activity.run_activity_log_menu(_make_ctx())
    assert script.remaining == 0


def test_submenu_ctrl_c_returns(configured, monkeypatch):
    script = _PromptScript([KeyboardInterrupt()])
    _patch_questionary(monkeypatch, script)
    menu_activity.run_activity_log_menu(_make_ctx())  # silent return = pass


# ----------------------------------------------------------- 5. Recap


@respx.mock
def test_recap_printed_before_call(configured, monkeypatch, capsys):
    respx.get("https://api.example.com/v1/activity").mock(
        return_value=httpx.Response(200, json=SINGLE_PAGE)
    )
    script = _PromptScript([""])  # pause
    _patch_questionary(monkeypatch, script)
    menu_activity.run_list_all(_make_ctx())
    captured = capsys.readouterr()
    assert "About to call:" in captured.out
    assert "expense activity list" in captured.out
