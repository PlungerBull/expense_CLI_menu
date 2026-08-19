"""Phase 2 System screen tests — Config + Auth & profile (fake client)."""

import asyncio
import io

from rich.console import Console
from textual.widgets import Static

from expense.config import Config
from expense.tui.app import ExpenseApp
from expense.tui.screens.modals import SnapshotModal
from expense.tui.screens.system import (
    ActivityScreen,
    AuthScreen,
    ConfigScreen,
    RatesScreen,
    _redact_token,
)
from tests.unit.helpers import wait_for

CFG = Config(
    engine_url="https://engine.example",
    token="ewe_pat_abcd1234wxyz",
    main_currency="PEN",
)


def _screen_text(container) -> str:
    """Every Static under `container`, rendered through a Rich console."""
    con = Console(file=io.StringIO(), width=100)
    for child in container.query(Static):
        con.print(child.content)
    return con.file.getvalue()


def test_redact_token():
    assert _redact_token(None) == "(none)"
    assert _redact_token("short") == "****"
    assert _redact_token("ewe_pat_abcd1234wxyz") == "ewe_pat_****wxyz"


def test_config_screen_shows_only_the_engine_connection(monkeypatch):
    """Engine url, token, main currency — and nothing else. The client-id and
    cache-status rows went with the replica (2026-08-06)."""
    monkeypatch.setattr("expense.config.load", lambda: CFG)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = ConfigScreen()
            await app.push_screen(screen)
            await wait_for(pilot, lambda: bool(app.screen.query("#card")))
            card = _screen_text(app.screen.query_one("#card"))
            assert "engine url" in card and "token" in card and "main currency" in card
            assert "client id" not in card and "cache" not in card

    asyncio.run(scenario())


def test_config_screen_reads_and_saves(monkeypatch):
    saved = {}
    monkeypatch.setattr("expense.config.load", lambda: CFG)
    monkeypatch.setattr("expense.config.save", lambda c: saved.update(cfg=c))

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = ConfigScreen()
            await app.push_screen(screen)
            await wait_for(pilot, lambda: screen._cfg is not None)
            assert screen._cfg.engine_url == "https://engine.example"
            screen._save(engine_url="https://new.example")  # e-action path
            await wait_for(pilot, lambda: "cfg" in saved)
            assert saved["cfg"].engine_url == "https://new.example"
            assert saved["cfg"].token == "ewe_pat_abcd1234wxyz"  # other fields preserved

    asyncio.run(scenario())


def test_config_screen_rejects_bad_engine_url(monkeypatch):
    """A scheme-less URL must error at save time, not brick every later call
    with a generic connection error (backlog 6.3b — the TUI half of 3.4)."""
    saved = {}
    monkeypatch.setattr("expense.config.load", lambda: CFG)
    monkeypatch.setattr("expense.config.save", lambda c: saved.update(cfg=c))
    notices: list = []
    monkeypatch.setattr(ConfigScreen, "notify", lambda self, message, **kw: notices.append(message))

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = ConfigScreen()
            await app.push_screen(screen)
            await wait_for(pilot, lambda: screen._cfg is not None)
            screen._save(engine_url="engine.example")  # no scheme
            await wait_for(pilot, lambda: notices)  # the rejection toast
            assert not saved  # nothing written
            assert any("scheme and host" in m for m in notices)
            assert not any("Config saved" in m for m in notices)

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
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = AuthScreen()
            await app.push_screen(screen)
            await wait_for(pilot, lambda: "Alex" in _screen_text(app.screen))
            card = _screen_text(app.screen)
            assert "display name" in card and "Alex" in card
            assert "main currency" in card and "PEN" in card
            # Main currency is read-only — the engine locked it (2026-08-01);
            # the `m` set-currency flow is gone.
            assert not hasattr(screen, "action_currency")
            assert fake_client.puts == []

    asyncio.run(scenario())


