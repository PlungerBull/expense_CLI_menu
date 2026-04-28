import json
from uuid import UUID, uuid4

import httpx
import pytest
import respx
import typer
from typer.testing import CliRunner

from expense import config as config_module
from expense.commands.reconcile_cmd import app as reconcile_app

cli_app = typer.Typer()


@cli_app.callback()
def _root() -> None:
    pass


cli_app.add_typer(reconcile_app, name="reconcile")

runner = CliRunner()


def _strip_panel(output: str) -> str:
    no_box = "".join(c for c in output if c not in "│╭╮╰╯─\n\t")
    return " ".join(no_box.split())


RECON_DRAFT_RESPONSE = {
    "id": "11111111-1111-1111-1111-111111111111",
    "user_id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
    "account_id": "22222222-2222-2222-2222-222222222222",
    "name": "Statement April 2026",
    "date_start": "2026-04-01T00:00:00Z",
    "date_end": "2026-04-30T23:59:59Z",
    "beginning_balance_cents": 100000,
    "beginning_balance_home_cents": 100000,
    "ending_balance_cents": 150000,
    "ending_balance_home_cents": 150000,
    "status": 1,
    "sort_order": 4,
    "beginning_balance_source": "chained",
    "chained_from_reconciliation_id": "00000000-0000-0000-0000-000000000003",
    "version": 1,
    "created_at": "2026-04-15T10:00:00Z",
    "updated_at": "2026-04-15T10:00:00Z",
    "deleted_at": None,
}

RECON_MANUAL_RESPONSE = {
    **RECON_DRAFT_RESPONSE,
    "id": "33333333-3333-3333-3333-333333333333",
    "beginning_balance_source": "manual",
    "chained_from_reconciliation_id": None,
}

LIST_RESPONSE = {
    "items": [RECON_DRAFT_RESPONSE, RECON_MANUAL_RESPONSE],
    "total": 2,
    "limit": 50,
    "offset": 0,
}

DETAIL_WITH_TRANSACTIONS = {
    **RECON_DRAFT_RESPONSE,
    "transactions": [
        {
            "id": "tx-001",
            "title": "Lunch",
            "amount_cents": -1500,
            "account_id": "22222222-2222-2222-2222-222222222222",
            "category_id": "cat-food",
            "date": "2026-04-15T12:00:00Z",
            "reconciliation_id": RECON_DRAFT_RESPONSE["id"],
            "version": 1,
            "created_at": "2026-04-15T12:05:00Z",
            "updated_at": "2026-04-15T12:05:00Z",
            "deleted_at": None,
        }
    ],
    "transactions_total": 3,
    "transactions_limit": 1,
    "transactions_offset": 0,
    "transactions_truncated": True,
}

DETAIL_EMPTY_TRANSACTIONS = {
    **RECON_DRAFT_RESPONSE,
    "transactions": [],
    "transactions_total": 0,
    "transactions_limit": 50,
    "transactions_offset": 0,
    "transactions_truncated": False,
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
    yield


@respx.mock
def test_list_happy_with_account_filter(configured):
    route = respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(
        cli_app,
        ["reconcile", "list", "--account", "22222222-2222-2222-2222-222222222222"],
    )
    assert result.exit_code == 0, result.output
    assert "Statement April 2026" in result.output
    assert "[chained from 00000000-0000-0000-0000-000000000003]" in result.output
    assert "[manual]" in result.output

    request = route.calls.last.request
    assert request.url.params.get("account_id") == "22222222-2222-2222-2222-222222222222"


@respx.mock
def test_list_empty(configured):
    respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json={"items": [], "total": 0, "limit": 50, "offset": 0})
    )
    result = runner.invoke(cli_app, ["reconcile", "list"])
    assert result.exit_code == 0, result.output
    assert "(no reconciliations)" in result.output


