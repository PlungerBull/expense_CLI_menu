"""respx-mocked apply tests + CLI dry-run for `expense import`."""

import json

import httpx
import respx
from typer.testing import CliRunner

from expense import config as config_module
from expense.commands import import_cmd
from expense.http import ExpenseClient
from expense.import_ import apply as apply_mod
from expense.import_ import plan as plan_mod
from expense.import_.parse import ParsedRow
from expense.import_.reader import RawRow, SheetData
from tests.unit.helpers import ENGINE_URL as BASE
from tests.unit.helpers import make_cli_app, sync_payload

runner = CliRunner()


def _prow(line: int, **over: object) -> ParsedRow:
    base = dict(
        line=line,
        title="Groomers",
        category="WANTS",
        hashtag="Salidas",
        date_iso="2022-12-01",
        amount_cents=-4400,
        currency="PEN",
        account="BCP PEN",
        description=None,
        exchange_rate=None,
    )
    base.update(over)
    return ParsedRow(**base)  # type: ignore[arg-type]


def _plan(rows: list[ParsedRow]) -> plan_mod.ImportPlan:
    return plan_mod.build_plan(rows, [])


def _mock_existing(*, accounts: list, categories: list, hashtags: list) -> None:
    respx.get(f"{BASE}/v1/accounts").mock(return_value=httpx.Response(200, json=accounts))
    respx.get(f"{BASE}/v1/categories").mock(
        return_value=httpx.Response(200, json={"items": categories})
    )
    respx.get(f"{BASE}/v1/hashtags").mock(
        return_value=httpx.Response(200, json={"items": hashtags})
    )


@respx.mock
def test_apply_reuses_existing_and_creates_rest(configured):
    rows = [
        _prow(2),  # BCP PEN reused; WANTS + Salidas created
        _prow(
            3,
            account="BCP USD",
            currency="USD",
            amount_cents=-10000,
            exchange_rate=3.68,
            category="PERROS",
            hashtag="Viajes",
        ),
    ]
    plan = _plan(rows)
    _mock_existing(
        accounts=[
            {"id": "acc-pen", "name": "BCP PEN", "currency_code": "PEN"},
            {"id": "acc-usd", "name": "BCP USD", "currency_code": "USD"},
        ],
        categories=[{"id": "cat-susc", "name": "Suscripciones"}],
        hashtags=[],
    )
    acc_route = respx.post(f"{BASE}/v1/accounts").mock(
        return_value=httpx.Response(201, json={"id": "new-acc"})
    )
    respx.post(f"{BASE}/v1/categories").mock(return_value=httpx.Response(201, json={"id": "c"}))
    respx.post(f"{BASE}/v1/hashtags").mock(return_value=httpx.Response(201, json={"id": "h"}))
    batch_route = respx.post(f"{BASE}/v1/transactions/batch").mock(
        return_value=httpx.Response(201, json={"created": []})
    )

    cfg = config_module.ensure_loaded()
    with ExpenseClient(cfg) as client:
        res = apply_mod.resolve_or_create(client, plan)
        result = apply_mod.apply_plan(client, plan, res, chunk_size=200)

    assert (res.accounts_reused, res.accounts_created) == (2, 0)
    assert not acc_route.called
    assert res.categories_created == 2  # WANTS, PERROS
    assert res.hashtags_created == 2  # Salidas, Viajes

    body = json.loads(batch_route.calls.last.request.content)
    items = body["transactions"]
    assert len(items) == 2
    pen = next(i for i in items if i["account_id"] == "acc-pen")
    usd = next(i for i in items if i["account_id"] == "acc-usd")
    assert "exchange_rate" not in pen
    assert usd["exchange_rate"] == 3.68
    assert len(pen["hashtag_ids"]) == 1
    assert pen["id"] == plan_mod.tx_id_for(rows[0])  # deterministic
    assert result.tx_created == 2


def _conflict() -> httpx.Response:
    return httpx.Response(
        409, json={"error": {"code": "CONFLICT", "message": "id exists", "fields": None}}
    )


