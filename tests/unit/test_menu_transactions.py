"""Step 9.5.4 — menu-driven Transactions flows.

Covers list/get/update/delete/restore/batch + the new date-preset filter,
pick_transaction picker, and the hashtags-on-edit flow enabled by engine A+.
"""

import json
from uuid import uuid4

import httpx
import pytest
import respx

from expense import config as config_module
from expense.menu import prompts
from expense.menu.groups import _common as menu_common
from expense.menu.groups import transactions as menu_tx

TRANSACTION_RESPONSE = {
    "id": "55555555-5555-5555-5555-555555555555",
    "user_id": "u_123",
    "title": "Coffee",
    "amount_cents": -450,
    "amount_home_cents": -450,
    "date": "2026-05-09T12:00:00-05:00",
    "account_id": "acct-1",
    "category_id": "cat-1",
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

TRANSACTION_WITH_HASHTAGS = {
    **TRANSACTION_RESPONSE,
    "hashtag_ids": ["hashtag-a"],
}

LIST_RESPONSE = {
    "items": [TRANSACTION_RESPONSE],
    "total": 1,
    "limit": 100,
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
    monkeypatch.setattr(menu_tx.questionary, "select", script)
    monkeypatch.setattr(menu_tx.questionary, "text", script)
    monkeypatch.setattr(prompts.questionary, "select", script)
    monkeypatch.setattr(prompts.questionary, "text", script)


class _StubCtx:
    def __init__(self):
        from expense.context import AppContext

        self.obj = AppContext(verbose=False, no_cache=True, no_sync_after=True)


def _make_ctx() -> _StubCtx:
    return _StubCtx()


# ----------------------------------------------------------- 1. List


@respx.mock
def test_list_no_filters(configured, monkeypatch):
    route = respx.get("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: prompts.SKIP)
    monkeypatch.setattr(prompts, "pick_category", lambda **_k: prompts.SKIP)
    monkeypatch.setattr(prompts, "pick_hashtag", lambda **_k: prompts.SKIP)
    script = _PromptScript(
        [
            "Any date",  # date range
            "",  # search (skip)
            "any",  # cleared
            False,  # include-deleted
            "",  # page size default
            "",  # pause
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_tx.run_list(_make_ctx())
    assert route.called
    params = route.calls.last.request.url.params
    assert params.get("account_id") is None
    assert params.get("category_id") is None
    assert params.get("date_from") is None


@respx.mock
def test_list_account_filter(configured, monkeypatch):
    route = respx.get("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: "acct-pick")
    monkeypatch.setattr(prompts, "pick_category", lambda **_k: prompts.SKIP)
    monkeypatch.setattr(prompts, "pick_hashtag", lambda **_k: prompts.SKIP)
    monkeypatch.setattr(prompts, "pick_reconciliation", lambda **_k: prompts.BACK)
    script = _PromptScript(
        [
            "Any date",
            "",
            "any",
            False,
            "",
            "",  # pause
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_tx.run_list(_make_ctx())
    assert route.calls.last.request.url.params.get("account_id") == "acct-pick"


@respx.mock
def test_list_date_preset_last_30_days(configured, monkeypatch):
    route = respx.get("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: prompts.SKIP)
    monkeypatch.setattr(prompts, "pick_category", lambda **_k: prompts.SKIP)
    monkeypatch.setattr(prompts, "pick_hashtag", lambda **_k: prompts.SKIP)
    script = _PromptScript(
        [
            "Last 30 days",  # date preset
            "",  # search
            "any",  # cleared
            False,  # include-deleted
            "",  # page size
            "",  # pause
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_tx.run_list(_make_ctx())
    params = route.calls.last.request.url.params
    assert params.get("date_from") is not None
    assert params.get("date_to") is not None
    # ISO 8601 with year:
    assert params.get("date_from").startswith("20")


@respx.mock
def test_list_date_preset_custom(configured, monkeypatch):
    route = respx.get("https://api.example.com/v1/transactions").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: prompts.SKIP)
    monkeypatch.setattr(prompts, "pick_category", lambda **_k: prompts.SKIP)
    monkeypatch.setattr(prompts, "pick_hashtag", lambda **_k: prompts.SKIP)
    script = _PromptScript(
        [
            "Custom range…",
            "2026-01-01",  # from
            "2026-03-31",  # to
            "",  # search
            "any",  # cleared
            False,  # include-deleted
            "",  # page size
            "",  # pause
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_tx.run_list(_make_ctx())
    params = route.calls.last.request.url.params
    assert params.get("date_from").startswith("2026-01-01")
    assert params.get("date_to").startswith("2026-03-31")


def test_list_reconciliation_skipped_without_account(monkeypatch):
    """Without an account picked, reconciliation prompt must not be offered."""
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: prompts.SKIP)
    monkeypatch.setattr(prompts, "pick_category", lambda **_k: prompts.SKIP)
    monkeypatch.setattr(prompts, "pick_hashtag", lambda **_k: prompts.SKIP)

    rec_called = {"hit": False}

    def _rec(**_k):
        rec_called["hit"] = True
        return prompts.BACK

    monkeypatch.setattr(prompts, "pick_reconciliation", _rec)

    # Will abort at first date prompt by returning None — but we only care
    # whether pick_reconciliation got invoked.
    script = _PromptScript([None])
    _patch_questionary(monkeypatch, script)
    menu_tx.run_list(_make_ctx())
    assert rec_called["hit"] is False


# ----------------------------------------------------------- 2. Get


@respx.mock
def test_get_happy(configured, monkeypatch):
    tx_id = "55555555-5555-5555-5555-555555555555"
    route = respx.get(f"https://api.example.com/v1/transactions/{tx_id}").mock(
        return_value=httpx.Response(200, json=TRANSACTION_RESPONSE)
    )
    monkeypatch.setattr(prompts, "pick_transaction", lambda **_k: tx_id)
    script = _PromptScript([""])  # pause
    _patch_questionary(monkeypatch, script)
    menu_tx.run_get(_make_ctx())
    assert route.called


# ----------------------------------------------------------- 3. Update


@respx.mock
def test_update_title_only(configured, monkeypatch):
    tx_id = TRANSACTION_RESPONSE["id"]
    route = respx.put(f"https://api.example.com/v1/transactions/{tx_id}").mock(
        return_value=httpx.Response(200, json=TRANSACTION_RESPONSE)
    )
    monkeypatch.setattr(prompts, "pick_transaction", lambda **_k: tx_id)
    monkeypatch.setattr(menu_tx.queries, "get_transaction", lambda _id: TRANSACTION_RESPONSE)
    script = _PromptScript(
        [
            True,  # update title? Yes
            "New title",  # new title
            False,  # amount? No
            False,  # date? No
            False,  # account? No
            False,  # category? No
            False,  # description? No
            False,  # cleared? No
            False,  # exchange rate? No
            False,  # hashtags? No
            False,  # reconciliation? No
            True,  # confirm
            "",  # pause
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_tx.run_update(_make_ctx())
    body = json.loads(route.calls.last.request.content)
    assert body == {"title": "New title"}


@respx.mock
def test_update_hashtags_replace(configured, monkeypatch):
    tx_id = TRANSACTION_WITH_HASHTAGS["id"]
    route = respx.put(f"https://api.example.com/v1/transactions/{tx_id}").mock(
        return_value=httpx.Response(200, json=TRANSACTION_WITH_HASHTAGS)
    )
    monkeypatch.setattr(prompts, "pick_transaction", lambda **_k: tx_id)
    monkeypatch.setattr(menu_tx.queries, "get_transaction", lambda _id: TRANSACTION_WITH_HASHTAGS)
    # Resolve hashtag name lookup
    monkeypatch.setattr(
        menu_tx.queries,
        "list_hashtags",
        lambda **_k: {"items": [{"id": "hashtag-a", "name": "lunch"}]},
    )
    monkeypatch.setattr(prompts, "pick_hashtag", lambda **_k: ["hashtag-a", "hashtag-b"])
    script = _PromptScript(
        [
            False,  # title? No
            False,  # amount? No
            False,  # date? No
            False,  # account? No
            False,  # category? No
            False,  # description? No
            False,  # cleared? No
            False,  # exchange rate? No
            True,  # hashtags? Yes
            False,  # reconciliation? No
            True,  # confirm
            "",  # pause
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_tx.run_update(_make_ctx())
    body = json.loads(route.calls.last.request.content)
    assert body["hashtag_ids"] == ["hashtag-a", "hashtag-b"]


@respx.mock
def test_update_hashtags_overlap_payload_shape(configured, monkeypatch):
    """Overlap PUT: cached set [A], new set [A, B]. Engine 0a75a9d handles
    overlap correctly server-side; the CLI just produces the right wire shape."""
    tx_id = TRANSACTION_WITH_HASHTAGS["id"]
    route = respx.put(f"https://api.example.com/v1/transactions/{tx_id}").mock(
        return_value=httpx.Response(200, json=TRANSACTION_WITH_HASHTAGS)
    )
    monkeypatch.setattr(prompts, "pick_transaction", lambda **_k: tx_id)
    monkeypatch.setattr(menu_tx.queries, "get_transaction", lambda _id: TRANSACTION_WITH_HASHTAGS)
    monkeypatch.setattr(
        menu_tx.queries, "list_hashtags", lambda **_k: {"items": [{"id": "hashtag-a", "name": "A"}]}
    )
    monkeypatch.setattr(prompts, "pick_hashtag", lambda **_k: ["hashtag-a", "hashtag-b"])
    script = _PromptScript(
        [False] * 8 + [True, False, True, ""]  # only hashtags+confirm+pause
    )
    _patch_questionary(monkeypatch, script)
    menu_tx.run_update(_make_ctx())
    body = json.loads(route.calls.last.request.content)
    # Engine expects the full new set on PUT; engine de-dupes server-side.
    assert body["hashtag_ids"] == ["hashtag-a", "hashtag-b"]


def test_update_no_changes_short_circuit(monkeypatch, capsys):
    tx_id = TRANSACTION_RESPONSE["id"]
    monkeypatch.setattr(prompts, "pick_transaction", lambda **_k: tx_id)
    monkeypatch.setattr(menu_tx.queries, "get_transaction", lambda _id: TRANSACTION_RESPONSE)
    monkeypatch.setattr(menu_tx.queries, "list_hashtags", lambda **_k: {"items": []})
    # All 10 fields: No, then pause-Enter after "No changes." (Step 9.5.11b).
    script = _PromptScript([False] * 10 + [""])
    _patch_questionary(monkeypatch, script)
    menu_tx.run_update(_make_ctx())
    out = capsys.readouterr().out
    assert "No changes." in out


@respx.mock
def test_update_transfer_leg_422_does_not_kill_flow(configured, monkeypatch):
    tx_id = TRANSACTION_RESPONSE["id"]
    respx.put(f"https://api.example.com/v1/transactions/{tx_id}").mock(
        return_value=httpx.Response(
            422,
            json={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Transfer-pair leg edit guard rejected this update.",
                    "fields": {"amount_cents": "Read-only on transfer legs."},
                }
            },
        )
    )
    monkeypatch.setattr(prompts, "pick_transaction", lambda **_k: tx_id)
    monkeypatch.setattr(menu_tx.queries, "get_transaction", lambda _id: TRANSACTION_RESPONSE)
    monkeypatch.setattr(menu_tx.queries, "list_hashtags", lambda **_k: {"items": []})
    script = _PromptScript(
        [
            False,  # title
            True,  # amount? Yes
            "-500",  # new amount
            False,  # date
            False,  # account
            False,  # category
            False,  # description
            False,  # cleared
            False,  # exchange rate
            False,  # hashtags
            False,  # reconciliation
            True,  # confirm
            "",  # pause — must be reached
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_tx.run_update(_make_ctx())
    assert script.remaining == 0


# ----------------------------------------------------------- 4. Delete


@respx.mock
def test_delete_happy(configured, monkeypatch):
    tx_id = TRANSACTION_RESPONSE["id"]
    route = respx.delete(f"https://api.example.com/v1/transactions/{tx_id}").mock(
        return_value=httpx.Response(200, json=TRANSACTION_RESPONSE)
    )
    monkeypatch.setattr(prompts, "pick_transaction", lambda **_k: tx_id)
    monkeypatch.setattr(prompts, "confirm_destructive", lambda *a, **k: True)
    script = _PromptScript([""])  # pause
    _patch_questionary(monkeypatch, script)
    menu_tx.run_delete(_make_ctx())
    assert route.called


# ----------------------------------------------------------- 5. Restore


@respx.mock
def test_restore_happy(configured, monkeypatch):
    tx_id = TRANSACTION_RESPONSE["id"]
    route = respx.post(f"https://api.example.com/v1/transactions/{tx_id}/restore").mock(
        return_value=httpx.Response(200, json=TRANSACTION_RESPONSE)
    )
    monkeypatch.setattr(prompts, "pick_transaction", lambda **_k: tx_id)
    script = _PromptScript([""])  # pause
    _patch_questionary(monkeypatch, script)
    menu_tx.run_restore(_make_ctx())
    assert route.called


# ----------------------------------------------------------- 6. Batch


@respx.mock
def test_batch_happy(configured, monkeypatch, tmp_path):
    batch_file = tmp_path / "batch.json"
    batch_file.write_text(
        json.dumps(
            [
                {
                    "title": "T1",
                    "amount_cents": -100,
                    "account_id": "a",
                    "category_id": "c",
                },
                {
                    "title": "T2",
                    "amount_cents": -200,
                    "account_id": "a",
                    "category_id": "c",
                },
            ]
        )
    )
    route = respx.post("https://api.example.com/v1/transactions/batch").mock(
        return_value=httpx.Response(
            201,
            json={
                "transactions": [
                    {**TRANSACTION_RESPONSE, "title": "T1"},
                    {**TRANSACTION_RESPONSE, "title": "T2"},
                ]
            },
        )
    )
    monkeypatch.setattr(prompts, "confirm_destructive", lambda *a, **k: True)
    script = _PromptScript([str(batch_file), ""])  # path, pause
    _patch_questionary(monkeypatch, script)
    menu_tx.run_batch(_make_ctx())
    assert route.called


def test_batch_rejects_transfer_field(monkeypatch, tmp_path, capsys):
    batch_file = tmp_path / "bad.json"
    batch_file.write_text(
        json.dumps([{"title": "T1", "amount_cents": -100, "transfer": {"id": "x"}}])
    )
    # path + pause-Enter after the transfer-rejection message (Step 9.5.11b).
    script = _PromptScript([str(batch_file), ""])
    _patch_questionary(monkeypatch, script)
    menu_tx.run_batch(_make_ctx())
    err = capsys.readouterr().err
    assert "transfer" in err and "not supported" in err
