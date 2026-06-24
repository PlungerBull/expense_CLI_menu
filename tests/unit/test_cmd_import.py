"""respx-mocked apply tests + CLI dry-run for `expense import`."""

import json
from uuid import uuid4

import httpx
import pytest
import respx
import typer
from typer.testing import CliRunner

from expense import config as config_module
from expense.commands import import_cmd
from expense.context import AppContext
from expense.http import ExpenseClient
from expense.import_ import apply as apply_mod
from expense.import_ import plan as plan_mod
from expense.import_.parse import ParsedRow
from expense.import_.reader import RawRow, SheetData

BASE = "https://api.example.com"
runner = CliRunner()


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.setenv("EXPENSE_CONFIG", str(tmp_path / ".expense-config"))
    monkeypatch.setenv("EXPENSE_CACHE", str(tmp_path / "cache.sqlite3"))
    config_module.save(
        config_module.Config(engine_url=BASE, token="ewe_pat_test", client_id=uuid4())
    )
    yield


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
    respx.post(f"{BASE}/v1/transactions/batch").mock(
        return_value=httpx.Response(
            409, json={"error": {"code": "CONFLICT", "message": "id exists", "fields": None}}
        )
    )

    cfg = config_module.ensure_loaded()
    with ExpenseClient(cfg) as client:
        res = apply_mod.resolve_or_create(client, plan)
        result = apply_mod.apply_plan(client, plan, res)

    assert result.tx_created == 0
    assert result.tx_skipped_existing == 1
    assert result.tx_failed == 0


@respx.mock
def test_batch_422_is_fatal_and_reported(configured):
    plan = _plan([_prow(2)])
    _mock_existing(
        accounts=[{"id": "acc-pen", "name": "BCP PEN", "currency_code": "PEN"}],
        categories=[],
        hashtags=[],
    )
    respx.post(f"{BASE}/v1/categories").mock(return_value=httpx.Response(201, json={"id": "c"}))
    respx.post(f"{BASE}/v1/hashtags").mock(return_value=httpx.Response(201, json={"id": "h"}))
    respx.post(f"{BASE}/v1/transactions/batch").mock(
        return_value=httpx.Response(
            422,
            json={"error": {"code": "VALIDATION_ERROR", "message": "bad", "fields": {}}},
        )
    )

    cfg = config_module.ensure_loaded()
    with ExpenseClient(cfg) as client:
        res = apply_mod.resolve_or_create(client, plan)
        result = apply_mod.apply_plan(client, plan, res)

    assert result.tx_failed == 1
    assert result.failures and result.failures[0][0] == 0


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


def _build_app() -> typer.Typer:
    app = typer.Typer()

    @app.callback()
    def _root(ctx: typer.Context) -> None:
        ctx.obj = AppContext()

    app.command("import")(import_cmd.run_import)
    return app


@respx.mock
def test_dry_run_writes_nothing(configured, monkeypatch):
    monkeypatch.setattr(
        import_cmd,
        "read_workbook",
        lambda path, **k: SheetData(headers=_HEADERS, rows=[RawRow(2, list(_CELLS))]),
    )
    result = runner.invoke(_build_app(), ["import", "whatever.xlsx"])
    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert not respx.calls  # nothing hit the engine


def test_missing_openpyxl_friendly_error(configured, monkeypatch):
    def boom(path, **k):
        from expense.import_.reader import ImportDependencyError

        raise ImportDependencyError("openpyxl is required for `expense import`.")

    monkeypatch.setattr(import_cmd, "read_workbook", boom)
    result = runner.invoke(_build_app(), ["import", "whatever.xlsx"])
    assert result.exit_code == 1
    assert "openpyxl" in result.output