@respx.mock
def test_list_json_passthrough(configured):
    respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["reconcile", "list", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == LIST_RESPONSE


@respx.mock
def test_get_with_transactions_window(configured):
    route = respx.get(
        "https://api.example.com/v1/reconciliations/11111111-1111-1111-1111-111111111111"
    ).mock(return_value=httpx.Response(200, json=DETAIL_WITH_TRANSACTIONS))
    result = runner.invoke(
        cli_app, ["reconcile", "get", "11111111-1111-1111-1111-111111111111", "--limit", "1"]
    )
    assert result.exit_code == 0, result.output
    assert "Statement April 2026" in result.output
    assert "Transactions:" in result.output
    assert "Lunch" in result.output
    assert "more transactions" in result.output
    assert "transactions list --reconciliation" in result.output

    request = route.calls.last.request
    assert request.url.params.get("limit") == "1"


@respx.mock
def test_get_empty_transactions_hint(configured):
    respx.get(
        "https://api.example.com/v1/reconciliations/11111111-1111-1111-1111-111111111111"
    ).mock(return_value=httpx.Response(200, json=DETAIL_EMPTY_TRANSACTIONS))
    result = runner.invoke(cli_app, ["reconcile", "get", "11111111-1111-1111-1111-111111111111"])
    assert result.exit_code == 0, result.output
    assert "(no transactions assigned)" in result.output
    assert "transactions update <tx-id> --reconciliation-id" in result.output


@respx.mock
def test_get_404(configured):
    respx.get("https://api.example.com/v1/reconciliations/missing").mock(
        return_value=httpx.Response(
            404,
            json={"error": {"code": "NOT_FOUND", "message": "Not found", "fields": None}},
        )
    )
    result = runner.invoke(cli_app, ["reconcile", "get", "missing"])
    assert result.exit_code == 1
    assert "NOT_FOUND" in result.output


@respx.mock
def test_create_chained_default(configured):
    route = respx.post("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(201, json=RECON_DRAFT_RESPONSE)
    )
    result = runner.invoke(
        cli_app,
        [
            "reconcile",
            "create",
            "--account",
            "22222222-2222-2222-2222-222222222222",
            "--name",
            "Statement April 2026",
            "--date-start",
            "2026-04-01",
            "--date-end",
            "2026-04-30",
            "--ending-balance",
            "150000",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Created:" in result.output
    assert "[chained from " in result.output
    assert "Next: attach transactions" in result.output

    body = json.loads(route.calls.last.request.content)
    UUID(body["id"])
    assert body["account_id"] == "22222222-2222-2222-2222-222222222222"
    assert body["name"] == "Statement April 2026"
    assert body["ending_balance_cents"] == 150000
    assert "beginning_balance_cents" not in body, "expected omission to trigger chaining"
    assert "X-Idempotency-Key" in route.calls.last.request.headers


@respx.mock
def test_create_with_manual_balance(configured):
    route = respx.post("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(201, json=RECON_MANUAL_RESPONSE)
    )
    result = runner.invoke(
        cli_app,
        [
            "reconcile",
            "create",
            "--account",
            "22222222-2222-2222-2222-222222222222",
            "--name",
            "Cutover",
            "--beginning-balance",
            "999999",
            "--ending-balance",
            "1050000",
        ],
    )
    assert result.exit_code == 0, result.output

    body = json.loads(route.calls.last.request.content)
    assert body["beginning_balance_cents"] == 999999
    assert "beginning_balance_source" not in body


def test_create_chained_with_balance_blocks_at_parse(configured):
    result = runner.invoke(
        cli_app,
        [
            "reconcile",
            "create",
            "--account",
            "acct",
            "--name",
            "X",
            "--source",
            "chained",
            "--beginning-balance",
            "100",
        ],
    )
    assert result.exit_code != 0
    stripped = _strip_panel(result.output)
    assert "--source chained cannot be combined" in stripped


def test_create_invalid_source_value_blocks_at_parse(configured):
    result = runner.invoke(
        cli_app,
        [
            "reconcile",
            "create",
            "--account",
            "acct",
            "--name",
            "X",
            "--source",
            "auto",
        ],
    )
    assert result.exit_code != 0
    stripped = _strip_panel(result.output)
    assert "Choose one of: manual, chained" in stripped


@respx.mock
def test_update_partial_payload(configured):
    route = respx.put(
        "https://api.example.com/v1/reconciliations/11111111-1111-1111-1111-111111111111"
    ).mock(return_value=httpx.Response(200, json=RECON_DRAFT_RESPONSE))
    result = runner.invoke(
        cli_app,
        [
            "reconcile",
            "update",
            "11111111-1111-1111-1111-111111111111",
            "--name",
            "Renamed",
            "--ending-balance",
            "200000",
        ],
    )
    assert result.exit_code == 0, result.output

    body = json.loads(route.calls.last.request.content)
    assert body == {"name": "Renamed", "ending_balance_cents": 200000}
    assert "X-Idempotency-Key" in route.calls.last.request.headers


@respx.mock
def test_update_source_chained_alone(configured):
    route = respx.put(
        "https://api.example.com/v1/reconciliations/11111111-1111-1111-1111-111111111111"
    ).mock(return_value=httpx.Response(200, json=RECON_DRAFT_RESPONSE))
    result = runner.invoke(
        cli_app,
        ["reconcile", "update", "11111111-1111-1111-1111-111111111111", "--source", "chained"],
    )
    assert result.exit_code == 0, result.output

    body = json.loads(route.calls.last.request.content)
    assert body == {"beginning_balance_source": "chained"}


def test_update_chained_with_balance_blocks_at_parse(configured):
    result = runner.invoke(
        cli_app,
        [
            "reconcile",
            "update",
            "11111111-1111-1111-1111-111111111111",
            "--source",
            "chained",
            "--beginning-balance",
            "500",
        ],
    )
    assert result.exit_code != 0
    stripped = _strip_panel(result.output)
    assert "--source chained cannot be combined" in stripped


@respx.mock
def test_update_field_locked_422_surfaces_hint(configured):
    respx.put(
        "https://api.example.com/v1/reconciliations/11111111-1111-1111-1111-111111111111"
    ).mock(
        return_value=httpx.Response(
            422,
            json={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Cannot edit locked fields on completed reconciliation.",
                    "fields": {
                        "ending_balance_cents": "Locked while reconciliation is completed.",
                    },
                }
            },
        )
    )
    result = runner.invoke(
        cli_app,
        [
            "reconcile",
            "update",
            "11111111-1111-1111-1111-111111111111",
            "--ending-balance",
            "200000",
        ],
    )
    assert result.exit_code == 1
    assert "VALIDATION_ERROR" in result.output
    assert "expense reconcile revert" in result.output


@respx.mock
def test_update_chained_ambiguity_422_surfaces_hint(configured):
    respx.put(
        "https://api.example.com/v1/reconciliations/11111111-1111-1111-1111-111111111111"
    ).mock(
        return_value=httpx.Response(
            422,
            json={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Cannot set beginning_balance_cents while source is 'chained'.",
                    "fields": {
                        "beginning_balance_cents": "Remove this field, or set source to manual.",
                        "beginning_balance_source": "Cannot be 'chained' while value is set.",
                    },
                }
            },
        )
    )
    result = runner.invoke(
        cli_app,
        [
            "reconcile",
            "update",
            "11111111-1111-1111-1111-111111111111",
            "--name",
            "anything",
        ],
    )
    assert result.exit_code == 1
    assert "VALIDATION_ERROR" in result.output
    assert "--source chained cannot be combined with --beginning-balance" in result.output


def test_delete_requires_yes_in_non_tty(configured):
    result = runner.invoke(cli_app, ["reconcile", "delete", "11111111-1111-1111-1111-111111111111"])
    assert result.exit_code == 1
    assert "non-interactive" in result.output


@respx.mock
def test_delete_with_yes(configured):
    respx.delete(
        "https://api.example.com/v1/reconciliations/11111111-1111-1111-1111-111111111111"
    ).mock(return_value=httpx.Response(200, json={**RECON_DRAFT_RESPONSE, "deleted_at": "now"}))
    result = runner.invoke(
        cli_app,
        ["reconcile", "delete", "11111111-1111-1111-1111-111111111111", "--yes"],
    )
    assert result.exit_code == 0, result.output


@respx.mock
def test_delete_409_surfaces_hint(configured):
    respx.delete(
        "https://api.example.com/v1/reconciliations/11111111-1111-1111-1111-111111111111"
    ).mock(
        return_value=httpx.Response(
            409,
            json={
                "error": {
                    "code": "CONFLICT",
                    "message": "Cannot delete a completed reconciliation.",
                    "fields": None,
                }
            },
        )
    )
    result = runner.invoke(
        cli_app,
        ["reconcile", "delete", "11111111-1111-1111-1111-111111111111", "--yes"],
    )
    assert result.exit_code == 1
    assert "CONFLICT" in result.output
    assert "expense reconcile revert" in result.output


# ---------------------------------------------------------------------------
# Phase 2: restore, complete, revert (state machine)
# ---------------------------------------------------------------------------


@respx.mock
def test_restore_happy_with_note(configured):
    route = respx.post(
        "https://api.example.com/v1/reconciliations/11111111-1111-1111-1111-111111111111/restore"
    ).mock(return_value=httpx.Response(200, json=RECON_DRAFT_RESPONSE))
    result = runner.invoke(
        cli_app, ["reconcile", "restore", "11111111-1111-1111-1111-111111111111"]
    )
    assert result.exit_code == 0, result.output
    assert "NOT re-linked" in result.output
    assert "X-Idempotency-Key" in route.calls.last.request.headers


@respx.mock
def test_complete_happy_prints_locked_count(configured):
    response_with_count = {**RECON_DRAFT_RESPONSE, "status": 2, "transactions_total": 17}
    route = respx.post(
        "https://api.example.com/v1/reconciliations/11111111-1111-1111-1111-111111111111/complete"
    ).mock(return_value=httpx.Response(200, json=response_with_count))
    result = runner.invoke(
        cli_app, ["reconcile", "complete", "11111111-1111-1111-1111-111111111111"]
    )
    assert result.exit_code == 0, result.output
    assert "Locked 17 transactions." in result.output
    assert "X-Idempotency-Key" in route.calls.last.request.headers


@respx.mock
def test_complete_422_empty_batch_surfaces_hint(configured):
    respx.post(
        "https://api.example.com/v1/reconciliations/11111111-1111-1111-1111-111111111111/complete"
    ).mock(
        return_value=httpx.Response(
            422,
            json={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "No transactions assigned to this reconciliation.",
                    "fields": {},
                }
            },
        )
    )
    result = runner.invoke(
        cli_app, ["reconcile", "complete", "11111111-1111-1111-1111-111111111111"]
    )
    assert result.exit_code == 1
    assert "VALIDATION_ERROR" in result.output
    assert "expense transactions update" in result.output


