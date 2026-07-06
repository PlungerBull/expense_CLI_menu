"""Phase 2 reconciliation working-screen tests — checklist + assign/complete."""

import asyncio

from expense.tui.app import ExpenseApp
from expense.tui.screens.modals import ConfirmModal
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


def test_checklist_colors_come_from_palette():
    """Amounts + checked marks use the injected palette, never literal colors (4.2)."""
    from expense.tui.theme import FALLBACK

    rows = [
        ("t1", "Alquiler", -250000, "2026-04-03", "Vivienda"),
        ("t2", "Refund", 5620, "2026-04-09", ""),
    ]
    table = CheckList(rows, checked=["t1"])._build()  # app-less, FALLBACK palette
    marks, amounts = table.columns[0]._cells, table.columns[2]._cells
    assert marks[0].style == FALLBACK.success and marks[2].style == "dim"  # [x] vs [ ]
    assert amounts[0].style == FALLBACK.error  # -2,500.00
    assert amounts[2].style == FALLBACK.success  # +56.20


def test_status_span_maps_completed_and_draft():
    from expense.tui.screens.reconciliations import _status_span
    from expense.tui.theme import Palette

    palette = Palette("#0f0", "#f00", "#ff0")
    assert _status_span("completed", palette) == ("completed", palette.success)
    assert _status_span("draft", palette) == ("draft", palette.warning)


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


def test_revert_key_is_u(fake_client, monkeypatch):
    """Real `u` keypress routes to revert (backlog 4.1 — `r` must never write)."""
    completed = {**DRAFT, "status": 2}
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = ReconciliationDetailScreen(dict(completed))
            await app.push_screen(screen)
            await _wait_list(screen, pilot)
            await pilot.press("u")
            await wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
            await pilot.press("y")
            await wait_for(pilot, lambda: fake_client.posts)
            assert fake_client.posts == [("/reconciliations/r1/revert", None)]

    asyncio.run(scenario())


def test_r_refreshes_record_and_never_writes(fake_client, monkeypatch):
    """`r` refetches the batch (header + status gate) and the checklist; no write."""
    completed = {**DRAFT, "status": 2}
    _patch(monkeypatch)
    fresh = {**completed, "ending_balance_cents": 999999}
    monkeypatch.setattr(
        "expense.commands.reconcile_cmd.fetch_reconciliations",
        lambda cfg, **k: {"items": [fresh]},
    )

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = ReconciliationDetailScreen(dict(completed))
            await app.push_screen(screen)
            await _wait_list(screen, pilot)
            await pilot.press("r")
            await wait_for(pilot, lambda: screen._record is fresh)
            await pilot.pause(0.05)
            assert app.screen is screen  # no confirm modal opened
            assert not fake_client.posts and not fake_client.deletes

    asyncio.run(scenario())


def test_r_refresh_dismisses_when_record_gone(fake_client, monkeypatch):
    """Batch deleted elsewhere → refresh notifies and pops instead of lying."""
    _patch(monkeypatch)
    monkeypatch.setattr(
        "expense.commands.reconcile_cmd.fetch_reconciliations", lambda cfg, **k: {"items": []}
    )

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = ReconciliationDetailScreen(dict(DRAFT))
            await app.push_screen(screen)
            await _wait_list(screen, pilot)
            await pilot.press("r")
            await wait_for(pilot, lambda: app.screen is not screen)

    asyncio.run(scenario())


def test_confirm_modal_enter_cancels(fake_client, monkeypatch):
    """Enter is the safe default: dismisses the confirm without applying (4.1)."""
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = ReconciliationDetailScreen(dict(DRAFT))
            await app.push_screen(screen)
            await _wait_list(screen, pilot)
            await pilot.press("d")  # delete → confirm modal
            await wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
            await pilot.press("enter")
            await wait_for(pilot, lambda: app.screen is screen)  # modal gone
            await pilot.pause(0.05)
            assert not fake_client.deletes

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
