import json
import re
from uuid import UUID

import httpx
import pytest
import respx
from typer.testing import CliRunner

from expense import config as config_module
from expense.cache import db as cache_db
from expense.cache import state as cache_state
from expense.commands.reconcile_cmd import app as reconcile_app
from tests.unit.helpers import insert_reconciliation, insert_transaction, make_cli_app, sync_payload

cli_app = make_cli_app(reconcile_app, "reconcile")

runner = CliRunner()


_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[mGKH]")


def _strip_panel(output: str) -> str:
    no_ansi = _ANSI_ESCAPE_RE.sub("", output)
    no_box = "".join(c for c in no_ansi if c not in "│╭╮╰╯─\n\t")
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
def cache_populated(configured):
    cfg = config_module.ensure_loaded()
    conn = cache_db.connect()
    try:
        insert_reconciliation(conn, {**RECON_DRAFT_RESPONSE, "user_id": "u1"})
        insert_reconciliation(conn, {**RECON_MANUAL_RESPONSE, "user_id": "u1"})

        insert_transaction(
            conn,
            {
                "id": "tx-001",
                "user_id": "u1",
                "title": "Lunch",
                "amount_cents": -1500,
                "account_id": RECON_DRAFT_RESPONSE["account_id"],
                "category_id": "cat-food",
                "reconciliation_id": RECON_DRAFT_RESPONSE["id"],
                "date": "2026-04-15",
                "version": 1,
                "updated_at": "2026-04-15T12:05:00Z",
                "created_at": "2026-04-15T12:05:00Z",
                "deleted_at": None,
            },
        )
        insert_transaction(
            conn,
            {
                "id": "tx-002",
                "user_id": "u1",
                "title": "Coffee",
                "amount_cents": -500,
                "account_id": RECON_DRAFT_RESPONSE["account_id"],
                "category_id": "cat-food",
                "reconciliation_id": RECON_DRAFT_RESPONSE["id"],
                "date": "2026-04-14",
                "version": 1,
                "updated_at": "2026-04-14T08:00:00Z",
                "created_at": "2026-04-14T08:00:00Z",
                "deleted_at": None,
            },
        )
        insert_transaction(
            conn,
            {
                "id": "tx-003",
                "user_id": "u1",
                "title": "Cab",
                "amount_cents": -2000,
                "account_id": RECON_DRAFT_RESPONSE["account_id"],
                "category_id": "cat-transport",
                "reconciliation_id": RECON_DRAFT_RESPONSE["id"],
                "date": "2026-04-13",
                "version": 1,
                "updated_at": "2026-04-13T09:00:00Z",
                "created_at": "2026-04-13T09:00:00Z",
                "deleted_at": None,
            },
        )

        cache_state.write_identity(
            conn,
            user_id="u1",
            client_id=str(cfg.client_id),
            engine_url=cfg.engine_url,
            token_fingerprint=cache_state.token_fingerprint(cfg.token),
        )
        cache_state.write_token(conn, "tok-populated")
    finally:
        conn.close()
    yield


@respx.mock
def test_list_happy_with_account_filter(configured):
    route = respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(
        cli_app,
        ["--no-cache", "reconcile", "list", "--account-id", "22222222-2222-2222-2222-222222222222"],
    )
    assert result.exit_code == 0, result.output
    for header in (
        "Account",
        "Name",
        "Period",
        "Begin",
        "End",
        "Source",
        "Status",
        "Deleted",
        "Id",
    ):
        assert header in result.output
    assert "Statement April 2026" in result.output
    assert "2026-04-01 → 2026-04-30" in result.output

    lines = result.output.splitlines()
    chained_row = next(line for line in lines if RECON_DRAFT_RESPONSE["id"] in line)
    assert "chained" in chained_row
    assert "draft" in chained_row
    manual_row = next(line for line in lines if RECON_MANUAL_RESPONSE["id"] in line)
    assert "manual" in manual_row

    request = route.calls.last.request
    assert request.url.params.get("account_id") == "22222222-2222-2222-2222-222222222222"