@respx.mock
def test_batch_409_is_non_fatal(configured):
    plan = _plan([_prow(2)])
    _mock_existing(
        accounts=[{"id": "acc-pen", "name": "BCP PEN", "currency_code": "PEN"}],
        categories=[],
        hashtags=[],
    )
    respx.post(f"{BASE}/v1/categories").mock(return_value=httpx.Response(201, json={"id": "c"}))
    respx.post(f"{BASE}/v1/hashtags").mock(return_value=httpx.Response(201, json={"id": "h"}))
    batch_route = respx.post(f"{BASE}/v1/transactions/batch").mock(
        side_effect=lambda request: _conflict()
    )

    cfg = config_module.ensure_loaded()
    with ExpenseClient(cfg) as client:
        res = apply_mod.resolve_or_create(client, plan)
        result = apply_mod.apply_plan(client, plan, res)

    assert result.tx_created == 0
    assert result.tx_skipped_existing == 1
    assert result.tx_failed == 0
    assert batch_route.call_count == 2  # batch 409 → singleton retry 409


@respx.mock
def test_chunk_409_falls_back_to_per_row_and_imports_new_rows(configured):
    """Appending rows to an already-imported sheet must import the new rows (backlog 1.3)."""
    plan = _plan([_prow(2), _prow(3, amount_cents=-5500)])
    _mock_existing(
        accounts=[{"id": "acc-pen", "name": "BCP PEN", "currency_code": "PEN"}],
        categories=[],
        hashtags=[],
    )
    respx.post(f"{BASE}/v1/categories").mock(return_value=httpx.Response(201, json={"id": "c"}))
    respx.post(f"{BASE}/v1/hashtags").mock(return_value=httpx.Response(201, json={"id": "h"}))
    batch_route = respx.post(f"{BASE}/v1/transactions/batch").mock(
        side_effect=[_conflict(), _conflict(), httpx.Response(201, json={"created": []})]
    )

    cfg = config_module.ensure_loaded()
    with ExpenseClient(cfg) as client:
        res = apply_mod.resolve_or_create(client, plan)
        result = apply_mod.apply_plan(client, plan, res)

    assert result.tx_skipped_existing == 1
    assert result.tx_created == 1
    assert result.tx_failed == 0
    assert batch_route.call_count == 3  # one batch + two singletons
    singleton_sizes = [
        len(json.loads(c.request.content)["transactions"]) for c in batch_route.calls
    ][1:]
    assert singleton_sizes == [1, 1]


@respx.mock
def test_per_row_fallback_reports_non_409_failure(configured):
    plan = _plan([_prow(2), _prow(3, amount_cents=-5500)])
    _mock_existing(
        accounts=[{"id": "acc-pen", "name": "BCP PEN", "currency_code": "PEN"}],
        categories=[],
        hashtags=[],
    )
    respx.post(f"{BASE}/v1/categories").mock(return_value=httpx.Response(201, json={"id": "c"}))
    respx.post(f"{BASE}/v1/hashtags").mock(return_value=httpx.Response(201, json={"id": "h"}))
    respx.post(f"{BASE}/v1/transactions/batch").mock(
        side_effect=[
            _conflict(),
            _conflict(),
            httpx.Response(
                422, json={"error": {"code": "VALIDATION_ERROR", "message": "bad", "fields": {}}}
            ),
        ]
    )

    cfg = config_module.ensure_loaded()
    with ExpenseClient(cfg) as client:
        res = apply_mod.resolve_or_create(client, plan)
        result = apply_mod.apply_plan(client, plan, res)

    assert result.tx_skipped_existing == 1
    assert result.tx_failed == 1
    failed_id = plan.tx_ids[3]
    # sheet-line context prefixed, engine text via format_error (backlog 6.3a)
    assert result.failures == [(0, f"sheet line 3, id {failed_id}: VALIDATION_ERROR — bad")]


@respx.mock
def test_per_row_fallback_connection_error_stops_run(configured):
    plan = _plan([_prow(line, amount_cents=-100 * line) for line in (2, 3, 4, 5)])
    _mock_existing(
        accounts=[{"id": "acc-pen", "name": "BCP PEN", "currency_code": "PEN"}],
        categories=[],
        hashtags=[],
    )
    respx.post(f"{BASE}/v1/categories").mock(return_value=httpx.Response(201, json={"id": "c"}))
    respx.post(f"{BASE}/v1/hashtags").mock(return_value=httpx.Response(201, json={"id": "h"}))
    batch_route = respx.post(f"{BASE}/v1/transactions/batch").mock(
        side_effect=[
            _conflict(),
            httpx.Response(201, json={"created": []}),
            httpx.ConnectError("down"),
        ]
    )

    cfg = config_module.ensure_loaded()
    with ExpenseClient(cfg) as client:
        res = apply_mod.resolve_or_create(client, plan)
        result = apply_mod.apply_plan(client, plan, res, chunk_size=2)

    assert result.tx_created == 1  # first singleton landed
    assert result.tx_failed == 3  # unsent tail of chunk 0 + the never-sent chunk 1
    assert result.tx_skipped_existing == 0
    assert batch_route.call_count == 3  # batch, singleton 201, singleton ConnectError
    assert len(result.failures) == 1
    assert "CONNECTION_ERROR: could not reach engine" in result.failures[0][1]
    assert "rows from sheet line 3 on were not sent" in result.failures[0][1]