def test_auth_not_provisioned_bootstraps(fake_client, monkeypatch):
    _patch_auth(fake_client, monkeypatch, me=None)  # 404 → not provisioned
    monkeypatch.setattr("expense.dates.detect_timezone", lambda *a, **k: "America/Lima")

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = AuthScreen()
            await app.push_screen(screen)
            await wait_for(pilot, lambda: bool(app.screen.query(".legend")))
            screen.action_bootstrap()
            await wait_for(pilot, lambda: bool(app.screen.query("#prompt")))
            app.screen.query_one("#prompt").value = "Alex"
            await pilot.press("enter")  # submit display name
            await wait_for(pilot, lambda: fake_client.posts)
            path, body = fake_client.posts[0]
            assert path == "/auth/bootstrap"
            assert body == {"display_name": "Alex", "timezone": "America/Lima"}

    asyncio.run(scenario())


def test_bootstrap_undetectable_timezone_notifies_not_crash(fake_client, monkeypatch):
    """Timezone detection failure toasts a remedy instead of crashing the app
    through Textual's message pump (backlog 6.2d)."""
    from expense.dates import TimezoneDetectionError

    _patch_auth(fake_client, monkeypatch, me=None)

    def boom(*a, **k):
        raise TimezoneDetectionError("no zone")

    monkeypatch.setattr("expense.dates.detect_timezone", boom)
    notices: list = []
    monkeypatch.setattr(AuthScreen, "notify", lambda self, message, **kw: notices.append(message))

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = AuthScreen()
            await app.push_screen(screen)
            await wait_for(pilot, lambda: bool(app.screen.query(".legend")))
            screen.action_bootstrap()
            await wait_for(pilot, lambda: bool(app.screen.query("#prompt")))
            app.screen.query_one("#prompt").value = "Alex"
            await pilot.press("enter")  # submit display name → detection fails
            await wait_for(pilot, lambda: notices)
            assert any("TZ environment variable" in m for m in notices)
            assert app.is_running
            assert not fake_client.posts  # nothing was sent to the engine

    asyncio.run(scenario())


# --------------------------------------------------------------------------
# System reads — Activity · Rates
# --------------------------------------------------------------------------


def test_system_screens_inherit_escape_and_r(monkeypatch):
    """4.5 dropped the re-declared escape/r; SectionScreen must still supply them."""
    monkeypatch.setattr("expense.config.load", lambda: CFG)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = ConfigScreen()
            await app.push_screen(screen)
            await wait_for(pilot, lambda: screen._cfg is not None)
            keys = set(screen.active_bindings)
            assert {"escape", "r", "e", "t"} <= keys
            assert screen.active_bindings["r"].binding.description == "Refresh"

    asyncio.run(scenario())


def test_activity_screen_lists_and_opens_snapshot(fake_client, monkeypatch):
    """fetch() resolves every row's display name through ONE engine client, so
    build() (UI thread) never does HTTP. The row's account is routed here; an
    unrouted one would degrade to the 8-char short id."""
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
    fake_client.get_responses["/accounts/acc-1234-5678"] = {"name": "BCP Soles"}

    async def scenario():
        app = ExpenseApp()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = ActivityScreen()
            await app.push_screen(screen)
            from expense.tui.widgets.cursor_list import CursorList

            await wait_for(pilot, lambda: bool(app.screen.query(CursorList)))
            assert screen._by_id.get("a1") is items[0]
            assert screen._cells["a1"] == [
                "2026-07-02",
                "14:03:07",
                "UPDATED",
                "user",
                "accounts",
                "BCP Soles",
            ]
            # real enter key (not a direct handler call) so this covers routing.
            await pilot.press("enter")
            await wait_for(pilot, lambda: isinstance(app.screen, SnapshotModal))
            assert isinstance(app.screen, SnapshotModal)
            # regression: the modal must be centered, not collapsed at the top-left
            # corner (the missing `align: center middle` rule made it invisible).
            region = app.screen.query_one("#modal").region
            assert region.x > 0 and region.y > 0

    asyncio.run(scenario())


