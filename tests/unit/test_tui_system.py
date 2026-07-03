"""Phase 2 System screen tests — Config + Auth & profile (fake client)."""

import asyncio
from uuid import uuid4

from expense.config import Config
from expense.errors import EngineError
from expense.tui.app import ExpenseApp
from expense.tui.screens.system import AuthScreen, ConfigScreen, _redact_token

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
            for _ in range(50):
                await pilot.pause(0.02)
                if screen._cfg is not None:
                    break
            assert screen._cfg.engine_url == "https://engine.example"
            screen._save(engine_url="https://new.example")  # e-action path
            await pilot.pause(0.05)
            assert saved["cfg"].engine_url == "https://new.example"
            assert saved["cfg"].token == "ewe_pat_abcd1234wxyz"  # other fields preserved

    asyncio.run(scenario())


class _FakeClient:
    me = None  # None → raise 404 (not provisioned)
    posts: list = []
    puts: list = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, path):
        if _FakeClient.me is None:
            raise EngineError("NOT_FOUND", "no user", None, 404, {})
        return _FakeClient.me

    def post(self, path, json_body=None):
        _FakeClient.posts.append((path, json_body))
        return {}

    def put(self, path, json_body=None):
        _FakeClient.puts.append((path, json_body))
        return {}


def _patch_auth(monkeypatch, *, me):
    _FakeClient.me = me
    _FakeClient.posts, _FakeClient.puts = [], []
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: CFG)
    monkeypatch.setattr("expense.http.ExpenseClient", _FakeClient)
    monkeypatch.setattr("expense.cache.refresh_after_write", lambda *a, **k: None)
    monkeypatch.setattr("expense.config.save", lambda c: None)


async def _wait(pred, pilot):
    for _ in range(50):
        await pilot.pause(0.02)
        if pred():
            return


def test_auth_provisioned_shows_identity(monkeypatch):
    me = {
        "user": {"display_name": "Alex", "id": "u1"},
        "settings": {"main_currency": "PEN"},
    }
    _patch_auth(monkeypatch, me=me)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = AuthScreen()
            await app.push_screen(screen)
            await _wait(lambda: bool(app.screen.query(".section-title")), pilot)
            await pilot.pause(0.05)
            # currency change → prompt USD/PEN, then confirm → PUT /auth/settings
            screen.action_currency()
            await pilot.pause(0.05)
            app.screen.query_one("#prompt").value = "usd"
            await pilot.press("enter")  # submit prompt → opens confirm
            await pilot.pause(0.05)
            await pilot.press("y")  # confirm recalc
            await _wait(lambda: bool(_FakeClient.puts), pilot)
            assert _FakeClient.puts == [("/auth/settings", {"main_currency": "USD"})]

    asyncio.run(scenario())


def test_auth_not_provisioned_bootstraps(monkeypatch):
    _patch_auth(monkeypatch, me=None)  # 404 → not provisioned
    monkeypatch.setattr("expense.commands.auth_cmd._detect_timezone", lambda: "America/Lima")

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = AuthScreen()
            await app.push_screen(screen)
            await _wait(lambda: bool(app.screen.query(".legend")), pilot)
            screen.action_bootstrap()
            await pilot.pause(0.05)
            app.screen.query_one("#prompt").value = "Alex"
            await pilot.press("enter")  # submit display name
            await _wait(lambda: bool(_FakeClient.posts), pilot)
            path, body = _FakeClient.posts[0]
            assert path == "/auth/bootstrap"
            assert body == {"display_name": "Alex", "timezone": "America/Lima"}

    asyncio.run(scenario())


# --------------------------------------------------------------------------
# System reads — Sync · Activity · Rates
# --------------------------------------------------------------------------

from expense.cache import SyncSummary  # noqa: E402
from expense.tui.screens.modals import SnapshotModal  # noqa: E402
from expense.tui.screens.system import (  # noqa: E402
    ActivityScreen,
    RatesScreen,
    SyncScreen,
    _delta_table,
    _rate_table,
    _short_token,
)


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
            await _wait(lambda: bool(app.screen.query(".legend")), pilot)
            # guard: pressing sync under --no-cache never touches the engine.
            called = []
            monkeypatch.setattr("expense.cache.delta_sync", lambda *a, **k: called.append(1))
            screen.action_sync()
            await pilot.pause(0.05)
            assert called == []

    asyncio.run(scenario())


def test_sync_screen_delta_refresh(monkeypatch):
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: CFG)
    # keep fetch() off disk: pretend there's no cache row yet.
    monkeypatch.setattr(
        "expense.cache.db.connect", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no db"))
    )
    monkeypatch.setattr("expense.http.ExpenseClient", _FakeClient)
    summary = SyncSummary(kind="delta", inserts={"transactions": 2}, updates={"transactions": 1})
    monkeypatch.setattr("expense.cache.delta_sync", lambda *a, **k: summary)

    async def scenario():
        app = ExpenseApp(no_cache=False)
        async with app.run_test() as pilot:
            screen = SyncScreen()
            await app.push_screen(screen)
            await _wait(lambda: bool(app.screen.query(".legend")), pilot)
            screen.action_sync()
            await _wait(lambda: screen._last is not None, pilot)
            assert screen._last is summary
            assert screen._last.kind == "delta"

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

            await _wait(lambda: bool(app.screen.query(CursorList)), pilot)
            assert screen._by_id.get("a1") is items[0]
            # real enter key (not a direct handler call) so this covers routing.
            await pilot.press("enter")
            await _wait(lambda: isinstance(app.screen, SnapshotModal), pilot)
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
            await _wait(lambda: bool(app.screen.query(".legend")), pilot)
            screen.action_lookup()  # target defaults to PEN, base/date to engine defaults
            await _wait(lambda: screen._result is not None, pilot)
            assert captured == {"target": "PEN", "base": None, "date": None}
            assert screen._result["rate"] == "3.7520"

    asyncio.run(scenario())
