"""Phase 2 quick-add Log screen tests (fake client)."""

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
        {"id": "catO", "name": "@Opening", "is_system": True, "system_key": "opening_balance"},
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
    "hashtag_ids": ["h1"],
    "description": "receta",
}


def test_load_entities_three_superset_queries(fake_client, monkeypatch):
    """The form loads each resource once and derives both the suggestion pools
    and the full name maps — three queries, not six (backlog 6.5b). Only the
    accounts fetch is a superset (include_archived); categories/hashtags lost
    archive in the 2026-08-06 schema slimming."""
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
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = QuickAddLogScreen()
            await app.push_screen(screen)
            await _wait_loaded(screen, pilot)
            assert sorted(calls) == [("accounts", True), ("categories", False), ("hashtags", False)]
            assert "accX" not in [a[0] for a in screen._accounts]  # archived out of the pool
            assert screen._acc_names.get("accX") == "Old bank"  # but resolvable in the map

    asyncio.run(scenario())


def test_edit_with_null_hashtag_ref_renders_dash_not_crash(fake_client, monkeypatch):
    """A record carrying a null reference id must render the shared em-dash
    fallback instead of TypeError-ing on None[:8] (backlog 6.2e)."""
    _patch(monkeypatch)
    record = {**TXN, "hashtag_ids": ["h1", None]}

    async def scenario():
        app = ExpenseApp()
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
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = QuickAddLogScreen()
            await app.push_screen(screen)
            await _wait_loaded(screen, pilot)
            _enter(screen, "")  # date
            _enter(screen, "Dog walker")  # title
            _enter(screen, "-99.92")  # amount
            _enter(screen, "BCP P")  # account → BCP PEN
            _enter(screen, "Masco")  # category → Mascotas
            _enter(screen, "#dog")  # hashtag add (# stripped)
            _enter(screen, "")  # hashtags done
            _enter(screen, "")  # note → creates
            await wait_for(pilot, lambda: fake_client.posts)
            path, body = fake_client.posts[0]
            assert path == "/transactions"
            assert body["amount_cents"] == -9992 and body["account_id"] == "acc1"
            assert body["category_id"] == "cat1" and body["hashtag_ids"] == ["h1"]
            assert "transfer" not in body  # fail-closed: feature removed 2026-08-10

    asyncio.run(scenario())


def test_quick_log_guards_double_submit(fake_client, monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp()
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
        app = ExpenseApp()
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
        app = ExpenseApp()
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


def test_edit_draft_puts_hashtag_ids_to_inbox(fake_client, monkeypatch):
    """The same picker, on a draft, writes to /inbox — the 6.1 payoff.

    Proves the un-gated field is not merely displayed: the tag reaches
    `PUT /inbox/{id}` under the engine's field name.
    """
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            draft = {**TXN, "id": "i1", "hashtag_ids": []}
            screen = QuickAddLogScreen(record=draft, resource="inbox")
            await app.push_screen(screen)
            await _wait_loaded(screen, pilot)
            screen._current = screen._sequence().index("hashtags")
            _enter(screen, "trav")
            screen.action_submit()
            await wait_for(pilot, lambda: fake_client.puts)
            path, body = fake_client.puts[0]
            assert path == "/inbox/i1"
            assert body == {"hashtag_ids": ["h2"]}

    asyncio.run(scenario())


def test_edit_draft_clearing_tags_sends_empty_list(fake_client, monkeypatch):
    """Clearing must send `[]` (the engine's clear), never drop the key or send null."""
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            draft = {**TXN, "id": "i1", "hashtag_ids": ["h1"]}
            screen = QuickAddLogScreen(record=draft, resource="inbox")
            await app.push_screen(screen)
            await _wait_loaded(screen, pilot)
            screen._values["hashtags"] = []
            screen.action_submit()
            await wait_for(pilot, lambda: fake_client.puts)
            path, body = fake_client.puts[0]
            assert path == "/inbox/i1"
            assert body == {"hashtag_ids": []}

    asyncio.run(scenario())


def test_edit_no_changes_does_not_submit(fake_client, monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = QuickAddLogScreen(record=TXN, resource="transactions")
            await app.push_screen(screen)
            await _wait_loaded(screen, pilot)
            screen.action_submit()  # nothing changed
            await pilot.pause(0.1)
            assert not fake_client.calls

    asyncio.run(scenario())


def test_no_form_offers_cleared():
    """`cleared` is gone from the ledger — no form may offer it.

    The engine deleted the column 2026-08-16 (sql/035). Sending it is a 422 on an
    unknown field, which rejects the whole body, so a lingering row here would lose
    an entire edit. Nothing replaces it: a row is confirmed by belonging to a
    completed reconciliation that adds up.
    """
    for screen in (
        QuickAddLogScreen(),
        QuickAddLogScreen(record={"id": "t1", "title": "x"}, resource="transactions"),
        QuickAddLogScreen(record={"id": "i1", "title": "x"}, resource="inbox"),
    ):
        assert "cleared" not in screen._sequence()


def test_edit_sequence_offers_hashtags_for_both_resources():
    """Drafts and transactions get the identical field sequence (backlog 6.1, 2026-08-16).

    This was the gap the resource gate created: a draft could be tagged at
    creation and never re-tagged, even though the engine has accepted
    `hashtag_ids` on `PUT /inbox/{id}` since 2026-08-14 and the tags survive
    promotion. The gate was one line; removing it was the whole fix.
    """
    draft = QuickAddLogScreen(record={"id": "i1", "title": "x"}, resource="inbox")
    tx = QuickAddLogScreen(record={"id": "t1", "title": "x"}, resource="transactions")
    assert "hashtags" in draft._sequence()
    assert draft._sequence() == tx._sequence()


def test_quick_log_rejects_zero_and_unknown_account(fake_client, monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp()
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
        app = ExpenseApp()
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
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = QuickAddLogScreen()
            await app.push_screen(screen)
            await wait_for(pilot, lambda: notices)
            assert notices and "could not reach engine at https://x.invalid" in notices[0]

    asyncio.run(scenario())
