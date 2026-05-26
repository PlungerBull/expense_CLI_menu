"""Step 9.5.12 — menu-driven Reconciliations flows.

Covers the 10 reconcile verbs (list/get/create/update/complete/revert/
move/reorder/delete/restore), the source/beginning-balance mutex guard on
create, the revert audit-event warning surface, the move mode picker, and
the $EDITOR reorder hand-off.
"""

import json
from uuid import uuid4

import httpx
import pytest
import respx

from expense import _editor
from expense import config as config_module
from expense.commands import reconcile_cmd
from expense.menu import prompts
from expense.menu.groups import _common as menu_common
from expense.menu.groups import reconciliations as menu_recon

ACCOUNT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
RECON_ID = "11111111-1111-1111-1111-111111111111"
PEER_ID = "22222222-2222-2222-2222-222222222222"
DELETED_ID = "33333333-3333-3333-3333-333333333333"

RECON_RESPONSE = {
    "id": RECON_ID,
    "user_id": "u1",
    "account_id": ACCOUNT_ID,
    "name": "April 2026",
    "date_start": "2026-04-01T00:00:00Z",
    "date_end": "2026-04-30T23:59:59Z",
    "beginning_balance_cents": 100000,
    "ending_balance_cents": 150000,
    "beginning_balance_source": "manual",
    "status": 1,
    "sort_order": 1,
    "version": 1,
    "created_at": "2026-04-15T10:00:00Z",
    "updated_at": "2026-04-15T10:00:00Z",
    "deleted_at": None,
    "transactions": [],
    "transactions_total": 0,
}

LIST_RESPONSE = {"items": [RECON_RESPONSE], "total": 1, "limit": 100, "offset": 0}


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
    monkeypatch.setattr(menu_recon.questionary, "select", script)
    monkeypatch.setattr(menu_recon.questionary, "text", script)
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
    route = respx.get("https://api.example.com/v1/reconciliations")
    script = _PromptScript(["← Back"])
    _patch_questionary(monkeypatch, script)
    menu_recon.run_reconciliations_menu(_make_ctx())
    assert not route.called


# --------------------------------------------------------------- 1. List


