"""Phase 2 quick-add Log screen tests (field cycle + submit, fake client)."""

import asyncio

import pytest
from textual.widgets import Input

from expense.tui.app import ExpenseApp
from expense.tui.screens.quick_log import QuickAddLogScreen, amount_to_text, parse_amount

ACCOUNTS = [
    {"id": "acc1", "name": "BCP PEN", "currency_code": "PEN", "is_person": False},
    {"id": "acc2", "name": "BCP USD", "currency_code": "USD", "is_person": False},
]
CATEGORIES = {"items": [{"id": "cat1", "name": "Mascotas", "is_system": False}]}
HASHTAGS = {"items": [{"id": "h1", "name": "dog"}, {"id": "h2", "name": "traveling"}]}


@pytest.mark.parametrize(
    ("text", "expected"),
    [("-99.92", -9992), ("99", 9900), ("+12.5", 1250), ("0", 0), ("abc", None), ("", None)],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


def test_amount_to_text_roundtrips():
    assert amount_to_text(-9992) == "-99.92"
    assert parse_amount(amount_to_text(-123456)) == -123456


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
    monkeypatch.setattr("expense.commands.accounts_cmd.fetch_accounts", lambda *a, **k: ACCOUNTS)
    monkeypatch.setattr(
        "expense.commands.categories_cmd.fetch_categories", lambda *a, **k: CATEGORIES
    )
    monkeypatch.setattr("expense.commands.hashtags_cmd.fetch_hashtags", lambda *a, **k: HASHTAGS)
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())
    monkeypatch.setattr("expense.http.ExpenseClient", _FakeClient)
    monkeypatch.setattr("expense.cache.refresh_after_write", lambda *a, **k: None)


def _enter(screen, text):
    """Set the bar text, recompute suggestions, and commit the current field."""
    screen.query_one("#bar", Input).value = text
    screen._recompute_suggestions(text)
    screen.on_input_submitted(None)


def test_quick_log_full_flow_submits_payload(monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = QuickAddLogScreen()
            await app.push_screen(screen)
            for _ in range(40):
                await pilot.pause(0.02)
                if screen._accounts:
                    break
            _enter(screen, "")  # date → today
            _enter(screen, "Dog walker")  # title
            _enter(screen, "-99.92")  # amount
            _enter(screen, "BCP P")  # account → BCP PEN
            _enter(screen, "Masco")  # category → Mascotas
            _enter(screen, "dog")  # hashtag add (stays)
            _enter(screen, "")  # hashtags done → advance to note
            _enter(screen, "")  # note skip
            screen.action_submit()
            for _ in range(40):
                await pilot.pause(0.02)
                if _FakeClient.calls:
                    break
            path, body = _FakeClient.calls[0]
            assert path == "/transactions"
            assert body["title"] == "Dog walker" and body["amount_cents"] == -9992
            assert body["account_id"] == "acc1" and body["category_id"] == "cat1"
            assert body["hashtag_ids"] == ["h1"] and "date" in body

    asyncio.run(scenario())


def test_quick_log_rejects_zero_and_unknown_account(monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = QuickAddLogScreen()
            await app.push_screen(screen)
            for _ in range(40):
                await pilot.pause(0.02)
                if screen._accounts:
                    break
            _enter(screen, "")  # date
            _enter(screen, "x")  # title
            _enter(screen, "0")  # amount zero → rejected, stays on amount
            assert screen._key == "amount"
            _enter(screen, "-5.00")  # valid → advance to account
            _enter(screen, "Nonexistent")  # no match → rejected, stays on account
            assert screen._key == "account"

    asyncio.run(scenario())
