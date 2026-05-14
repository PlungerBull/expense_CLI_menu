"""Step 9.5.2 — menu-driven Log a transaction.

Drives `run_log_flow` end-to-end with monkeypatched prompts and an
`respx`-mocked engine. Verifies payload shape on POST /v1/transactions
for each path (short, long, transfer, aborted, picker-back, engine-422).
"""

import json
from uuid import uuid4

import httpx
import pytest
import respx

from expense import config as config_module
from expense.menu import prompts
from expense.menu.groups import _common as menu_common
from expense.menu.groups import log as menu_log

TRANSACTION_RESPONSE = {
    "id": "55555555-5555-5555-5555-555555555555",
    "user_id": "u_123",
    "title": "Coffee",
    "amount_cents": -450,
    "amount_home_cents": -450,
    "date": "2026-05-09T12:00:00-05:00",
    "account_id": "acct-id",
    "category_id": "cat-id",
    "description": None,
    "cleared": False,
    "exchange_rate": 1.0,
    "transaction_type": 1,
    "transfer_transaction_id": None,
    "hashtag_ids": [],
    "inbox_id": None,
    "reconciliation_id": None,
    "created_at": "2026-05-09T10:00:00Z",
    "updated_at": "2026-05-09T10:00:00Z",
    "version": 1,
    "deleted_at": None,
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
    """Replays a fixed sequence of answers across questionary calls."""

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
    """Patch every questionary entry point the flow uses to share one script."""
    monkeypatch.setattr(menu_common.questionary, "text", script)
    monkeypatch.setattr(menu_common.questionary, "select", script)
    monkeypatch.setattr(prompts.questionary, "select", script)
    monkeypatch.setattr(prompts.questionary, "text", script)


def _patch_pickers(monkeypatch, account_id: str, category_id: str) -> None:
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: account_id)
    monkeypatch.setattr(prompts, "pick_category", lambda **_k: category_id)


class _StubCtx:
    """Quacks like typer.Context for `get_verbose`/`get_no_cache`/`get_no_sync_after`."""

    def __init__(self):
        from expense.context import AppContext

        self.obj = AppContext(verbose=False, no_cache=True, no_sync_after=True)


def _make_ctx() -> _StubCtx:
    return _StubCtx()


# ----------------------------------------------------------- happy paths