@respx.mock
def test_chunk_422_falls_back_to_per_row_isolating_bad_rows(configured):
    """One invalid row must not sink its whole chunk, and must name its sheet line (backlog 3.9)."""
    plan = _plan([_prow(2), _prow(3, amount_cents=-5500)])
    _mock_existing(
        accounts=[{"id": "acc-pen", "name": "BCP PEN", "currency_code": "PEN"}],
        categories=[],
        hashtags=[],
    )
    respx.post(f"{BASE}/v1/categories").mock(return_value=httpx.Response(201, json={"id": "c"}))
    respx.post(f"{BASE}/v1/hashtags").mock(return_value=httpx.Response(201, json={"id": "h"}))
    batch_route = respx.post(f"{BASE}/v1/transactions/batch").mock(
        side_effect=[
            httpx.Response(
                422, json={"error": {"code": "VALIDATION_ERROR", "message": "bad", "fields": {}}}
            ),
            httpx.Response(201, json={"created": []}),
            httpx.Response(
                422, json={"error": {"code": "VALIDATION_ERROR", "message": "bad", "fields": {}}}
            ),
        ]
    )

    cfg = config_module.ensure_loaded()
    with ExpenseClient(cfg) as client:
        res = apply_mod.resolve_or_create(client, plan)
        result = apply_mod.apply_plan(client, plan, res)

    assert result.tx_created == 1  # the valid row still landed
    assert result.tx_failed == 1
    assert batch_route.call_count == 3  # one batch + two singletons
    assert "sheet line 3" in result.failures[0][1]


@respx.mock
def test_row_failure_keeps_engine_fields_detail(configured):
    """A 422's per-field detail must survive into the failure line — never
    reformat lossily (backlog 6.3a)."""
    plan = _plan([_prow(2), _prow(3, amount_cents=0)])
    _mock_existing(
        accounts=[{"id": "acc-pen", "name": "BCP PEN", "currency_code": "PEN"}],
        categories=[],
        hashtags=[],
    )
    respx.post(f"{BASE}/v1/categories").mock(return_value=httpx.Response(201, json={"id": "c"}))
    respx.post(f"{BASE}/v1/hashtags").mock(return_value=httpx.Response(201, json={"id": "h"}))
    respx.post(f"{BASE}/v1/transactions/batch").mock(
        side_effect=[
            _conflict(),
            _conflict(),
            httpx.Response(
                422,
                json={
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "Invalid input.",
                        "fields": {"amount_cents": "Must not be zero."},
                    }
                },
            ),
        ]
    )

    cfg = config_module.ensure_loaded()
    with ExpenseClient(cfg) as client:
        res = apply_mod.resolve_or_create(client, plan)
        result = apply_mod.apply_plan(client, plan, res)

    assert result.tx_failed == 1
    message = result.failures[0][1]
    assert "sheet line 3" in message  # the row is findable in the workbook
    assert "amount_cents: Must not be zero." in message  # fields preserved


@respx.mock
def test_chunk_level_auth_failure_reports_line_range_without_per_row_hammering(configured):
    """A non-409/422 chunk error fails once with the sheet line range (backlog 3.9)."""
    plan = _plan([_prow(2), _prow(3, amount_cents=-5500)])
    _mock_existing(
        accounts=[{"id": "acc-pen", "name": "BCP PEN", "currency_code": "PEN"}],
        categories=[],
        hashtags=[],
    )
    respx.post(f"{BASE}/v1/categories").mock(return_value=httpx.Response(201, json={"id": "c"}))
    respx.post(f"{BASE}/v1/hashtags").mock(return_value=httpx.Response(201, json={"id": "h"}))
    batch_route = respx.post(f"{BASE}/v1/transactions/batch").mock(
        return_value=httpx.Response(
            403, json={"error": {"code": "FORBIDDEN", "message": "nope", "fields": None}}
        )
    )

    cfg = config_module.ensure_loaded()
    with ExpenseClient(cfg) as client:
        res = apply_mod.resolve_or_create(client, plan)
        result = apply_mod.apply_plan(client, plan, res)

    assert result.tx_failed == 2
    assert batch_route.call_count == 1  # every row would 403 identically — no fallback
    assert result.failures == [(0, "sheet lines 2-3: FORBIDDEN — nope")]


