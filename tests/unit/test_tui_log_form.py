"""Phase 2 transaction-form smoke tests (validation + submit, fake client)."""

import asyncio

from textual.widgets import Input, Select

from expense.tui.app import ExpenseApp
from expense.tui.screens.log_transaction import LogTransactionScreen

ACCOUNTS = {"acc1": "BCP Soles"}
CATEGORIES = {"cat1": "Comida"}


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
    mod = "expense.tui.screens.log_transaction"
    monkeypatch.setattr(f"{mod}.load_account_name_map", lambda: ACCOUNTS)
    monkeypatch.setattr(f"{mod}.load_category_name_map", lambda: CATEGORIES)
    monkeypatch.setattr("expense.http.ExpenseClient", _FakeClient)
    monkeypatch.setattr("expense.cache.refresh_after_write", lambda *a, **k: None)
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())


def test_log_form_submits_valid_payload(monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = LogTransactionScreen()
            await app.push_screen(screen)
            for _ in range(40):
                await pilot.pause(0.02)
                if screen.query_one("#f-account", Select)._options:  # options loaded
                    break
            screen.query_one("#f-title", Input).value = "Almuerzo"
            screen.query_one("#f-amount", Input).value = "-18000"
            screen.query_one("#f-account", Select).value = "acc1"
            screen.query_one("#f-category", Select).value = "cat1"
            screen.query_one("#f-cleared", Select).value = "no"
            screen.action_submit()
            for _ in range(40):
                await pilot.pause(0.02)
                if _FakeClient.calls:
                    break
            path, body = _FakeClient.calls[0]
            assert path == "/transactions"
            assert body["title"] == "Almuerzo" and body["amount_cents"] == -18000
            assert body["account_id"] == "acc1" and body["category_id"] == "cat1"
            assert body["cleared"] is False and "date" in body

    asyncio.run(scenario())


def test_log_form_rejects_zero_amount(monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = LogTransactionScreen()
            await app.push_screen(screen)
            await pilot.pause(0.1)
            screen.query_one("#f-title", Input).value = "x"
            screen.query_one("#f-amount", Input).value = "0"
            screen.query_one("#f-account", Select).value = "acc1"
            screen.query_one("#f-category", Select).value = "cat1"
            screen.action_submit()
            await pilot.pause(0.1)
            assert not _FakeClient.calls  # zero amount rejected, no POST

    asyncio.run(scenario())
