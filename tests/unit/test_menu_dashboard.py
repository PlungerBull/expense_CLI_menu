"""Step 9.5.5 — Dashboard view flows.

Covers both flow functions (current month, with archived panels). These are
surfaced under the Reports umbrella menu; the umbrella routing itself is
covered in test_menu_reports.py. Dashboard is engine-only (no cache), so we
stub GET /v1/dashboard directly with respx.
"""

from uuid import uuid4

import httpx
import pytest
import respx

from expense import config as config_module
from expense.menu.groups import _common as menu_common
from expense.menu.groups import dashboard as menu_dash

DASHBOARD_RESPONSE = {
    "month": {"year": 2026, "month": 5},
    "bank_accounts": [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "name": "BCP Soles",
            "currency_code": "PEN",
            "current_balance_cents": 125000,
            "current_balance_home_cents": 125000,
        }
    ],
    "people": [],
    "categories": [
        {
            "id": "33333333-3333-3333-3333-333333333333",
            "name": "Food",
            "spent_cents": -50000,
            "spent_home_cents": -50000,
            "hashtag_breakdown": [],
        }
    ],
    "totals": {
        "inflow_cents": 0,
        "inflow_home_cents": 0,
        "outflow_cents": 50000,
        "outflow_home_cents": 50000,
        "net_cents": -50000,
        "net_home_cents": -50000,
    },
    "archived_accounts": None,
    "archived_categories": None,
    "archived_hashtags": None,
}

DASHBOARD_WITH_ARCHIVED = {
    **DASHBOARD_RESPONSE,
    "archived_accounts": [
        {
            "id": "44444444-4444-4444-4444-444444444444",
            "name": "Old BCP",
            "currency_code": "PEN",
            "current_balance_cents": 0,
            "current_balance_home_cents": 0,
        }
    ],
    "archived_categories": [
        {
            "id": "55555555-5555-5555-5555-555555555555",
            "name": "Crypto",
            "lifetime_spent_cents": -250000,
            "lifetime_spent_home_cents": -250000,
        }
    ],
    "archived_hashtags": [
        {
            "id": "66666666-6666-6666-6666-666666666666",
            "name": "#vacation-2024",
            "lifetime_spent_cents": -480000,
            "lifetime_spent_home_cents": -480000,
        }
    ],
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
    # The flow functions only prompt via common.pause(); patch that surface.
    monkeypatch.setattr(menu_common.questionary, "text", script)
    monkeypatch.setattr(menu_common.questionary, "select", script)


class _StubCtx:
    def __init__(self):
        from expense.context import AppContext

        self.obj = AppContext(verbose=False, no_cache=True, no_sync_after=True)


def _make_ctx() -> _StubCtx:
    return _StubCtx()


@respx.mock
def test_current_month_renders(configured, monkeypatch, capsys):
    route = respx.get("https://api.example.com/v1/dashboard").mock(
        return_value=httpx.Response(200, json=DASHBOARD_RESPONSE)
    )
    script = _PromptScript([""])  # pause
    _patch_questionary(monkeypatch, script)
    menu_dash.run_current_month(_make_ctx())
    assert route.called
    request = route.calls.last.request
    assert "include_archived" not in request.url.params
    out = capsys.readouterr().out
    assert "Month: 2026-05" in out
    # Tabular accounts: Name and Currency are separate columns now, not "Name (CUR)".
    assert "BCP Soles" in out
    assert "PEN" in out
    assert "Archived accounts" not in out


@respx.mock
def test_with_archived_renders(configured, monkeypatch, capsys):
    route = respx.get("https://api.example.com/v1/dashboard").mock(
        return_value=httpx.Response(200, json=DASHBOARD_WITH_ARCHIVED)
    )
    script = _PromptScript([""])  # pause
    _patch_questionary(monkeypatch, script)
    menu_dash.run_with_archived(_make_ctx())
    assert route.called
    request = route.calls.last.request
    assert request.url.params.get("include_archived") == "true"
    out = capsys.readouterr().out
    assert "Archived accounts:" in out
    assert "Old BCP" in out
    assert "Archived categories:" in out
    assert "Crypto" in out
    assert "Archived hashtags:" in out
    assert "#vacation-2024" in out
