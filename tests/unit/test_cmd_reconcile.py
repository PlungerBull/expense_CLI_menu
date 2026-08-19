import json
from uuid import UUID

import httpx
import respx
from typer.testing import CliRunner

from expense.commands.reconcile_cmd import app as reconcile_app
from tests.unit.helpers import make_cli_app, strip_panel

cli_app = make_cli_app(reconcile_app, "reconcile")

runner = CliRunner()


RECON_DRAFT_RESPONSE = {
    "id": "11111111-1111-1111-1111-111111111111",
    "user_id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
    "account_id": "22222222-2222-2222-2222-222222222222",
    "name": "Statement April 2026",
    "date_start": "2026-04-01T00:00:00Z",
    "date_end": "2026-04-30T23:59:59Z",
    # native cents only — the home-cent pair died with read-time conversion
    # (2026-08-05); reconciliations are single-account, so there is nothing to mix
    "beginning_balance_cents": 100000,
    "ending_balance_cents": 150000,
    "status": 1,
    # difference_cents replaced sort_order/beginning_balance_source/
    # chained_from_reconciliation_id in the 2026-08-06 de-chaining: it is
    # (ending − beginning) minus the assigned transactions, computed at read time
    "difference_cents": 0,
    "version": 1,
    "created_at": "2026-04-15T10:00:00Z",
    "updated_at": "2026-04-15T10:00:00Z",
    "deleted_at": None,
}

RECON_OFF_RESPONSE = {
    **RECON_DRAFT_RESPONSE,
    "id": "33333333-3333-3333-3333-333333333333",
    "difference_cents": -3500,
}

LIST_RESPONSE = {
    "items": [RECON_DRAFT_RESPONSE, RECON_OFF_RESPONSE],
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


@respx.mock
def test_list_happy_with_account_filter(configured):
    route = respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(
        cli_app,
        ["reconcile", "list", "--account-id", "22222222-2222-2222-2222-222222222222"],
    )
    assert result.exit_code == 0, result.output
    for header in (
        "Account",
        "Name",
        "Period",
        "Begin",
        "End",
        "Status",
        "Deleted",
        "Id",
    ):
        assert header in result.output
    assert "Source" not in result.output  # died with the 2026-08-06 de-chaining
    assert "Statement April 2026" in result.output
    assert "2026-04-01 → 2026-04-30" in result.output

    lines = result.output.splitlines()
    balanced_row = next(line for line in lines if RECON_DRAFT_RESPONSE["id"] in line)
    assert "draft" in balanced_row

    request = route.calls.last.request
    assert request.url.params.get("account_id") == "22222222-2222-2222-2222-222222222222"


@respx.mock
def test_list_renders_difference_column(configured):
    """The flat table always prints the number — 0.00 when the batch balances,
    the signed figure when it does not. No glyph translation: this table gets
    piped and eyeballed (Phase 3 sketch, the CLI half of option H)."""
    respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["reconcile", "list"])
    assert result.exit_code == 0, result.output
    assert "Diff" in result.output

    lines = result.output.splitlines()
    balanced = next(line for line in lines if RECON_DRAFT_RESPONSE["id"] in line)
    off = next(line for line in lines if RECON_OFF_RESPONSE["id"] in line)
    assert "0.00" in balanced
    assert "-35.00" in off


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
        cli_app,
        ["reconcile", "get", "11111111-1111-1111-1111-111111111111", "--limit", "1"],
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
def test_create_sends_both_required_fields(configured):
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
            "--beginning-balance",
            "100000",
            "--ending-balance",
            "150000",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Created:" in result.output
    assert "Next: attach transactions" in result.output

    body = json.loads(route.calls.last.request.content)
    UUID(body["id"])
    assert body["account_id"] == "22222222-2222-2222-2222-222222222222"
    assert body["name"] == "Statement April 2026"
    assert body["beginning_balance_cents"] == 100000
    assert body["ending_balance_cents"] == 150000
    assert body["date_start"].startswith("2026-04-01")
    # both retired by the de-chaining; the request schemas are extra="forbid"
    assert "beginning_balance_source" not in body
    assert "sort_order" not in body
    assert "X-Idempotency-Key" in route.calls.last.request.headers


def test_create_without_beginning_balance_blocks_at_parse(configured):
    """Omitting it used to mean \"chain from the previous batch\"; there is no
    derived mode left, so the engine 422s. Typer refuses before the HTTP call."""
    result = runner.invoke(
        cli_app,
        [
            "reconcile",
            "create",
            "--account-id",
            "acct",
            "--name",
            "X",
            "--date-start",
            "2026-04-01",
        ],
    )
    assert result.exit_code == 2  # Click usage error
    assert "--beginning-balance" in strip_panel(result.output)


def test_create_without_date_start_blocks_at_parse(configured):
    """date_start is what orders a batch since the de-chaining."""
    result = runner.invoke(
        cli_app,
        [
            "reconcile",
            "create",
            "--account-id",
            "acct",
            "--name",
            "X",
            "--beginning-balance",
            "100000",
        ],
    )
    assert result.exit_code == 2
    assert "--date-start" in strip_panel(result.output)


def test_create_rejects_retired_flags(configured):
    """--source and --sort-order are gone from the surface entirely."""
    for flag, value in (("--source", "chained"), ("--sort-order", "3")):
        result = runner.invoke(
            cli_app,
            [
                "reconcile",
                "create",
                "--account-id",
                "acct",
                "--name",
                "X",
                "--date-start",
                "2026-04-01",
                "--beginning-balance",
                "100000",
                flag,
                value,
            ],
        )
        assert result.exit_code == 2, flag
        assert "No such option" in strip_panel(result.output)


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


def test_update_rejects_retired_source_flag(configured):
    result = runner.invoke(
        cli_app,
        [
            "reconcile",
            "update",
            "11111111-1111-1111-1111-111111111111",
            "--source",
            "chained",
        ],
    )
    assert result.exit_code == 2
    assert "No such option" in strip_panel(result.output)


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


@respx.mock
def test_list_include_deleted_param(configured):
    deleted = {
        **RECON_OFF_RESPONSE,
        "id": "99999999-9999-9999-9999-999999999999",
        "deleted_at": "2026-06-01T09:00:00Z",
    }
    body = {"items": [RECON_DRAFT_RESPONSE, deleted], "total": 2, "limit": 50, "offset": 0}
    route = respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json=body)
    )
    result = runner.invoke(cli_app, ["reconcile", "list", "--include-deleted", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == body
    assert route.calls.last.request.url.params.get("include_deleted") == "true"


@respx.mock
def test_list_resolves_account_name_from_live_accounts(configured):
    """The Account column joins account_id against the live accounts list."""
    respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    accounts_route = respx.get("https://api.example.com/v1/accounts").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [{"id": RECON_DRAFT_RESPONSE["account_id"], "name": "BCP Soles"}],
                "total": 1,
                "limit": 200,
                "offset": 0,
            },
        )
    )
    result = runner.invoke(cli_app, ["reconcile", "list"])
    assert result.exit_code == 0, result.output
    assert accounts_route.called
    assert "BCP Soles" in result.output


@respx.mock
def test_list_unresolvable_account_degrades_to_short_id(configured):
    """A reference list the engine won't serve must not break the table."""
    respx.get("https://api.example.com/v1/reconciliations").mock(
        return_value=httpx.Response(200, json=LIST_RESPONSE)
    )
    result = runner.invoke(cli_app, ["reconcile", "list"])
    assert result.exit_code == 0, result.output
    assert "22222222" in result.output
    assert "BCP Soles" not in result.output