@respx.mock
def test_list_empty(configured):
    respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json={"items": [], "total": 0, "limit": 50, "offset": 0})
    )
    result = runner.invoke(cli_app, ["--no-cache", "reconcile", "list"])
    assert result.exit_code == 0, result.output
    assert "(no reconciliations)" in result.output


@respx.mock
def test_list_json_passthrough(configured):
    respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["--no-cache", "reconcile", "list", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == LIST_RESPONSE


@respx.mock
def test_get_with_transactions_window(configured):
    route = respx.get(
        "https://api.example.com/v1/reconciliations/11111111-1111-1111-1111-111111111111"
    ).mock(return_value=httpx.Response(200, json=DETAIL_WITH_TRANSACTIONS))
    result = runner.invoke(
        cli_app,
        ["--no-cache", "reconcile", "get", "11111111-1111-1111-1111-111111111111", "--limit", "1"],
    )
    assert result.exit_code == 0, result.output
    assert "Statement April 2026" in result.output
    assert "Transactions:" in result.output
    assert "Lunch" in result.output
    assert "more transactions" in result.output
    assert "transactions list --reconciliation" in result.output

    request = route.calls.last.request
    assert request.url.params.get("limit") == "1"
    assert request.url.params.get("debit_as_negative") == "true"


@respx.mock
def test_get_empty_transactions_hint(configured):
    respx.get(
        "https://api.example.com/v1/reconciliations/11111111-1111-1111-1111-111111111111"
    ).mock(return_value=httpx.Response(200, json=DETAIL_EMPTY_TRANSACTIONS))
    result = runner.invoke(
        cli_app, ["--no-cache", "reconcile", "get", "11111111-1111-1111-1111-111111111111"]
    )
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
    result = runner.invoke(cli_app, ["--no-cache", "reconcile", "get", "missing"])
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
            "--account-id",
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
            "--account-id",
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
            "--account-id",
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
            "--account-id",
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


# ---------------------------------------------------------------------------
# Phase 3b: reorder via $EDITOR
# ---------------------------------------------------------------------------


@respx.mock
def test_reorder_json_skips_editor_and_no_http(configured, monkeypatch):
    respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json=CHAIN_LIST)
    )
    put_route = respx.put(f"https://api.example.com/v1/accounts/{ACCOUNT_ID}/reconciliations/order")

    called: list[bool] = []

    def fake_edit_text(*args, **kwargs):
        called.append(True)
        return None

    monkeypatch.setattr("expense._editor.edit_text", fake_edit_text)

    result = runner.invoke(cli_app, ["reconcile", "reorder", "--account-id", ACCOUNT_ID, "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {"ordered_ids": ["aaaa", "bbbb", "cccc"]}
    assert called == []
    assert put_route.call_count == 0


@respx.mock
def test_reorder_empty_chain(configured, monkeypatch):
    respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json={"items": [], "total": 0, "limit": 200, "offset": 0})
    )
    monkeypatch.setattr("expense._editor.edit_text", lambda *a, **k: None)

    result = runner.invoke(cli_app, ["reconcile", "reorder", "--account-id", ACCOUNT_ID])
    assert result.exit_code == 0, result.output
    assert "(no reconciliations to reorder)" in result.output


@respx.mock
def test_reorder_aborts_when_editor_returns_none(configured, monkeypatch):
    respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json=CHAIN_LIST)
    )
    put_route = respx.put(f"https://api.example.com/v1/accounts/{ACCOUNT_ID}/reconciliations/order")
    monkeypatch.setattr("expense._editor.edit_text", lambda *a, **k: None)

    result = runner.invoke(cli_app, ["reconcile", "reorder", "--account-id", ACCOUNT_ID])
    assert result.exit_code == 0, result.output
    assert "Aborted." in result.output
    assert put_route.call_count == 0