def test_activity_resolves_singular_resource_types(fake_client):
    # The engine writes resource_type in the SINGULAR ("transaction", …); the
    # resolver must map those (and the older plural forms) to the collection
    # path it reads live.
    import expense.commands.activity_cmd as ac

    fake_client.get_responses["/transactions/abc-123"] = {"title": "Groceries"}
    fake_client.get_responses["/accounts/def-456"] = {"name": "BCP Soles"}
    assert ac._resolve_resource_name("transaction", "abc-123", fake_client) == "Groceries"
    alias = ac._resolve_resource_name("expense_transactions", "abc-123", fake_client)
    assert alias == "Groceries"
    assert ac._resolve_resource_name("account", "def-456", fake_client) == "BCP Soles"
    # unknown type → short id, never a crash (and never an engine read)
    assert ac._resolve_resource_name("user", "0123456789ab", fake_client) == "01234567"
    assert not any(path.startswith("/users") for _, path in fake_client.requests)
    # a routed miss (deleted record → 404) also degrades to the short id
    assert ac._resolve_resource_name("account", "0123456789ab", fake_client) == "01234567"


def test_rates_screen_lists_history(monkeypatch):
    """Rates is a read table now (backlog 4.8): newest first, 4-decimal rates."""
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: CFG)
    captured = {}

    def fake_history(cfg, *, date=None, limit=None, offset=None, verbose=False):
        captured.update(date=date, limit=limit, offset=offset)
        return {
            "items": [
                {"rate_date": "2026-07-05", "base": "USD", "target": "PEN", "rate": 3.6},
                {"rate_date": "2026-07-04", "base": "USD", "target": "PEN", "rate": 3.59},
            ],
            "total": 132,
        }

    monkeypatch.setattr("expense.commands.rates_cmd.fetch_rates_history", fake_history)

    async def scenario():
        app = ExpenseApp()
        # tall harness: rows-per-page adapt to the terminal since 2026-07-13;
        # 35 lines puts rates (chrome 11 + two legends 4) at the 20-row cap
        async with app.run_test(size=(120, 35)) as pilot:
            screen = RatesScreen()
            await app.push_screen(screen)
            from expense.tui.widgets.cursor_list import CursorList

            await wait_for(pilot, lambda: bool(app.screen.query(CursorList)))
            # fetch-paged, capped at the 20-row standard (2026-07-11 + 2026-07-13)
            assert captured == {"date": None, "limit": 20, "offset": 0}
            cursor_list = app.screen.query_one(CursorList)
            rows = cursor_list._rows
            assert rows[0][1] == ["2026-07-05", "USD", "PEN", "3.6000"]
            assert rows[1][1] == ["2026-07-04", "USD", "PEN", "3.5900"]
            assert cursor_list.page_status == "rows 1-2 of 132 · page 1 of 7"

    asyncio.run(scenario())


def test_rates_screen_date_filter_refetches(monkeypatch):
    """Real `f` keypress → PromptModal → submitted date refetches; blank clears."""
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: CFG)
    calls: list = []

    def fake_history(cfg, *, date=None, limit=None, offset=None, verbose=False):
        calls.append(date)
        return {"items": [], "total": 0}

    monkeypatch.setattr("expense.commands.rates_cmd.fetch_rates_history", fake_history)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = RatesScreen()
            await app.push_screen(screen)
            await wait_for(pilot, lambda: calls)
            await pilot.press("f")
            await wait_for(pilot, lambda: bool(app.screen.query("#prompt")))
            app.screen.query_one("#prompt").value = "2026-07-04"
            await pilot.press("enter")
            await wait_for(pilot, lambda: calls[-1] == "2026-07-04")
            await pilot.press("f")  # blank enter clears the filter
            await wait_for(pilot, lambda: bool(app.screen.query("#prompt")))
            app.screen.query_one("#prompt").value = ""
            await pilot.press("enter")
            await wait_for(pilot, lambda: len(calls) >= 3 and calls[-1] is None)

    asyncio.run(scenario())