@respx.mock
def test_list_no_account_no_deleted(configured, monkeypatch, capsys):
    route = respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: prompts.SKIP)
    script = _PromptScript(
        [
            "List reconciliations",
            False,  # include_deleted
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_recon.run_reconciliations_menu(_make_ctx())
    assert route.called
    request = route.calls.last.request
    assert "account_id" not in request.url.params
    assert "include_deleted" not in request.url.params
    assert "April 2026" in capsys.readouterr().out


@respx.mock
def test_list_with_account_filter(configured, monkeypatch):
    route = respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: ACCOUNT_ID)
    script = _PromptScript(
        [
            "List reconciliations",
            True,  # include_deleted
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_recon.run_reconciliations_menu(_make_ctx())
    request = route.calls.last.request
    assert request.url.params.get("account_id") == ACCOUNT_ID
    assert request.url.params.get("include_deleted") == "true"


# --------------------------------------------------------------- 2. View


@respx.mock
def test_view_happy(configured, monkeypatch, capsys):
    route = respx.get(f"https://api.example.com/v1/reconciliations/{RECON_ID}").mock(
        return_value=httpx.Response(200, json=RECON_RESPONSE)
    )
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: ACCOUNT_ID)
    monkeypatch.setattr(prompts, "pick_reconciliation", lambda **_k: RECON_ID)
    script = _PromptScript(
        [
            "View a reconciliation",
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_recon.run_reconciliations_menu(_make_ctx())
    assert route.called
    assert "April 2026" in capsys.readouterr().out


# --------------------------------------------------------------- 3. Create


@respx.mock
def test_create_manual_with_beginning_balance(configured, monkeypatch):
    route = respx.post("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(201, json=RECON_RESPONSE)
    )
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: ACCOUNT_ID)
    script = _PromptScript(
        [
            "Create a reconciliation",
            "April 2026",  # name
            "",  # date_start (skip)
            "",  # date_end (skip)
            "manual",  # source
            "100000",  # beginning_balance
            "150000",  # ending_balance
            "",  # sort_order
            True,  # confirm
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_recon.run_reconciliations_menu(_make_ctx())
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body["account_id"] == ACCOUNT_ID
    assert body["name"] == "April 2026"
    assert body["beginning_balance_cents"] == 100000
    assert body["ending_balance_cents"] == 150000
    assert body["beginning_balance_source"] == "manual"


@respx.mock
def test_create_chained_skips_beginning_balance(configured, monkeypatch):
    """Chained source must NOT prompt for beginning_balance (engine mutex)."""
    route = respx.post("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(
            201, json={**RECON_RESPONSE, "beginning_balance_source": "chained"}
        )
    )
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: ACCOUNT_ID)
    script = _PromptScript(
        [
            "Create a reconciliation",
            "May 2026",  # name
            "",  # date_start
            "",  # date_end
            "chained",  # source — no beginning_balance prompt
            "175000",  # ending_balance
            "",  # sort_order
            True,  # confirm
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_recon.run_reconciliations_menu(_make_ctx())
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body["beginning_balance_source"] == "chained"
    assert "beginning_balance_cents" not in body
    assert body["ending_balance_cents"] == 175000


@respx.mock
def test_create_declined_no_http(configured, monkeypatch):
    route = respx.post("https://api.example.com/v1/reconciliations")
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: ACCOUNT_ID)
    script = _PromptScript(
        [
            "Create a reconciliation",
            "April 2026",
            "",
            "",
            "chained",
            "",  # ending_balance skip
            "",  # sort_order skip
            False,  # confirm? No
            "",  # pause after Aborted.
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_recon.run_reconciliations_menu(_make_ctx())
    assert not route.called


# --------------------------------------------------------------- 4. Update


@respx.mock
def test_update_no_changes_no_http(configured, monkeypatch, capsys):
    route = respx.put(f"https://api.example.com/v1/reconciliations/{RECON_ID}")
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: ACCOUNT_ID)
    monkeypatch.setattr(prompts, "pick_reconciliation", lambda **_k: RECON_ID)
    monkeypatch.setattr(
        menu_recon.cache_pkg, "get_reconciliation", lambda *_a, **_k: RECON_RESPONSE
    )
    script = _PromptScript(
        [
            "Update a reconciliation",
            False,  # name? No
            False,  # date_start? No
            False,  # date_end? No
            False,  # source? No
            False,  # beginning_balance? No
            False,  # ending_balance? No
            "",  # pause after No changes.
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_recon.run_reconciliations_menu(_make_ctx())
    assert not route.called
    assert "No changes." in capsys.readouterr().out


@respx.mock
def test_update_name_only(configured, monkeypatch):
    route = respx.put(f"https://api.example.com/v1/reconciliations/{RECON_ID}").mock(
        return_value=httpx.Response(200, json=RECON_RESPONSE)
    )
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: ACCOUNT_ID)
    monkeypatch.setattr(prompts, "pick_reconciliation", lambda **_k: RECON_ID)
    monkeypatch.setattr(
        menu_recon.cache_pkg, "get_reconciliation", lambda *_a, **_k: RECON_RESPONSE
    )
    script = _PromptScript(
        [
            "Update a reconciliation",
            True,  # name? Yes
            "April 2026 (revised)",  # new name
            False,  # date_start? No
            False,  # date_end? No
            False,  # source? No
            False,  # beginning_balance? No
            False,  # ending_balance? No
            True,  # confirm? Yes
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_recon.run_reconciliations_menu(_make_ctx())
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body == {"name": "April 2026 (revised)"}


@respx.mock
def test_update_to_chained_skips_beginning_balance(configured, monkeypatch):
    """Switching source to chained should NOT prompt for beginning balance."""
    route = respx.put(f"https://api.example.com/v1/reconciliations/{RECON_ID}").mock(
        return_value=httpx.Response(200, json=RECON_RESPONSE)
    )
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: ACCOUNT_ID)
    monkeypatch.setattr(prompts, "pick_reconciliation", lambda **_k: RECON_ID)
    monkeypatch.setattr(
        menu_recon.cache_pkg, "get_reconciliation", lambda *_a, **_k: RECON_RESPONSE
    )
    script = _PromptScript(
        [
            "Update a reconciliation",
            False,  # name? No
            False,  # date_start? No
            False,  # date_end? No
            True,  # source? Yes
            "chained",  # picked source
            # NO beginning_balance prompt now
            False,  # ending_balance? No
            True,  # confirm
            "",
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_recon.run_reconciliations_menu(_make_ctx())
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body == {"beginning_balance_source": "chained"}


# --------------------------------------------------------------- 5. Complete


@respx.mock
def test_complete_happy(configured, monkeypatch):
    route = respx.post(f"https://api.example.com/v1/reconciliations/{RECON_ID}/complete").mock(
        return_value=httpx.Response(200, json=RECON_RESPONSE)
    )
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: ACCOUNT_ID)
    monkeypatch.setattr(prompts, "pick_reconciliation", lambda **_k: RECON_ID)
    monkeypatch.setattr(prompts, "confirm_destructive", lambda *a, **k: True)
    script = _PromptScript(
        [
            "Complete a reconciliation",
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_recon.run_reconciliations_menu(_make_ctx())
    assert route.called


# --------------------------------------------------------------- 6. Revert


@respx.mock
def test_revert_warning_mentions_audit_event(configured, monkeypatch):
    """Roadmap gate criterion: extra-strong confirm must mention audit event + unlocking."""
    route = respx.post(f"https://api.example.com/v1/reconciliations/{RECON_ID}/revert").mock(
        return_value=httpx.Response(200, json=RECON_RESPONSE)
    )
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: ACCOUNT_ID)
    monkeypatch.setattr(prompts, "pick_reconciliation", lambda **_k: RECON_ID)

    captured: dict = {}

    def capturing_confirm(message, warning=None):
        captured["message"] = message
        captured["warning"] = warning
        return True

    monkeypatch.setattr(prompts, "confirm_destructive", capturing_confirm)
    script = _PromptScript(
        [
            "Revert a completed reconciliation",
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_recon.run_reconciliations_menu(_make_ctx())
    assert route.called
    assert captured["warning"] is not None
    assert "audit" in captured["warning"].lower()
    assert "unlock" in captured["warning"].lower()


# --------------------------------------------------------------- 7. Move


@respx.mock
def test_move_to_position(configured, monkeypatch):
    respx.get(f"https://api.example.com/v1/reconciliations/{RECON_ID}").mock(
        return_value=httpx.Response(200, json=RECON_RESPONSE)
    )
    respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {**RECON_RESPONSE, "id": PEER_ID, "sort_order": 1, "name": "March"},
                    {**RECON_RESPONSE, "id": RECON_ID, "sort_order": 2, "name": "April"},
                ],
                "total": 2,
                "limit": 200,
                "offset": 0,
            },
        )
    )
    put_route = respx.put(
        f"https://api.example.com/v1/accounts/{ACCOUNT_ID}/reconciliations/order"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "reconciliations": [
                    {**RECON_RESPONSE, "id": RECON_ID, "sort_order": 1},
                    {**RECON_RESPONSE, "id": PEER_ID, "sort_order": 2},
                ],
                "recalculated_count": 1,
            },
        )
    )
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: ACCOUNT_ID)
    monkeypatch.setattr(prompts, "pick_reconciliation", lambda **_k: RECON_ID)
    script = _PromptScript(
        [
            "Move a reconciliation in the chain",
            "to",  # mode select
            "1",  # position
            True,  # confirm
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_recon.run_reconciliations_menu(_make_ctx())
    assert put_route.called
    body = json.loads(put_route.calls.last.request.content)
    assert body["ordered_ids"] == [RECON_ID, PEER_ID]


@respx.mock
def test_move_rejects_self_as_peer(configured, monkeypatch, capsys):
    """`before`/`after` cannot reference the source itself."""
    put_route = respx.put(f"https://api.example.com/v1/accounts/{ACCOUNT_ID}/reconciliations/order")
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: ACCOUNT_ID)
    # First call returns the source; second call returns the same ID as peer.
    calls = iter([RECON_ID, RECON_ID])
    monkeypatch.setattr(prompts, "pick_reconciliation", lambda **_k: next(calls))
    script = _PromptScript(
        [
            "Move a reconciliation in the chain",
            "before",  # mode
            "",  # pause after rejection
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_recon.run_reconciliations_menu(_make_ctx())
    assert not put_route.called
    assert "cannot reference the source itself" in capsys.readouterr().err


# --------------------------------------------------------------- 8. Reorder ($EDITOR)


@respx.mock
def test_reorder_happy(configured, monkeypatch):
    respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {**RECON_RESPONSE, "id": RECON_ID, "sort_order": 1, "name": "April"},
                    {**RECON_RESPONSE, "id": PEER_ID, "sort_order": 2, "name": "May"},
                ],
                "total": 2,
                "limit": 200,
                "offset": 0,
            },
        )
    )
    put_route = respx.put(
        f"https://api.example.com/v1/accounts/{ACCOUNT_ID}/reconciliations/order"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "reconciliations": [
                    {**RECON_RESPONSE, "id": PEER_ID, "sort_order": 1},
                    {**RECON_RESPONSE, "id": RECON_ID, "sort_order": 2},
                ],
                "recalculated_count": 2,
            },
        )
    )
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: ACCOUNT_ID)

    # Mock $EDITOR: swap the two lines.
    def fake_editor(initial_text, *, suffix=".txt", editor=None):
        assert suffix == ".reorder"
        # Reverse order.
        lines = [ln for ln in initial_text.splitlines() if ln and not ln.startswith("#")]
        return "\n".join(reversed(lines)) + "\n"

    monkeypatch.setattr(_editor, "edit_text", fake_editor)
    # reconcile_cmd imported _editor at module level — patch there too.
    monkeypatch.setattr(reconcile_cmd._editor, "edit_text", fake_editor)

    script = _PromptScript(
        [
            "Reorder reconciliations ($EDITOR)",
            "",  # year filter (skip)
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_recon.run_reconciliations_menu(_make_ctx())
    assert put_route.called
    body = json.loads(put_route.calls.last.request.content)
    assert body["ordered_ids"] == [PEER_ID, RECON_ID]


# --------------------------------------------------------------- 9. Delete


@respx.mock
def test_delete_warning_mentions_cascade(configured, monkeypatch):
    """Roadmap gate criterion: cascade-unassign warning must surface before submit."""
    route = respx.delete(f"https://api.example.com/v1/reconciliations/{RECON_ID}").mock(
        return_value=httpx.Response(
            200, json={**RECON_RESPONSE, "deleted_at": "2026-05-25T00:00:00Z"}
        )
    )
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: ACCOUNT_ID)
    monkeypatch.setattr(prompts, "pick_reconciliation", lambda **_k: RECON_ID)

    captured: dict = {}

    def capturing_confirm(message, warning=None):
        captured["warning"] = warning
        return True

    monkeypatch.setattr(prompts, "confirm_destructive", capturing_confirm)
    script = _PromptScript(
        [
            "Delete a reconciliation",
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_recon.run_reconciliations_menu(_make_ctx())
    assert route.called
    assert captured["warning"] is not None
    assert "cascade" in captured["warning"].lower()


@respx.mock
def test_delete_declined_no_http(configured, monkeypatch):
    route = respx.delete(f"https://api.example.com/v1/reconciliations/{RECON_ID}")
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: ACCOUNT_ID)
    monkeypatch.setattr(prompts, "pick_reconciliation", lambda **_k: RECON_ID)
    monkeypatch.setattr(prompts, "confirm_destructive", lambda *a, **k: False)
    script = _PromptScript(
        [
            "Delete a reconciliation",
            "",  # pause after Aborted.
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_recon.run_reconciliations_menu(_make_ctx())
    assert not route.called


# --------------------------------------------------------------- 10. Restore


@respx.mock
def test_restore_happy(configured, monkeypatch):
    route = respx.post(f"https://api.example.com/v1/reconciliations/{DELETED_ID}/restore").mock(
        return_value=httpx.Response(
            200, json={**RECON_RESPONSE, "id": DELETED_ID, "deleted_at": None}
        )
    )
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: ACCOUNT_ID)
    monkeypatch.setattr(
        menu_recon.cache_pkg,
        "list_reconciliations",
        lambda **_k: {
            "items": [
                {
                    **RECON_RESPONSE,
                    "id": DELETED_ID,
                    "deleted_at": "2026-05-20T00:00:00Z",
                    "name": "Archived March 2026",
                }
            ],
            "total": 1,
            "limit": 100,
            "offset": 0,
        },
    )
    script = _PromptScript(
        [
            "Restore a deleted reconciliation",
            DELETED_ID,  # questionary.select returns the id directly
            True,  # confirm
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_recon.run_reconciliations_menu(_make_ctx())
    assert route.called


@respx.mock
def test_restore_empty_returns_no_http(configured, monkeypatch):
    route = respx.post(f"https://api.example.com/v1/reconciliations/{DELETED_ID}/restore")
    monkeypatch.setattr(prompts, "pick_account", lambda **_k: ACCOUNT_ID)
    monkeypatch.setattr(
        menu_recon.cache_pkg,
        "list_reconciliations",
        lambda **_k: {"items": [], "total": 0, "limit": 100, "offset": 0},
    )
    script = _PromptScript(
        [
            "Restore a deleted reconciliation",
            "",  # pause after "No deleted reconciliations found"
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_recon.run_reconciliations_menu(_make_ctx())
    assert not route.called