@respx.mock
def test_required_only_happy_path(configured, monkeypatch):
    route = respx.post("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(201, json=TRANSACTION_RESPONSE)
    )
    _patch_pickers(monkeypatch, "acct-id", "cat-id")
    script = _PromptScript(
        [
            "Coffee at Starbucks",  # title text
            "-450",  # amount text
            False,  # set optional? No
            True,  # confirm? Yes
            "",  # pause press-enter
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_log.run_log_flow(_make_ctx())
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body["title"] == "Coffee at Starbucks"
    assert body["amount_cents"] == -450
    assert body["account_id"] == "acct-id"
    assert body["category_id"] == "cat-id"
    assert "description" not in body
    assert "cleared" not in body
    assert "exchange_rate" not in body
    assert "transfer" not in body


@respx.mock
def test_long_path_all_optional_fields(configured, monkeypatch):
    route = respx.post("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(201, json=TRANSACTION_RESPONSE)
    )
    _patch_pickers(monkeypatch, "acct-id", "cat-id")
    script = _PromptScript(
        [
            "Coffee",
            "-450",
            True,  # set optional? Yes
            "2026-04-25",  # date
            "Morning coffee",  # description
            True,  # cleared = Yes
            "3.75",  # exchange rate
            False,  # transfer? No
            True,  # confirm
            "",  # pause
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_log.run_log_flow(_make_ctx())
    body = json.loads(route.calls.last.request.content)
    assert body["title"] == "Coffee"
    assert body["amount_cents"] == -450
    assert body["description"] == "Morning coffee"
    assert body["cleared"] is True
    assert body["exchange_rate"] == 3.75
    # Date normalized to RFC 3339 with local offset
    assert body["date"].startswith("2026-04-25")
    assert "+" in body["date"] or body["date"].endswith("Z") or "-" in body["date"][10:]


@respx.mock
def test_transfer_pair_path(configured, monkeypatch):
    route = respx.post("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(201, json=TRANSACTION_RESPONSE)
    )
    # First pick_account → source; second pick_account → destination.
    account_iter = iter(["acct-src", "acct-dst"])
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: next(account_iter))
    monkeypatch.setattr(prompts, "pick_category", lambda **_k: "cat-id")
    script = _PromptScript(
        [
            "Move money",
            "-100",  # source amount
            True,  # optional? Yes
            "",  # date → default
            "",  # description → skip
            "unset",  # cleared default
            "",  # exchange rate skip
            True,  # transfer? Yes
            "100",  # to-amount (opposite sign)
            True,  # confirm
            "",  # pause
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_log.run_log_flow(_make_ctx())
    body = json.loads(route.calls.last.request.content)
    assert body["amount_cents"] == -100
    assert "transfer" in body
    assert body["transfer"]["account_id"] == "acct-dst"
    assert body["transfer"]["amount_cents"] == 100


@respx.mock
def test_hashtags_attached_at_create(configured, monkeypatch):
    """Cache has hashtags → picker fires → selected ids land in the POST body."""
    route = respx.post("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(201, json=TRANSACTION_RESPONSE)
    )
    _patch_pickers(monkeypatch, "acct-id", "cat-id")
    # Pretend the cache has at least one hashtag so the picker is offered.
    monkeypatch.setattr(menu_log, "_cache_has_active_hashtags", lambda: True)
    # Picker returns two hashtag ids (multi-select checkbox result).
    monkeypatch.setattr(prompts, "pick_hashtag", lambda **_k: ["tag-aaa", "tag-bbb"])
    script = _PromptScript(
        [
            "Lunch",
            "-1500",
            False,  # optional? No
            True,  # confirm
            "",  # pause
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_log.run_log_flow(_make_ctx())
    body = json.loads(route.calls.last.request.content)
    assert body["hashtag_ids"] == ["tag-aaa", "tag-bbb"]


@respx.mock
def test_hashtag_picker_skipped_when_cache_empty(configured, monkeypatch):
    """No hashtags in cache → no picker prompt at all, no hashtag_ids in POST."""
    route = respx.post("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(201, json=TRANSACTION_RESPONSE)
    )
    _patch_pickers(monkeypatch, "acct-id", "cat-id")
    monkeypatch.setattr(menu_log, "_cache_has_active_hashtags", lambda: False)

    picker_calls = {"n": 0}

    def _picker_should_not_fire(**_k):
        picker_calls["n"] += 1
        return []

    monkeypatch.setattr(prompts, "pick_hashtag", _picker_should_not_fire)
    script = _PromptScript(
        [
            "Coffee",
            "-450",
            False,  # optional? No
            True,  # confirm
            "",  # pause
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_log.run_log_flow(_make_ctx())

    assert picker_calls["n"] == 0
    body = json.loads(route.calls.last.request.content)
    assert "hashtag_ids" not in body


# ----------------------------------------------------------- bail paths


@respx.mock
def test_user_aborts_at_confirm(configured, monkeypatch):
    route = respx.post("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(201, json=TRANSACTION_RESPONSE)
    )
    _patch_pickers(monkeypatch, "acct-id", "cat-id")
    script = _PromptScript(
        [
            "Coffee",
            "-450",
            False,  # optional? No
            False,  # confirm? No
            "",  # pause after Aborted.
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_log.run_log_flow(_make_ctx())
    assert not route.called


def test_account_picker_back_short_circuits(monkeypatch):
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: prompts.BACK)
    script = _PromptScript(
        [
            "Coffee",  # title
            "-450",  # amount
        ]
    )
    _patch_questionary(monkeypatch, script)
    # Should return without raising and without consuming further script answers.
    menu_log.run_log_flow(_make_ctx())
    assert script.remaining == 0


def test_category_picker_back_short_circuits(monkeypatch):
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: "acct-id")
    monkeypatch.setattr(prompts, "pick_category", lambda **_k: prompts.BACK)
    script = _PromptScript(
        [
            "Coffee",
            "-450",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_log.run_log_flow(_make_ctx())
    assert script.remaining == 0


# ----------------------------------------------------------- engine 422


@respx.mock
def test_engine_422_does_not_kill_flow(configured, monkeypatch):
    respx.post("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(
            422,
            json={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid category_id.",
                    "fields": {"category_id": "Invalid IDs: cat-id"},
                }
            },
        )
    )
    _patch_pickers(monkeypatch, "acct-id", "cat-id")
    script = _PromptScript(
        [
            "Coffee",
            "-450",
            False,
            True,  # confirm
            "",  # pause press-enter
        ]
    )
    _patch_questionary(monkeypatch, script)
    # Must NOT raise typer.Exit out of the flow — caught internally.
    menu_log.run_log_flow(_make_ctx())
    # Script fully consumed → control reached the pause and returned cleanly.
    assert script.remaining == 0


# ----------------------------------------------------------- recap output


def test_recap_renders_expected_lines(capsys):
    args = {
        "title": "Coffee",
        "amount": -450,
        "account_id": "acct-id",
        "category_id": "cat-id",
        "date": "2026-04-25T00:00:00-05:00",
        "description": "morning",
        "cleared": True,
        "exchange_rate": 3.75,
        "transfer": True,
        "to_account_id": "acct-dst",
        "to_amount": 450,
    }
    menu_log._print_recap(args)
    captured = capsys.readouterr().out
    assert "expense log \\" in captured
    assert '--title "Coffee"' in captured
    assert "--amount -450" in captured
    assert "--account-id acct-id" in captured
    assert "--category-id cat-id" in captured
    assert "--cleared" in captured
    assert "--exchange-rate 3.75" in captured
    assert "--transfer" in captured
    assert "--to-account-id acct-dst" in captured
    assert "--to-amount 450" in captured