def test_revert_requires_yes_in_non_tty(configured):
    result = runner.invoke(cli_app, ["reconcile", "revert", "11111111-1111-1111-1111-111111111111"])
    assert result.exit_code == 1
    assert "non-interactive" in result.output


@respx.mock
def test_revert_with_yes_prints_unlocked_count(configured):
    response_with_count = {**RECON_DRAFT_RESPONSE, "status": 1, "transactions_total": 17}
    route = respx.post(
        "https://api.example.com/v1/reconciliations/11111111-1111-1111-1111-111111111111/revert"
    ).mock(return_value=httpx.Response(200, json=response_with_count))
    result = runner.invoke(
        cli_app,
        ["reconcile", "revert", "11111111-1111-1111-1111-111111111111", "--yes"],
    )
    assert result.exit_code == 0, result.output
    assert "Unlocked 17 transactions." in result.output
    assert "X-Idempotency-Key" in route.calls.last.request.headers


# ---------------------------------------------------------------------------
# Phase 3a: move (single-row reorder)
# ---------------------------------------------------------------------------

ACCOUNT_ID = "22222222-2222-2222-2222-222222222222"
RECON_A = {
    **RECON_DRAFT_RESPONSE,
    "id": "aaaa",
    "account_id": ACCOUNT_ID,
    "sort_order": 1,
    "name": "Jan",
}
RECON_B = {
    **RECON_DRAFT_RESPONSE,
    "id": "bbbb",
    "account_id": ACCOUNT_ID,
    "sort_order": 2,
    "name": "Feb",
}
RECON_C = {
    **RECON_DRAFT_RESPONSE,
    "id": "cccc",
    "account_id": ACCOUNT_ID,
    "sort_order": 3,
    "name": "Mar",
}

