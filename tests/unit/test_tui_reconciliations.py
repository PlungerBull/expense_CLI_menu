"""Phase 2 reconciliations tests — list rows + new-batch form (fake client)."""

import asyncio

from textual.widgets import Input

from expense.tui.app import ExpenseApp
from expense.tui.screens.reconciliations import (
    NewReconciliationScreen,
    ReconciliationsScreen,
)
from expense.tui.widgets.cursor_list import CursorList
from tests.unit.helpers import wait_for

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


def test_batch_rows_format():
    from expense.tui.screens.reconciliations import batch_rows

    rows = batch_rows(ITEMS)
    assert rows[0][0] == "r1"
    cells = rows[0][1]
    assert cells[0] == "March 2026"
    assert cells[1] == "2026-03-01 → 2026-03-31"
    assert cells[2] == "12,000.00" and cells[3] == "9,580.00"
    assert cells[4] == "chained" and cells[5] == "completed"
    assert rows[0][2] == "dim"  # completed dimmed
    # draft, open-ended period, null end balance
    assert batch_rows([ITEMS[1]])[0][1][5] == "draft"
    assert batch_rows([ITEMS[1]])[0][1][1] == "—"


def _patch(monkeypatch):
    """Screen-specific patches; the client/config seams come from fake_client."""
    monkeypatch.setattr(
        "expense.commands.accounts_cmd.fetch_accounts",
        lambda *a, **k: [
            {"id": "acc1", "name": "BCP PEN", "currency_code": "PEN"},
            {"id": "acc2", "name": "Interbank USD", "currency_code": "USD"},
        ],
    )


def _enter(screen, text):
    screen.query_one("#bar", Input).value = text
    screen._recompute(text)
    screen.on_input_submitted(None)


async def _wait_accounts(screen, pilot):
    await wait_for(pilot, lambda: screen._accounts)


def test_new_reconciliation_chained_omits_begin(fake_client, monkeypatch):
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
            await wait_for(pilot, lambda: fake_client.posts)
            path, body = fake_client.posts[0]
            assert path == "/reconciliations"
            assert body["account_id"] == "acc1" and body["name"] == "April 2026"
            assert body["beginning_balance_source"] == "chained"
            assert "beginning_balance_cents" not in body  # chained derives it
            assert body["ending_balance_cents"] == 946000

    asyncio.run(scenario())


def test_new_reconciliation_manual_includes_begin(fake_client, monkeypatch):
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
            await wait_for(pilot, lambda: fake_client.posts)
            path, body = fake_client.posts[0]
            assert body["beginning_balance_source"] == "manual"
            assert body["beginning_balance_cents"] == 500000
            assert "ending_balance_cents" not in body

    asyncio.run(scenario())


def _patch_browse(monkeypatch):
    """Two accounts, one batch each — the browse screen's standard fixture."""
    monkeypatch.setattr(
        "expense.commands.reconcile_cmd.fetch_reconciliations",
        lambda *a, **k: {"items": ITEMS, "total": 2},
    )
    monkeypatch.setattr(
        "expense.commands.accounts_cmd.fetch_accounts",
        lambda *a, **k: [
            {"id": "acc1", "name": "BCP PEN", "currency_code": "PEN", "current_balance_cents": 100},
            {"id": "acc2", "name": "Interbank USD", "currency_code": "USD"},
        ],
    )
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())


async def _wait_browse(app, pilot):
    await wait_for(
        pilot,
        lambda: app.screen.query(CursorList) and not app.screen.query("#content LoadingIndicator"),
    )


def test_reconciliations_browse_account_first(monkeypatch):
    _patch_browse(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = ReconciliationsScreen()
            await app.push_screen(screen)
            await _wait_browse(app, pilot)
            # account focus: first account (acc1) selected → its batch (r1) shown below
            assert screen._mode == "accts"
            assert set(screen._by_id) == {"r1"}
            # arrow to the second account → batch list follows to acc2's batch (r2).
            # Wait on the state, not a fixed sleep: the Highlighted message
            # bubbles through several widget pumps and a 50ms nap lost that race
            # on CI (flaked 2026-07-13 after the adaptive-rows load deferral).
            screen._accts_list.action_move(1)
            await wait_for(pilot, lambda: screen._acct_idx == 1)
            assert set(screen._by_id) == {"r2"}

    asyncio.run(scenario())


def test_highlight_from_batches_pane_does_not_switch_account(monkeypatch):
    """A Highlighted sourced from the batches pane (Tab/click focus, no select)
    must not overwrite the selected account while in accounts mode — `n` would
    then create the new batch under the wrong account (backlog 6.2c)."""
    _patch_browse(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = ReconciliationsScreen()
            await app.push_screen(screen)
            await _wait_browse(app, pilot)
            assert screen._mode == "accts" and screen._acct_idx == 0
            # from the *batches* list → ignored
            screen.on_cursor_list_highlighted(CursorList.Highlighted(screen._batch_list, "r1", 1))
            assert screen._acct_idx == 0
            assert set(screen._by_id) == {"r1"}
            # the same event from the *accounts* list still drives the panes
            screen.on_cursor_list_highlighted(CursorList.Highlighted(screen._accts_list, "acc2", 1))
            assert screen._acct_idx == 1
            assert set(screen._by_id) == {"r2"}

    asyncio.run(scenario())


def test_reconciliations_list_pages_past_engine_cap(monkeypatch):
    """The browse fetch pages through the whole collection — a batch past the
    default page must not vanish from the chain, or ctrl+up/down reorders
    against wrong neighbors (backlog 6.2b, list half)."""
    total = 201
    all_items = [
        {"id": f"r{i}", "account_id": "acc1", "name": f"B{i}", "status": 1, "sort_order": i}
        for i in range(total)
    ]

    def paged(cfg, *, limit=None, offset=None, **k):
        lo = offset or 0
        return {"items": all_items[lo : lo + (limit or 100)], "total": total}

    monkeypatch.setattr("expense.commands.reconcile_cmd.fetch_reconciliations", paged)
    monkeypatch.setattr(
        "expense.commands.accounts_cmd.fetch_accounts",
        lambda *a, **k: [{"id": "acc1", "name": "BCP PEN", "currency_code": "PEN"}],
    )
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = ReconciliationsScreen()
            await app.push_screen(screen)
            await _wait_browse(app, pilot)
            assert len(screen._recons) == total  # both pages collected
            assert len(screen._batches) == total  # full chain for the account

    asyncio.run(scenario())


def test_new_reconciliation_from_account_drops_account_field():
    screen = NewReconciliationScreen(account_id="acc1", account_name="BCP PEN")
    assert "account" not in screen._sequence()  # account preset from browse
    assert screen._values["account"] == "acc1"
    assert screen.crumb == ("Reconciliations", "BCP PEN", "New")


def test_new_reconciliation_fetch_error_notifies_not_crash(fake_client, monkeypatch):
    """An engine/config error in _load_accounts must not exit the app (backlog 1.3)."""

    def boom(*a, **k):
        raise RuntimeError("engine down")

    monkeypatch.setattr("expense.commands.accounts_cmd.fetch_accounts", boom)
    notices: list = []
    monkeypatch.setattr(
        NewReconciliationScreen, "notify", lambda self, message, **kw: notices.append(message)
    )

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = NewReconciliationScreen()
            await app.push_screen(screen)
            await wait_for(pilot, lambda: notices)
            assert notices and "engine down" in notices[0]
            assert app.is_running
            assert app.screen is screen

    asyncio.run(scenario())
