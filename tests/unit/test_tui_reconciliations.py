"""Phase 2 reconciliations tests — list rows + new-batch form (fake client)."""

import asyncio

from textual.widgets import Input

from expense.tui.app import ExpenseApp
from expense.tui.screens.reconciliations import (
    NewReconciliationScreen,
    ReconciliationsScreen,
    reconciliation_rows,
)
from expense.tui.widgets.cursor_list import CursorList

ACCOUNTS = {"acc1": "BCP PEN", "acc2": "Interbank USD"}
ITEMS = [
    {
        "id": "r1",
        "account_id": "acc1",
        "name": "March 2026",
        "date_start": "2026-03-01T00:00:00Z",
        "date_end": "2026-03-31T00:00:00Z",
        "beginning_balance_cents": 1200000,
        "ending_balance_cents": 958000,
        "beginning_balance_source": "chained",
        "status": 2,
    },
    {
        "id": "r2",
        "account_id": "acc2",
        "name": "April 2026",
        "beginning_balance_cents": 958000,
        "ending_balance_cents": None,
        "beginning_balance_source": "manual",
        "status": 1,
    },
]


def test_reconciliation_rows_format():
    rows = reconciliation_rows(ITEMS, ACCOUNTS)
    assert rows[0][0] == "r1"
    cells = rows[0][1]
    assert cells[0] == "BCP PEN" and cells[1] == "March 2026"
    assert cells[2] == "2026-03-01 → 2026-03-31"
    assert cells[3] == "12,000.00" and cells[4] == "9,580.00"
    assert cells[5] == "chained" and cells[6] == "completed"
    assert rows[0][2] == "dim"  # completed dimmed
    # draft, open-ended period, null end balance
    assert reconciliation_rows([ITEMS[1]], ACCOUNTS)[0][1][6] == "draft"
    assert reconciliation_rows([ITEMS[1]], ACCOUNTS)[0][1][2] == "—"


class _FakeClient:
    calls: list = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, path, json_body=None):
        _FakeClient.calls.append((path, json_body))
        return {}


def _patch(monkeypatch):
    _FakeClient.calls = []
    monkeypatch.setattr(
        "expense.commands.accounts_cmd.fetch_accounts",
        lambda *a, **k: [
            {"id": "acc1", "name": "BCP PEN", "currency_code": "PEN"},
            {"id": "acc2", "name": "Interbank USD", "currency_code": "USD"},
        ],
    )
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())
    monkeypatch.setattr("expense.http.ExpenseClient", _FakeClient)
    monkeypatch.setattr("expense.cache.refresh_after_write", lambda *a, **k: None)


def _enter(screen, text):
    screen.query_one("#bar", Input).value = text
    screen._recompute(text)
    screen.on_input_submitted(None)


async def _wait_post(pilot):
    for _ in range(40):
        await pilot.pause(0.02)
        if _FakeClient.calls:
            return


async def _wait_accounts(screen, pilot):
    for _ in range(40):
        await pilot.pause(0.02)
        if screen._accounts:
            return


def test_new_reconciliation_chained_omits_begin(monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = NewReconciliationScreen()
            await app.push_screen(screen)
            await _wait_accounts(screen, pilot)
            _enter(screen, "April 2026")  # name
            _enter(screen, "BCP")  # account → acc1
            _enter(screen, "")  # date_start skip
            _enter(screen, "")  # date_end skip
            _enter(screen, "chained")  # source → no begin field
            _enter(screen, "9460.00")  # end → submits
            await _wait_post(pilot)
            path, body = _FakeClient.calls[0]
            assert path == "/reconciliations"
            assert body["account_id"] == "acc1" and body["name"] == "April 2026"
            assert body["beginning_balance_source"] == "chained"
            assert "beginning_balance_cents" not in body  # chained derives it
            assert body["ending_balance_cents"] == 946000

    asyncio.run(scenario())


def test_new_reconciliation_manual_includes_begin(monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = NewReconciliationScreen()
            await app.push_screen(screen)
            await _wait_accounts(screen, pilot)
            _enter(screen, "Manual batch")  # name
            _enter(screen, "Interbank")  # account → acc2
            _enter(screen, "")  # date_start
            _enter(screen, "")  # date_end
            _enter(screen, "manual")  # source → begin field appears
            assert "begin" in screen._sequence()
            _enter(screen, "5000.00")  # begin
            _enter(screen, "")  # end skip → submits
            await _wait_post(pilot)
            path, body = _FakeClient.calls[0]
            assert body["beginning_balance_source"] == "manual"
            assert body["beginning_balance_cents"] == 500000
            assert "ending_balance_cents" not in body

    asyncio.run(scenario())


def test_reconciliations_list_screen_filters_by_account(monkeypatch):
    monkeypatch.setattr(
        "expense.commands.reconcile_cmd.fetch_reconciliations",
        lambda *a, **k: {"items": ITEMS, "total": 2},
    )
    monkeypatch.setattr(
        "expense.tui.screens.reconciliations.load_account_name_map", lambda: ACCOUNTS
    )
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = ReconciliationsScreen()
            await app.push_screen(screen)
            for _ in range(50):
                await pilot.pause(0.02)
                if app.screen.query(CursorList) and not app.screen.query(
                    "#content LoadingIndicator"
                ):
                    break
            assert len(screen._by_id) == 2  # all accounts
            screen.action_account()  # → acc1 only
            await pilot.pause(0.1)
            assert set(screen._by_id) == {"r1"}

    asyncio.run(scenario())