CHAIN_LIST = {
    "items": [RECON_A, RECON_B, RECON_C],
    "total": 3,
    "limit": 200,
    "offset": 0,
}

REORDER_RESPONSE = {
    "reconciliations": [
        {**RECON_C, "sort_order": 1},
        {**RECON_A, "sort_order": 2},
        {**RECON_B, "sort_order": 3},
    ],
    "recalculated_count": 1,
}


@respx.mock
def test_move_to_position(configured):
    respx.get("https://api.example.com/v1/reconciliations/cccc").mock(
        return_value=httpx.Response(200, json=RECON_C)
    )
    respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json=CHAIN_LIST)
    )
    put_route = respx.put(
        f"https://api.example.com/v1/accounts/{ACCOUNT_ID}/reconciliations/order"
    ).mock(return_value=httpx.Response(200, json=REORDER_RESPONSE))

    result = runner.invoke(cli_app, ["reconcile", "move", "cccc", "--to", "1"])
    assert result.exit_code == 0, result.output
    assert "1 chained beginning balance(s) recalculated." in result.output

    body = json.loads(put_route.calls.last.request.content)
    assert body == {"ordered_ids": ["cccc", "aaaa", "bbbb"]}
    assert "X-Idempotency-Key" in put_route.calls.last.request.headers