@respx.mock
def test_chunking_splits_batches(configured):
    rows = [_prow(line) for line in range(2, 452)]  # 450 distinct rows
    plan = _plan(rows)
    _mock_existing(
        accounts=[{"id": "acc-pen", "name": "BCP PEN", "currency_code": "PEN"}],
        categories=[],
        hashtags=[],
    )
    respx.post(f"{BASE}/v1/categories").mock(return_value=httpx.Response(201, json={"id": "c"}))
    respx.post(f"{BASE}/v1/hashtags").mock(return_value=httpx.Response(201, json={"id": "h"}))
    batch_route = respx.post(f"{BASE}/v1/transactions/batch").mock(
        return_value=httpx.Response(201, json={"created": []})
    )

    cfg = config_module.ensure_loaded()
    with ExpenseClient(cfg) as client:
        res = apply_mod.resolve_or_create(client, plan)
        apply_mod.apply_plan(client, plan, res, chunk_size=200)

    sizes = [len(json.loads(c.request.content)["transactions"]) for c in batch_route.calls]
    assert sizes == [200, 200, 50]


@respx.mock
def test_batch_connection_failure_marks_remaining_failed_and_stops(configured):
    plan = _plan([_prow(2), _prow(3), _prow(4)])
    _mock_existing(
        accounts=[{"id": "acc-pen", "name": "BCP PEN", "currency_code": "PEN"}],
        categories=[],
        hashtags=[],
    )
    respx.post(f"{BASE}/v1/categories").mock(return_value=httpx.Response(201, json={"id": "c"}))
    respx.post(f"{BASE}/v1/hashtags").mock(return_value=httpx.Response(201, json={"id": "h"}))
    batch_route = respx.post(f"{BASE}/v1/transactions/batch").mock(
        side_effect=[httpx.Response(201, json={"created": []}), httpx.ConnectError("down")]
    )

    cfg = config_module.ensure_loaded()
    with ExpenseClient(cfg) as client:
        res = apply_mod.resolve_or_create(client, plan)
        result = apply_mod.apply_plan(client, plan, res, chunk_size=1)

    assert result.tx_created == 1
    assert result.tx_failed == 2  # the failing chunk plus the unsent one
    assert result.failures and result.failures[0][0] == 1
    assert "could not reach engine" in result.failures[0][1]
    assert batch_route.call_count == 2  # loop broke; third chunk never sent


# --- CLI surface -----------------------------------------------------------

_HEADERS = [
    "Descripcion",
    "CATEGORY",
    "HASHTAG",
    "Fecha",
    "Monto",
    "Cuenta",
    "T.C.",
    "Moneda",
    "Solarizado",
    "Estado Cuenta",
    "Notas",
]
_CELLS = ["Groomers", "WANTS", "Salidas", 44896, -44, "BCP PEN", "None", "PEN", -44, "None", "None"]


cli_app = make_cli_app(commands={"import": import_cmd.run_import})


@respx.mock
def test_dry_run_writes_nothing(configured, monkeypatch):
    monkeypatch.setattr(
        import_cmd,
        "read_workbook",
        lambda path, **k: SheetData(headers=_HEADERS, rows=[RawRow(2, list(_CELLS))]),
    )
    result = runner.invoke(cli_app, ["import", "whatever.xlsx"])
    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert not respx.calls  # nothing hit the engine


