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