@respx.mock
def test_reorder_no_changes(configured, monkeypatch):
    respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json=CHAIN_LIST)
    )
    put_route = respx.put(f"https://api.example.com/v1/accounts/{ACCOUNT_ID}/reconciliations/order")

    same_order = "aaaa  2026-01-01..2026-01-31  Jan\nbbbb  ...  Feb\ncccc  ...  Mar\n"
    monkeypatch.setattr("expense._editor.edit_text", lambda *a, **k: same_order)

    result = runner.invoke(cli_app, ["reconcile", "reorder", "--account-id", ACCOUNT_ID])
    assert result.exit_code == 0, result.output
    assert "No changes." in result.output
    assert put_route.call_count == 0


@respx.mock
def test_reorder_happy_path_sends_correct_body(configured, monkeypatch):
    respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json=CHAIN_LIST)
    )
    put_route = respx.put(
        f"https://api.example.com/v1/accounts/{ACCOUNT_ID}/reconciliations/order"
    ).mock(return_value=httpx.Response(200, json=REORDER_RESPONSE))

    edited = "# header\ncccc  ...  Mar\naaaa  ...  Jan\nbbbb  ...  Feb\n"
    monkeypatch.setattr("expense._editor.edit_text", lambda *a, **k: edited)

    result = runner.invoke(cli_app, ["reconcile", "reorder", "--account-id", ACCOUNT_ID])
    assert result.exit_code == 0, result.output
    assert "1 chained beginning balance(s) recalculated." in result.output

    body = json.loads(put_route.calls.last.request.content)
    assert body == {"ordered_ids": ["cccc", "aaaa", "bbbb"]}
    assert "X-Idempotency-Key" in put_route.calls.last.request.headers


@respx.mock
def test_reorder_unknown_id_in_editor_blocks(configured, monkeypatch):
    respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json=CHAIN_LIST)
    )
    put_route = respx.put(f"https://api.example.com/v1/accounts/{ACCOUNT_ID}/reconciliations/order")

    edited = "aaaa  ...  Jan\nbbbb  ...  Feb\nzzzz  smuggled\n"
    monkeypatch.setattr("expense._editor.edit_text", lambda *a, **k: edited)

    result = runner.invoke(cli_app, ["reconcile", "reorder", "--account-id", ACCOUNT_ID])
    assert result.exit_code != 0
    stripped = _strip_panel(result.output)
    assert "Unknown reconciliation id" in stripped
    assert put_route.call_count == 0


@respx.mock
def test_reorder_duplicate_id_in_editor_blocks(configured, monkeypatch):
    respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json=CHAIN_LIST)
    )
    put_route = respx.put(f"https://api.example.com/v1/accounts/{ACCOUNT_ID}/reconciliations/order")

    edited = "aaaa  ...\nbbbb  ...\naaaa  duplicate\ncccc  ...\n"
    monkeypatch.setattr("expense._editor.edit_text", lambda *a, **k: edited)

    result = runner.invoke(cli_app, ["reconcile", "reorder", "--account-id", ACCOUNT_ID])
    assert result.exit_code != 0
    stripped = _strip_panel(result.output)
    assert "Duplicate id" in stripped
    assert put_route.call_count == 0


@respx.mock
def test_reorder_missing_id_in_editor_blocks(configured, monkeypatch):
    respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json=CHAIN_LIST)
    )
    put_route = respx.put(f"https://api.example.com/v1/accounts/{ACCOUNT_ID}/reconciliations/order")

    edited = "aaaa  ...\nbbbb  ...\n"  # missing cccc
    monkeypatch.setattr("expense._editor.edit_text", lambda *a, **k: edited)

    result = runner.invoke(cli_app, ["reconcile", "reorder", "--account-id", ACCOUNT_ID])
    assert result.exit_code != 0
    stripped = _strip_panel(result.output)
    assert "Missing ids" in stripped
    assert put_route.call_count == 0