@respx.mock
def test_dry_run_json_emits_plan(configured, monkeypatch):
    """--json emits the raw plan (and suppresses the human dry-run trailer)."""
    monkeypatch.setattr(
        import_cmd,
        "read_workbook",
        lambda path, **k: SheetData(headers=_HEADERS, rows=[RawRow(2, list(_CELLS))]),
    )
    result = runner.invoke(cli_app, ["import", "whatever.xlsx", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)  # pure JSON, no trailer mixed in
    assert payload["valid_rows"] == 1
    assert payload["skipped"] == []
    assert payload["accounts"] == [{"name": "BCP PEN", "currency": "PEN"}]
    assert set(payload["categories"]) == {"WANTS"}
    assert set(payload["hashtags"]) == {"Salidas"}
    assert "Dry run" not in result.output
    assert not respx.calls


@respx.mock
def test_apply_happy_path_syncs_cache(configured_synced, monkeypatch):
    """`import --apply` wires cache_after_write: the post-write delta sync fires."""
    monkeypatch.setattr(
        import_cmd,
        "read_workbook",
        lambda path, **k: SheetData(headers=_HEADERS, rows=[RawRow(2, list(_CELLS))]),
    )
    _mock_existing(
        accounts=[{"id": "acc-pen", "name": "BCP PEN", "currency_code": "PEN"}],
        categories=[],
        hashtags=[],
    )
    respx.post(f"{BASE}/v1/categories").mock(return_value=httpx.Response(201, json={"id": "c"}))
    respx.post(f"{BASE}/v1/hashtags").mock(return_value=httpx.Response(201, json={"id": "h"}))
    respx.post(f"{BASE}/v1/transactions/batch").mock(
        return_value=httpx.Response(201, json={"created": []})
    )
    sync_route = respx.get(f"{BASE}/v1/sync").mock(
        return_value=httpx.Response(200, json=sync_payload())
    )

    result = runner.invoke(cli_app, ["import", "whatever.xlsx", "--apply"])
    assert result.exit_code == 0, result.output
    assert "Transactions: created 1" in result.output
    assert sync_route.called  # cache_after_write ran (import_cmd.py:145)
    assert "Cache refresh failed" not in result.output  # and it succeeded


@respx.mock
def test_apply_json_result_with_failures(configured, monkeypatch):
    """--apply --json emits the raw result envelope and still exits 1 on failures."""
    second_cells = list(_CELLS)
    second_cells[4] = -55  # different amount → distinct transaction
    monkeypatch.setattr(
        import_cmd,
        "read_workbook",
        lambda path, **k: SheetData(
            headers=_HEADERS, rows=[RawRow(2, list(_CELLS)), RawRow(3, second_cells)]
        ),
    )
    _mock_existing(
        accounts=[{"id": "acc-pen", "name": "BCP PEN", "currency_code": "PEN"}],
        categories=[],
        hashtags=[],
    )
    respx.post(f"{BASE}/v1/categories").mock(return_value=httpx.Response(201, json={"id": "c"}))
    respx.post(f"{BASE}/v1/hashtags").mock(return_value=httpx.Response(201, json={"id": "h"}))
    respx.post(f"{BASE}/v1/transactions/batch").mock(
        side_effect=[httpx.Response(201, json={"created": []}), httpx.ConnectError("down")]
    )

    result = runner.invoke(
        cli_app, ["import", "whatever.xlsx", "--apply", "--chunk-size", "1", "--json"]
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["accounts_reused"] == 1 and payload["accounts_created"] == 0
    assert payload["tx_created"] == 1 and payload["tx_failed"] == 1
    assert payload["failures"][0]["chunk"] == 1
    assert "could not reach engine" in payload["failures"][0]["error"]


@respx.mock
def test_apply_cli_reports_summary_on_connection_failure(configured, monkeypatch):
    """A mid-run connection drop still renders the summary and exits 1 (backlog 2.2)."""
    second_cells = list(_CELLS)
    second_cells[4] = -55  # different amount → distinct transaction
    monkeypatch.setattr(
        import_cmd,
        "read_workbook",
        lambda path, **k: SheetData(
            headers=_HEADERS, rows=[RawRow(2, list(_CELLS)), RawRow(3, second_cells)]
        ),
    )
    _mock_existing(
        accounts=[{"id": "acc-pen", "name": "BCP PEN", "currency_code": "PEN"}],
        categories=[],
        hashtags=[],
    )
    respx.post(f"{BASE}/v1/categories").mock(return_value=httpx.Response(201, json={"id": "c"}))
    respx.post(f"{BASE}/v1/hashtags").mock(return_value=httpx.Response(201, json={"id": "h"}))
    respx.post(f"{BASE}/v1/transactions/batch").mock(
        side_effect=[httpx.Response(201, json={"created": []}), httpx.ConnectError("down")]
    )

    result = runner.invoke(cli_app, ["import", "whatever.xlsx", "--apply", "--chunk-size", "1"])
    assert result.exit_code == 1
    assert "Transactions: created 1" in result.output
    assert "failed 1" in result.output
    assert "chunk 1: CONNECTION_ERROR: could not reach engine" in result.output


def test_missing_openpyxl_friendly_error(configured, monkeypatch):
    def boom(path, **k):
        from expense.import_.reader import ImportDependencyError

        raise ImportDependencyError("openpyxl is required for `expense import`.")

    monkeypatch.setattr(import_cmd, "read_workbook", boom)
    result = runner.invoke(cli_app, ["import", "whatever.xlsx"])
    assert result.exit_code == 1
    assert "openpyxl" in result.output
