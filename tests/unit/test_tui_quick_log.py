"""Phase 2 quick-add Log screen tests (normal + transfer flows, fake client)."""

import asyncio

import pytest
from textual.widgets import Input

from expense.errors import EngineConnectionError
from expense.tui.app import ExpenseApp
from expense.tui.screens.quick_log import QuickAddLogScreen, amount_to_text, parse_amount
from tests.unit.helpers import wait_for

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


def _patch(monkeypatch):
    """Screen-specific patches; the client/config seams come from fake_client.

    Name maps derive from the same fetches since backlog 6.5b — no separate
    load_*_name_map seams to patch.
    """
    monkeypatch.setattr("expense.commands.accounts_cmd.fetch_accounts", lambda *a, **k: ACCOUNTS)
    monkeypatch.setattr(
        "expense.commands.categories_cmd.fetch_categories", lambda *a, **k: CATEGORIES
    )
    monkeypatch.setattr("expense.commands.hashtags_cmd.fetch_hashtags", lambda *a, **k: HASHTAGS)


def _enter(screen, text):
    screen.query_one("#bar", Input).value = text
    screen._recompute_suggestions(text)
    screen.on_input_submitted(None)


async def _wait_loaded(screen, pilot):
    await wait_for(pilot, lambda: screen._accounts)


TXN = {
    "id": "tx1",
    "date": "2026-06-20T00:00:00Z",
    "title": "Farmacia",
    "amount_cents": -4250,
    "account_id": "acc1",
    "category_id": "cat1",
    "cleared": False,
    "hashtag_ids": ["h1"],
    "description": "receta",
}


def test_load_entities_three_superset_queries(fake_client, monkeypatch):
    """The form loads each resource once (include_archived) and derives both
    the active-only pools and the full name maps — three queries, not six
    (backlog 6.5b)."""
    calls: list[tuple[str, bool]] = []
    archived = {"id": "accX", "name": "Old bank", "currency_code": "PEN", "is_archived": True}

    def rec(name, payload):
        def fetch(cfg, *a, **k):
            calls.append((name, bool(k.get("include_archived"))))
            return payload

        return fetch

    monkeypatch.setattr(
        "expense.commands.accounts_cmd.fetch_accounts", rec("accounts", [*ACCOUNTS, archived])
    )
    monkeypatch.setattr(
        "expense.commands.categories_cmd.fetch_categories", rec("categories", CATEGORIES)
    )
    monkeypatch.setattr("expense.commands.hashtags_cmd.fetch_hashtags", rec("hashtags", HASHTAGS))

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = QuickAddLogScreen()
            await app.push_screen(screen)
            await _wait_loaded(screen, pilot)
            assert sorted(calls) == [("accounts", True), ("categories", True), ("hashtags", True)]
            assert "accX" not in [a[0] for a in screen._accounts]  # archived out of the pool
            assert screen._acc_names.get("accX") == "Old bank"  # but resolvable in the map

    asyncio.run(scenario())


def test_edit_with_null_hashtag_ref_renders_dash_not_crash(fake_client, monkeypatch):
    """A record carrying a null reference id must render the shared em-dash
    fallback instead of TypeError-ing on None[:8] (backlog 6.2e)."""
    _patch(monkeypatch)
    record = {**TXN, "hashtag_ids": ["h1", None]}

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = QuickAddLogScreen(record=record, resource="transactions")
            await app.push_screen(screen)
            await _wait_loaded(screen, pilot)
            await pilot.pause(0.05)
            assert app.is_running
            assert "—" in screen._display["hashtags"]  # null id → em-dash
            assert "—" in screen._tag_display_names()

    asyncio.run(scenario())


def test_quick_log_normal_flow_submits_payload(fake_client, monkeypatch):
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
            await wait_for(pilot, lambda: fake_client.posts)
            path, body = fake_client.posts[0]
            assert path == "/transactions"
            assert body["amount_cents"] == -9992 and body["account_id"] == "acc1"
            assert body["category_id"] == "cat1" and body["hashtag_ids"] == ["h1"]
            assert "transfer" not in body

    asyncio.run(scenario())


def test_quick_log_transfer_flow_submits_pair(fake_client, monkeypatch):
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
            await wait_for(pilot, lambda: fake_client.posts)
            path, body = fake_client.posts[0]
            assert path == "/transactions"
            assert body["amount_cents"] == -50000 and body["account_id"] == "acc1"
            assert "category_id" not in body  # engine assigns it for transfers
            assert body["transfer"]["account_id"] == "acc3"
            assert body["transfer"]["amount_cents"] == 50000  # opposite sign
            assert "hashtag_ids" not in body  # transfers skip hashtags

    asyncio.run(scenario())


def test_to_amount_flip_pins_engine_opposite_sign_rule(fake_client, monkeypatch):
    """The to-amount auto-sign is a sanctioned client-side mirror of the
    engine's zero-sum transfer rule (backlog 2.1, cli-spec.md "Sanctioned
    exceptions"): a typed magnitude — even an explicitly signed one — always
    commits opposite to Amount, and the summary shows the signed value."""
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = QuickAddLogScreen()
            await app.push_screen(screen)
            await _wait_loaded(screen, pilot)
            _enter(screen, "")  # date
            _enter(screen, "Move to savings")  # title
            _enter(screen, "-500")  # amount (from) — expense
            _enter(screen, "BCP P")  # account → BCP PEN
            _enter(screen, "Ahorr")  # transfer to → Ahorros
            _enter(screen, "-300")  # typed sign is overridden: opposite of −500 is +
            assert screen._values["to_amount"] == 30000
            assert screen._display["to_amount"] == "300.00"

    asyncio.run(scenario())