@respx.mock
def test_reorder_year_filter(configured, monkeypatch):
    chain = {
        "items": [
            {
                **RECON_A,
                "id": "old-1",
                "date_start": "2024-01-01T00:00:00Z",
                "date_end": "2024-01-31T23:59:59Z",
            },
            {
                **RECON_A,
                "id": "new-1",
                "date_start": "2025-01-01T00:00:00Z",
                "date_end": "2025-01-31T23:59:59Z",
            },
            {
                **RECON_A,
                "id": "new-2",
                "date_start": "2025-02-01T00:00:00Z",
                "date_end": "2025-02-28T23:59:59Z",
            },
        ],
        "total": 3,
        "limit": 200,
        "offset": 0,
    }
    respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json=chain)
    )

    result = runner.invoke(
        cli_app,
        ["reconcile", "reorder", "--account-id", ACCOUNT_ID, "--year", "2025", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {"ordered_ids": ["new-1", "new-2"]}


def test_list_replica_path(cache_populated):
    with respx.mock(base_url="https://api.example.com", assert_all_called=False) as router:
        recon_route = router.get("/v1/reconciliations")
        result = runner.invoke(cli_app, ["reconcile", "list"])
    assert result.exit_code == 0, result.output
    assert "Statement April 2026" in result.output
    assert not recon_route.called


def test_list_replica_account_filter(cache_populated):
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(
            cli_app,
            ["reconcile", "list", "--account-id", RECON_DRAFT_RESPONSE["account_id"], "--json"],
        )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["total"] == 2
    assert all(
        item["account_id"] == RECON_DRAFT_RESPONSE["account_id"] for item in payload["items"]
    )


def test_get_replica_path_with_embedded_transactions(cache_populated):
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(
            cli_app,
            ["reconcile", "get", RECON_DRAFT_RESPONSE["id"], "--json"],
        )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["id"] == RECON_DRAFT_RESPONSE["id"]
    assert payload["transactions_total"] == 3
    assert len(payload["transactions"]) == 3
    assert [t["id"] for t in payload["transactions"]] == ["tx-001", "tx-002", "tx-003"]
    assert payload["transactions_truncated"] is False


def test_get_replica_path_with_pagination(cache_populated):
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(
            cli_app,
            ["reconcile", "get", RECON_DRAFT_RESPONSE["id"], "--limit", "1", "--json"],
        )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["transactions_total"] == 3
    assert payload["transactions_limit"] == 1
    assert payload["transactions_offset"] == 0
    assert len(payload["transactions"]) == 1
    assert payload["transactions_truncated"] is True


def test_get_replica_not_found(cache_populated):
    with respx.mock(base_url="https://api.example.com"):
        result = runner.invoke(cli_app, ["reconcile", "get", "missing"])
    assert result.exit_code == 1
    assert "NOT_FOUND" in result.output


@respx.mock
def test_list_auto_cold_start_when_cache_empty(configured):
    sync_route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(
            200, json=sync_payload(reconciliations=[{**RECON_DRAFT_RESPONSE, "user_id": "u1"}])
        )
    )
    recon_route = respx.get("https://api.example.com/v1/reconciliations")
    result = runner.invoke(cli_app, ["reconcile", "list"])
    assert result.exit_code == 0, result.output
    assert sync_route.called
    assert not recon_route.called


@respx.mock
def test_create_triggers_post_write_sync(cache_populated):
    """Step 7b.3: a successful reconcile write fires a follow-up GET /sync."""
    respx.post("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(201, json=RECON_DRAFT_RESPONSE)
    )
    sync_route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(
            200, json=sync_payload(reconciliations=[{**RECON_DRAFT_RESPONSE, "user_id": "u1"}])
        )
    )
    result = runner.invoke(
        cli_app,
        ["reconcile", "create", "--account-id", "acct-id", "--name", "April"],
    )
    assert result.exit_code == 0, result.output
    assert sync_route.called
