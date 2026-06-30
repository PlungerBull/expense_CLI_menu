"""Phase 2 quick-add Log screen tests (normal + transfer flows, fake client)."""

import asyncio

import pytest
from textual.widgets import Input

from expense.tui.app import ExpenseApp
from expense.tui.screens.quick_log import QuickAddLogScreen, amount_to_text, parse_amount

ACCOUNTS = [
    {"id": "acc1", "name": "BCP PEN", "currency_code": "PEN", "is_person": False},
    {"id": "acc2", "name": "BCP USD", "currency_code": "USD", "is_person": False},
    {"id": "acc3", "name": "Ahorros", "currency_code": "PEN", "is_person": False},
]
CATEGORIES = {
    "items": [
        {"id": "cat1", "name": "Mascotas", "is_system": False},
        {"id": "catT", "name": "@Transfer", "is_system": True, "system_key": "transfer"},
    ]
}
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
    screen.query_one("#bar", Input).value = text
    screen._recompute_suggestions(text)
    screen.on_input_submitted(None)


async def _wait_loaded(screen, pilot):
    for _ in range(40):
        await pilot.pause(0.02)
        if screen._accounts:
            return


async def _wait_post(pilot):
    for _ in range(40):
        await pilot.pause(0.02)
        if _FakeClient.calls:
            return


def test_quick_log_normal_flow_submits_payload(monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = QuickAddLogScreen()
            await app.push_screen(screen)
            await _wait_loaded(screen, pilot)
            _enter(screen, "")  # date
            _enter(screen, "Dog walker")  # title
            _enter(screen, "-99.92")  # amount
            _enter(screen, "BCP P")  # account → BCP PEN
            _enter(screen, "")  # transfer to? → skip (normal)
            _enter(screen, "Masco")  # category → Mascotas
            _enter(screen, "#dog")  # hashtag add (# stripped)
            _enter(screen, "")  # hashtags done
            _enter(screen, "")  # note → creates
            await _wait_post(pilot)
            path, body = _FakeClient.calls[0]
            assert path == "/transactions"
            assert body["amount_cents"] == -9992 and body["account_id"] == "acc1"
            assert body["category_id"] == "cat1" and body["hashtag_ids"] == ["h1"]
            assert "transfer" not in body

    asyncio.run(scenario())


def test_quick_log_transfer_flow_submits_pair(monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = QuickAddLogScreen()
            await app.push_screen(screen)
            await _wait_loaded(screen, pilot)
            _enter(screen, "")  # date
            _enter(screen, "Move to savings")  # title
            _enter(screen, "-500")  # amount (from)
            _enter(screen, "BCP P")  # account → BCP PEN
            _enter(screen, "Ahorr")  # transfer to → Ahorros (same currency PEN)
            assert screen._is_transfer()
            assert screen._values["to_amount"] == 50000  # auto-mirrored opposite sign
            _enter(screen, "")  # to amount → accept the auto value
            _enter(screen, "")  # note → creates
            await _wait_post(pilot)
            path, body = _FakeClient.calls[0]
            assert path == "/transactions"
            assert body["amount_cents"] == -50000 and body["account_id"] == "acc1"
            assert body["category_id"] == "catT"  # required; engine overrides
            assert body["transfer"]["account_id"] == "acc3"
            assert body["transfer"]["amount_cents"] == 50000  # opposite sign
            assert "hashtag_ids" not in body  # transfers skip hashtags

    asyncio.run(scenario())


def test_quick_log_guards_double_submit(monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = QuickAddLogScreen()
            await app.push_screen(screen)
            await pilot.pause(0.05)
            screen._values.update(title="x", amount=-500, account="acc1", category="cat1")
            screen.action_submit()
            screen.action_submit()  # in flight → ignored
            screen.action_submit()
            await _wait_post(pilot)
            await pilot.pause(0.1)
            assert len(_FakeClient.calls) == 1

    asyncio.run(scenario())


def test_suggest_window_keeps_highlight_visible():
    import io

    from rich.console import Console

    screen = QuickAddLogScreen()
    screen._current = 3  # account (an entity field)
    screen._suggestions = [(f"c{i}", f"Cat{i}", "PEN") for i in range(20)]
    screen._suggest_idx = 17
    con = Console(file=io.StringIO(), width=60)
    con.print(screen._suggest_renderable())
    out = con.file.getvalue()
    assert "Cat17" in out and "more" in out


def test_quick_log_rejects_zero_and_unknown_account(monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = QuickAddLogScreen()
            await app.push_screen(screen)
            await _wait_loaded(screen, pilot)
            _enter(screen, "")  # date
            _enter(screen, "x")  # title
            _enter(screen, "0")  # amount zero → rejected, stays
            assert screen._key == "amount"
            _enter(screen, "-5.00")  # valid → account
            _enter(screen, "Nonexistent")  # no match → rejected, stays
            assert screen._key == "account"

    asyncio.run(scenario())
