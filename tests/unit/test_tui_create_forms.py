"""Phase 2 create-form tests (new hashtag / category / account, fake client)."""

import asyncio

from textual.widgets import Input

from expense.tui.app import ExpenseApp
from expense.tui.screens.create_forms import (
    NewAccountScreen,
    NewCategoryScreen,
    NewHashtagScreen,
)


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


def _run(monkeypatch, screen, steps):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            await app.push_screen(screen)
            await pilot.pause(0.05)
            for text in steps:
                _enter(screen, text)
            await _wait_post(pilot)
            return _FakeClient.calls[0]

    return asyncio.run(scenario())


def test_new_hashtag_posts_name(monkeypatch):
    path, body = _run(monkeypatch, NewHashtagScreen(), ["#groceries"])  # last field → submits
    assert path == "/hashtags"
    assert body["name"] == "groceries" and "id" in body  # leading # stripped


def test_new_category_requires_color_then_posts(monkeypatch):
    # name, then pick a color (type 'green' → matches the palette)
    path, body = _run(monkeypatch, NewCategoryScreen(), ["Educación", "green"])
    assert path == "/categories"
    assert body["name"] == "Educación" and body["color"] == "#5ab87a"


def test_new_account_bank_only_with_currency(monkeypatch):
    # name, currency PEN, skip color (empty → optional)
    path, body = _run(monkeypatch, NewAccountScreen(), ["Interbank Sueldo", "PEN", ""])
    assert path == "/accounts"
    assert body["name"] == "Interbank Sueldo" and body["currency_code"] == "PEN"
    assert "color" not in body and "is_person" not in body  # bank-only, no person flag


def test_new_account_required_name_blocks_submit(monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = NewAccountScreen()
            await app.push_screen(screen)
            await pilot.pause(0.05)
            screen.action_submit()  # nothing entered
            await pilot.pause(0.1)
            assert not _FakeClient.calls

    asyncio.run(scenario())
