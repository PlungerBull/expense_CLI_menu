"""Phase 2 System screen tests — Config + Auth & profile (fake client)."""

import asyncio
from uuid import uuid4

from expense.cache import SyncSummary
from expense.config import Config
from expense.tui.app import ExpenseApp
from expense.tui.screens.modals import ConfirmModal, SnapshotModal
from expense.tui.screens.system import (
    ActivityScreen,
    AuthScreen,
    ConfigScreen,
    RatesScreen,
    SyncScreen,
    _delta_table,
    _rate_table,
    _redact_token,
    _short_token,
)
from tests.unit.helpers import wait_for

CFG = Config(
    engine_url="https://engine.example",
    token="ewe_pat_abcd1234wxyz",
    client_id=uuid4(),
    main_currency="PEN",
)


def test_redact_token():
    assert _redact_token(None) == "(none)"
    assert _redact_token("short") == "****"
    assert _redact_token("ewe_pat_abcd1234wxyz") == "ewe_pat_****wxyz"


def test_config_screen_reads_and_saves(monkeypatch):
    saved = {}
    monkeypatch.setattr("expense.config.load", lambda: CFG)
    monkeypatch.setattr("expense.config.save", lambda c: saved.update(cfg=c))

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = ConfigScreen()
            await app.push_screen(screen)
            await wait_for(pilot, lambda: screen._cfg is not None)
            assert screen._cfg.engine_url == "https://engine.example"
            screen._save(engine_url="https://new.example")  # e-action path
            await pilot.pause(0.05)
            assert saved["cfg"].engine_url == "https://new.example"
            assert saved["cfg"].token == "ewe_pat_abcd1234wxyz"  # other fields preserved

    asyncio.run(scenario())


def _patch_auth(fake_client, monkeypatch, *, me):
    """me=None leaves GET /auth/me unmocked → FakeClient raises 404 (not provisioned)."""
    if me is not None:
        fake_client.get_responses["/auth/me"] = me
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: CFG)
    monkeypatch.setattr("expense.config.save", lambda c: None)


def test_auth_provisioned_shows_identity(fake_client, monkeypatch):
    me = {
        "user": {"display_name": "Alex", "id": "u1"},
        "settings": {"main_currency": "PEN"},
    }
    _patch_auth(fake_client, monkeypatch, me=me)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = AuthScreen()
            await app.push_screen(screen)
            await wait_for(pilot, lambda: bool(app.screen.query(".section-title")))
            await pilot.pause(0.05)
            # currency change → prompt USD/PEN, then confirm → PUT /auth/settings
            screen.action_currency()
            await pilot.pause(0.05)
            app.screen.query_one("#prompt").value = "usd"
            await pilot.press("enter")  # submit prompt → opens confirm
            await pilot.pause(0.05)
            await pilot.press("y")  # confirm recalc
            await wait_for(pilot, lambda: fake_client.puts)
            assert fake_client.puts == [("/auth/settings", {"main_currency": "USD"})]

    asyncio.run(scenario())


def test_auth_not_provisioned_bootstraps(fake_client, monkeypatch):
    _patch_auth(fake_client, monkeypatch, me=None)  # 404 → not provisioned
    monkeypatch.setattr("expense.commands.auth_cmd._detect_timezone", lambda: "America/Lima")

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = AuthScreen()
            await app.push_screen(screen)
            await wait_for(pilot, lambda: bool(app.screen.query(".legend")))
            screen.action_bootstrap()
            await pilot.pause(0.05)
            app.screen.query_one("#prompt").value = "Alex"
            await pilot.press("enter")  # submit display name
            await wait_for(pilot, lambda: fake_client.posts)
            path, body = fake_client.posts[0]
            assert path == "/auth/bootstrap"
            assert body == {"display_name": "Alex", "timezone": "America/Lima"}

    asyncio.run(scenario())


# --------------------------------------------------------------------------
# System reads — Sync · Activity · Rates
# --------------------------------------------------------------------------


def test_short_token():
    assert _short_token(None) == "(none)"
    assert _short_token("abc123") == "abc123"  # short tokens pass through
    assert _short_token("a1f3c9e7b2d4f6") == "a1f3c9…d4f6"


def test_delta_table_cold_start_only_inserts():
    # cold_start populates only inserts; missing update/tombstone dicts read as 0.
    s = SyncSummary(kind="cold_start", inserts={"transactions": 5}, settings_changed=True)
    t = _delta_table(s)
    assert t.row_count == 7  # 6 resources + settings


def test_rate_table_columns_track_response():
    body = {"base": "USD", "target": "PEN", "rate": "3.7520", "date": "2026-07-02"}
    assert len(_rate_table(body).columns) == 4
    assert _rate_table({}).row_count == 0  # empty body → empty table, no crash


def test_sync_screen_disabled_under_no_cache(monkeypatch):
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: CFG)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = SyncScreen()
            await app.push_screen(screen)
            await wait_for(pilot, lambda: bool(app.screen.query(".legend")))
            # guard: pressing sync under --no-cache never touches the engine.
            called = []
            monkeypatch.setattr("expense.cache.delta_sync", lambda *a, **k: called.append(1))
            screen.action_sync()
            await pilot.pause(0.05)
            assert called == []

    asyncio.run(scenario())