def test_to_amount_flip_negative_when_amount_positive(fake_client, monkeypatch):
    """Reverse direction of the 2.1 rule: a positive Amount makes the
    destination leg the expense side."""
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = QuickAddLogScreen()
            await app.push_screen(screen)
            await _wait_loaded(screen, pilot)
            _enter(screen, "")  # date
            _enter(screen, "Pull from savings")  # title
            _enter(screen, "500")  # amount (from) — income into the source
            _enter(screen, "BCP P")  # account → BCP PEN
            _enter(screen, "Ahorr")  # transfer to → Ahorros
            _enter(screen, "300")  # unsigned magnitude → destination leg is negative
            assert screen._values["to_amount"] == -30000
            assert screen._display["to_amount"] == "-300.00"

    asyncio.run(scenario())


def test_quick_log_guards_double_submit(fake_client, monkeypatch):
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
            await wait_for(pilot, lambda: fake_client.posts)
            await pilot.pause(0.1)
            assert len(fake_client.posts) == 1

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


def test_edit_prefills_and_puts_only_changed_fields(fake_client, monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = QuickAddLogScreen(record=TXN, resource="transactions")
            await app.push_screen(screen)
            await _wait_loaded(screen, pilot)
            assert screen._mode == "edit"
            assert screen._values["title"] == "Farmacia" and screen._values["amount"] == -4250
            # change just the title, then save
            screen._current = screen._sequence().index("title")
            _enter(screen, "Farmacia Inkafarma")
            screen.action_submit()
            await wait_for(pilot, lambda: fake_client.puts)
            path, body = fake_client.puts[0]
            assert path == "/transactions/tx1"
            assert body == {"title": "Farmacia Inkafarma"}  # diff only
            assert not fake_client.posts  # never POSTs in edit mode

    asyncio.run(scenario())


def test_edit_add_hashtag_puts_merged_hashtag_ids(fake_client, monkeypatch):
    """Hashtag appends must survive the edit diff — the snapshot must not alias (backlog 1.2)."""
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = QuickAddLogScreen(record=TXN, resource="transactions")
            await app.push_screen(screen)
            await _wait_loaded(screen, pilot)
            screen._current = screen._sequence().index("hashtags")
            _enter(screen, "trav")  # add #traveling next to the pre-existing #dog
            assert screen._values["hashtags"] == ["h1", "h2"]
            screen.action_submit()
            await wait_for(pilot, lambda: fake_client.puts)
            path, body = fake_client.puts[0]
            assert path == "/transactions/tx1"
            assert body == {"hashtag_ids": ["h1", "h2"]}  # diff only, both tags
            assert not fake_client.posts

    asyncio.run(scenario())


def test_edit_no_changes_does_not_submit(fake_client, monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = QuickAddLogScreen(record=TXN, resource="transactions")
            await app.push_screen(screen)
            await _wait_loaded(screen, pilot)
            screen.action_submit()  # nothing changed
            await pilot.pause(0.1)
            assert not fake_client.calls

    asyncio.run(scenario())


def test_edit_transfer_leg_locks_amount_account_date():
    leg = {**TXN, "transfer_transaction_id": "sibling1"}
    screen = QuickAddLogScreen(record=leg, resource="transactions")
    assert screen._locked == {"amount", "account", "date"}
    # the first editable field skips the locked date → title
    assert screen._sequence()[screen._first_editable()] == "title"


def test_edit_inbox_sequence_has_no_hashtags():
    screen = QuickAddLogScreen(record={"id": "i1", "title": "x"}, resource="inbox")
    assert "hashtags" not in screen._sequence()
    assert "cleared" in screen._sequence()


def test_quick_log_rejects_zero_and_unknown_account(fake_client, monkeypatch):
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


def test_quick_log_fetch_error_notifies_not_crash(fake_client, monkeypatch):
    """An engine/config error in _load_entities must not exit the app (backlog 1.3)."""
    _patch(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("engine down")

    monkeypatch.setattr("expense.commands.accounts_cmd.fetch_accounts", boom)
    notices: list = []
    monkeypatch.setattr(
        QuickAddLogScreen, "notify", lambda self, message, **kw: notices.append(message)
    )

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = QuickAddLogScreen()
            await app.push_screen(screen)
            await wait_for(pilot, lambda: notices)
            assert notices and "engine down" in notices[0]
            assert app.is_running
            assert app.screen is screen

    asyncio.run(scenario())


def test_quick_log_fetch_error_uses_canonical_renderer(fake_client, monkeypatch):
    """Engine errors surface with the canonical text, not bare str(exc) (backlog 2.1)."""
    _patch(monkeypatch)

    def boom(*a, **k):
        raise EngineConnectionError(url="https://x.invalid", original=Exception("refused"))

    monkeypatch.setattr("expense.commands.accounts_cmd.fetch_accounts", boom)
    notices: list = []
    monkeypatch.setattr(
        QuickAddLogScreen, "notify", lambda self, message, **kw: notices.append(message)
    )

    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = QuickAddLogScreen()
            await app.push_screen(screen)
            await wait_for(pilot, lambda: notices)
            assert notices and "could not reach engine at https://x.invalid" in notices[0]

    asyncio.run(scenario())