@respx.mock
def test_move_before(configured):
    respx.get("https://api.example.com/v1/reconciliations/cccc").mock(
        return_value=httpx.Response(200, json=RECON_C)
    )
    respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json=CHAIN_LIST)
    )
    put_route = respx.put(
        f"https://api.example.com/v1/accounts/{ACCOUNT_ID}/reconciliations/order"
    ).mock(return_value=httpx.Response(200, json=REORDER_RESPONSE))

    result = runner.invoke(cli_app, ["reconcile", "move", "cccc", "--before", "bbbb"])
    assert result.exit_code == 0, result.output

    body = json.loads(put_route.calls.last.request.content)
    assert body == {"ordered_ids": ["aaaa", "cccc", "bbbb"]}


@respx.mock
def test_move_after(configured):
    respx.get("https://api.example.com/v1/reconciliations/aaaa").mock(
        return_value=httpx.Response(200, json=RECON_A)
    )
    respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json=CHAIN_LIST)
    )
    put_route = respx.put(
        f"https://api.example.com/v1/accounts/{ACCOUNT_ID}/reconciliations/order"
    ).mock(return_value=httpx.Response(200, json=REORDER_RESPONSE))

    result = runner.invoke(cli_app, ["reconcile", "move", "aaaa", "--after", "bbbb"])
    assert result.exit_code == 0, result.output

    body = json.loads(put_route.calls.last.request.content)
    assert body == {"ordered_ids": ["bbbb", "aaaa", "cccc"]}


@respx.mock
def test_move_no_op(configured):
    respx.get("https://api.example.com/v1/reconciliations/aaaa").mock(
        return_value=httpx.Response(200, json=RECON_A)
    )
    respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json=CHAIN_LIST)
    )
    put_route = respx.put(f"https://api.example.com/v1/accounts/{ACCOUNT_ID}/reconciliations/order")

    result = runner.invoke(cli_app, ["reconcile", "move", "aaaa", "--to", "1"])
    assert result.exit_code == 0, result.output
    assert "No changes." in result.output
    assert put_route.call_count == 0


def test_move_no_flags_blocks_at_parse(configured):
    result = runner.invoke(cli_app, ["reconcile", "move", "aaaa"])
    assert result.exit_code != 0
    stripped = _strip_panel(result.output)
    assert "Pass exactly one of --to, --before, --after" in stripped


def test_move_multiple_flags_blocks_at_parse(configured):
    result = runner.invoke(cli_app, ["reconcile", "move", "aaaa", "--to", "1", "--before", "bbbb"])
    assert result.exit_code != 0
    stripped = _strip_panel(result.output)
    assert "mutually exclusive" in stripped


def test_move_to_zero_blocks_at_parse(configured):
    result = runner.invoke(cli_app, ["reconcile", "move", "aaaa", "--to", "0"])
    assert result.exit_code != 0
    stripped = _strip_panel(result.output)
    assert "Must be >= 1" in stripped


@respx.mock
def test_move_to_out_of_range_errors(configured):
    respx.get("https://api.example.com/v1/reconciliations/aaaa").mock(
        return_value=httpx.Response(200, json=RECON_A)
    )
    respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json=CHAIN_LIST)
    )
    result = runner.invoke(cli_app, ["reconcile", "move", "aaaa", "--to", "99"])
    assert result.exit_code != 0
    stripped = _strip_panel(result.output)
    assert "exceeds chain length" in stripped


@respx.mock
def test_move_before_unknown_peer_errors(configured):
    respx.get("https://api.example.com/v1/reconciliations/aaaa").mock(
        return_value=httpx.Response(200, json=RECON_A)
    )
    respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json=CHAIN_LIST)
    )
    result = runner.invoke(cli_app, ["reconcile", "move", "aaaa", "--before", "unknown"])
    assert result.exit_code != 0
    stripped = _strip_panel(result.output)
    assert "is not in account" in stripped
