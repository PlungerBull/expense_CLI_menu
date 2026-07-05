"""Phase 2 reconciliation working-screen tests — checklist + assign/complete."""

import asyncio

from expense.tui.app import ExpenseApp
from expense.tui.screens.reconciliations import ReconciliationDetailScreen, _txn_sub
from expense.tui.widgets.checklist import CheckList
from tests.unit.helpers import wait_for

CATS = {"c1": "Vivienda"}
TAGS = {"h1": "oficina"}


def test_txn_sub_assembles_category_tags_note():
    it = {"category_id": "c1", "hashtag_ids": ["h1"], "description": "alquiler"}
    assert _txn_sub(it, CATS, TAGS) == 'Vivienda  ·  #oficina  ·  "alquiler"'
    assert _txn_sub({"category_id": "c1"}, CATS, TAGS) == "Vivienda"
    assert _txn_sub({}, CATS, TAGS) == ""


def test_checklist_toggle_emits_and_tracks():
    rows = [("t1", "Alquiler", -250000, "2026-04-03", "Vivienda")]
    cl = CheckList(rows, checked=[])
    assert cl.cursor_key == "t1" and cl.checked == set()
    # simulate a toggle (no event loop): action_toggle posts a message + flips state
    cl.action_toggle()
    assert cl.checked == {"t1"}
    cl.action_toggle()
    assert cl.checked == set()


DRAFT = {
    "id": "r1",
    "account_id": "acc1",
    "name": "April 2026",
    "date_start": "2026-04-01T00:00:00Z",
    "date_end": "2026-04-30T00:00:00Z",
    "beginning_balance_cents": 958000,
    "ending_balance_cents": 946000,
    "beginning_balance_source": "chained",
    "status": 1,
}
ASSIGNED = [
    {
        "id": "t1",
        "title": "Alquiler",
        "amount_cents": -250000,
        "date": "2026-04-03",
        "reconciliation_id": "r1",
        "category_id": "c1",
        "hashtag_ids": ["h1"],
    },
]
AVAILABLE = [
    {
        "id": "t2",
        "title": "Gasolina",
        "amount_cents": -12000,
        "date": "2026-04-08",
        "reconciliation_id": None,
        "category_id": None,
        "hashtag_ids": [],
    },
    {
        "id": "t3",
        "title": "Other batch",
        "amount_cents": -5000,
        "date": "2026-04-09",
        "reconciliation_id": "rX",
    },  # belongs elsewhere → excluded
]


def _patch(monkeypatch):
    """Screen-specific patches; the client/config seams come from fake_client."""

    def fake_fetch(cfg, **k):
        if k.get("reconciliation") == "r1":
            return {"items": ASSIGNED}
        if k.get("account") == "acc1":
            return {"items": AVAILABLE}
        return {"items": []}

    monkeypatch.setattr("expense.commands.transactions_cmd.fetch_transactions", fake_fetch)
    monkeypatch.setattr(
        "expense.tui.screens.reconciliations.load_account_name_map", lambda: {"acc1": "BCP PEN"}
    )
    monkeypatch.setattr("expense.tui.screens.reconciliations.load_category_name_map", lambda: CATS)
    monkeypatch.setattr("expense.tui.screens.reconciliations.load_hashtag_name_map", lambda: TAGS)


async def _wait_list(screen, pilot):
    await wait_for(pilot, lambda: screen._list is not None)


def test_draft_lists_assigned_checked_plus_available(fake_client, monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = ReconciliationDetailScreen(dict(DRAFT))
            await app.push_screen(screen)
            await _wait_list(screen, pilot)
            cl = screen._list
            keys = [r[0] for r in cl._rows]
            assert keys == ["t1", "t2"]  # t3 (other batch) excluded
            assert cl.checked == {"t1"}  # assigned one is checked
            assert not cl._read_only

    asyncio.run(scenario())


def test_toggle_puts_reconciliation_id(fake_client, monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = ReconciliationDetailScreen(dict(DRAFT))
            await app.push_screen(screen)
            await _wait_list(screen, pilot)
            # toggle the available row (t2) into the batch
            screen._list._cursor = 1
            screen._list.action_toggle()
            await wait_for(pilot, lambda: fake_client.puts)
            assert fake_client.puts == [("/transactions/t2", {"reconciliation_id": "r1"})]

    asyncio.run(scenario())


def test_complete_requires_assignment_then_posts(fake_client, monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = ReconciliationDetailScreen(dict(DRAFT))
            await app.push_screen(screen)
            await _wait_list(screen, pilot)
            screen.action_complete()  # t1 already checked → opens confirm
            await pilot.pause(0.05)
            await pilot.press("y")  # confirm
            await wait_for(pilot, lambda: fake_client.posts)
            assert fake_client.posts == [("/reconciliations/r1/complete", None)]

    asyncio.run(scenario())


def test_completed_is_read_only(fake_client, monkeypatch):
    completed = {**DRAFT, "status": 2}
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = ReconciliationDetailScreen(dict(completed))
            await app.push_screen(screen)
            await _wait_list(screen, pilot)
            assert screen._list._read_only
            assert [r[0] for r in screen._list._rows] == ["t1"]  # only batch txns
            screen.action_delete()  # blocked while completed
            await pilot.pause(0.05)
            assert not fake_client.deletes

    asyncio.run(scenario())


def test_revert_posts(fake_client, monkeypatch):
    completed = {**DRAFT, "status": 2}
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = ReconciliationDetailScreen(dict(completed))
            await app.push_screen(screen)
            await _wait_list(screen, pilot)
            screen.action_revert()
            await pilot.pause(0.05)
            await pilot.press("y")
            await wait_for(pilot, lambda: fake_client.posts)
            assert fake_client.posts == [("/reconciliations/r1/revert", None)]

    asyncio.run(scenario())


def test_detail_fetch_error_notifies_not_crash(fake_client, monkeypatch):
    """An engine/config error in _load_txns must not exit the app (backlog 1.3)."""
    _patch(monkeypatch)

    def boom(cfg, **k):
        raise RuntimeError("engine down")

    monkeypatch.setattr("expense.commands.transactions_cmd.fetch_transactions", boom)
    notices: list = []
    monkeypatch.setattr(
        ReconciliationDetailScreen, "notify", lambda self, message, **kw: notices.append(message)
    )

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = ReconciliationDetailScreen(dict(DRAFT))
            await app.push_screen(screen)
            await wait_for(pilot, lambda: notices)
            assert notices and "engine down" in notices[0]
            assert app.is_running
            assert app.screen is screen

    asyncio.run(scenario())