def test_sync_screen_delta_refresh(fake_client, monkeypatch):
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: CFG)
    # keep fetch() off disk: pretend there's no cache row yet.
    monkeypatch.setattr(
        "expense.cache.db.connect", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no db"))
    )
    summary = SyncSummary(kind="delta", inserts={"transactions": 2}, updates={"transactions": 1})
    monkeypatch.setattr("expense.cache.delta_sync", lambda *a, **k: summary)

    async def scenario():
        app = ExpenseApp(no_cache=False)
        async with app.run_test() as pilot:
            screen = SyncScreen()
            await app.push_screen(screen)
            await wait_for(pilot, lambda: bool(app.screen.query(".legend")))
            screen.action_sync()
            await wait_for(pilot, lambda: screen._last is not None)
            assert screen._last is summary
            assert screen._last.kind == "delta"

    asyncio.run(scenario())


def test_full_rebuild_confirms_first(fake_client, monkeypatch):
    """`f` opens a confirm (backlog 4.1): enter cancels, y runs cold_start."""
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: CFG)
    monkeypatch.setattr(
        "expense.cache.db.connect", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no db"))
    )
    summary = SyncSummary(kind="cold_start", inserts={"transactions": 9})
    calls: list = []

    def fake_cold_start(*a, **k):
        calls.append(1)
        return summary

    monkeypatch.setattr("expense.cache.cold_start", fake_cold_start)

    async def scenario():
        app = ExpenseApp(no_cache=False)
        async with app.run_test() as pilot:
            screen = SyncScreen()
            await app.push_screen(screen)
            await wait_for(pilot, lambda: bool(app.screen.query(".legend")))
            await pilot.press("f")  # real key: covers routing
            await wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
            await pilot.press("enter")  # safe default → cancels
            await wait_for(pilot, lambda: app.screen is screen)
            await pilot.pause(0.05)
            assert calls == []
            await pilot.press("f")
            await wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
            await pilot.press("y")
            await wait_for(pilot, lambda: screen._last is summary)
            assert calls == [1]

    asyncio.run(scenario())


def test_system_screens_inherit_escape_and_r(monkeypatch):
    """4.5 dropped the re-declared escape/r; SectionScreen must still supply them."""
    monkeypatch.setattr("expense.config.load", lambda: CFG)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = ConfigScreen()
            await app.push_screen(screen)
            await wait_for(pilot, lambda: screen._cfg is not None)
            keys = set(screen.active_bindings)
            assert {"escape", "r", "e", "t"} <= keys
            assert screen.active_bindings["r"].binding.description == "Refresh"

    asyncio.run(scenario())


def test_activity_screen_lists_and_opens_snapshot(monkeypatch):
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: CFG)
    items = [
        {
            "id": "a1",
            "created_at": "2026-07-02T14:03:07Z",
            "action": 2,
            "actor_type": "user",
            "resource_type": "accounts",
            "resource_id": "acc-1234-5678",
            "before_snapshot": {"name": "Old", "is_archived": False},
            "after_snapshot": {"name": "New", "is_archived": False},
        }
    ]
    monkeypatch.setattr(
        "expense.commands.activity_cmd.fetch_activity",
        lambda *a, **k: {"items": items, "total": 1},
    )

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test(size=(120, 40)) as pilot:
            screen = ActivityScreen()
            await app.push_screen(screen)
            from expense.tui.widgets.cursor_list import CursorList

            await wait_for(pilot, lambda: bool(app.screen.query(CursorList)))
            assert screen._by_id.get("a1") is items[0]
            # real enter key (not a direct handler call) so this covers routing.
            await pilot.press("enter")
            await wait_for(pilot, lambda: isinstance(app.screen, SnapshotModal))
            assert isinstance(app.screen, SnapshotModal)
            # regression: the modal must be centered, not collapsed at the top-left
            # corner (the missing `align: center middle` rule made it invisible).
            region = app.screen.query_one("#modal").region
            assert region.x > 0 and region.y > 0

    asyncio.run(scenario())


def test_activity_resolves_singular_resource_types(monkeypatch):
    # The engine writes resource_type in the SINGULAR ("transaction", …); the
    # resolver must map those (and the older plural forms) to cache lookups.
    import expense.commands.activity_cmd as ac

    monkeypatch.setattr("expense.cache.queries.get_transaction", lambda _id: {"title": "Groceries"})
    monkeypatch.setattr("expense.cache.queries.get_account", lambda _id: {"name": "BCP Soles"})
    assert ac._resolve_resource_name("transaction", "abc-123") == "Groceries"
    assert ac._resolve_resource_name("expense_transactions", "abc-123") == "Groceries"  # alias
    assert ac._resolve_resource_name("account", "def-456") == "BCP Soles"
    # unknown type → short id, never a crash
    assert ac._resolve_resource_name("user", "0123456789ab") == "01234567"


def test_rates_screen_lookup(monkeypatch):
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: CFG)
    captured = {}

    def fake_fetch_rate(cfg, *, target, base=None, date=None, verbose=False):
        captured.update(target=target, base=base, date=date)
        return {"base": base or "USD", "target": target, "rate": "3.7520"}

    monkeypatch.setattr("expense.commands.rates_cmd.fetch_rate", fake_fetch_rate)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = RatesScreen()
            await app.push_screen(screen)
            await wait_for(pilot, lambda: bool(app.screen.query(".legend")))
            screen.action_lookup()  # target defaults to PEN, base/date to engine defaults
            await wait_for(pilot, lambda: screen._result is not None)
            assert captured == {"target": "PEN", "base": None, "date": None}
            assert screen._result["rate"] == "3.7520"

    asyncio.run(scenario())
