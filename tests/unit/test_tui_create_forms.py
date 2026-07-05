"""Phase 2 create-form tests (new hashtag / category / account, fake client)."""

import asyncio

from textual.widgets import Input

from expense.tui.app import ExpenseApp
from expense.tui.screens.create_forms import (
    NewAccountScreen,
    NewCategoryScreen,
    NewHashtagScreen,
)
from tests.unit.helpers import wait_for


def _enter(screen, text):
    screen.query_one("#bar", Input).value = text
    screen._recompute(text)
    screen.on_input_submitted(None)


def _run(fake_client, screen, steps):
    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            await app.push_screen(screen)
            await pilot.pause(0.05)
            for text in steps:
                _enter(screen, text)
            await wait_for(pilot, lambda: fake_client.posts)
            return fake_client.posts[0]

    return asyncio.run(scenario())


def test_new_hashtag_posts_name(fake_client):
    path, body = _run(fake_client, NewHashtagScreen(), ["#groceries"])  # last field → submits
    assert path == "/hashtags"
    assert body["name"] == "groceries" and "id" in body  # leading # stripped


def test_new_category_requires_color_then_posts(fake_client):
    # name, then pick a color (type 'green' → matches the palette)
    path, body = _run(fake_client, NewCategoryScreen(), ["Educación", "green"])
    assert path == "/categories"
    assert body["name"] == "Educación" and body["color"] == "#5ab87a"


def test_new_account_bank_only_with_currency(fake_client):
    # name, currency PEN, skip color (empty → optional)
    path, body = _run(fake_client, NewAccountScreen(), ["Interbank Sueldo", "PEN", ""])
    assert path == "/accounts"
    assert body["name"] == "Interbank Sueldo" and body["currency_code"] == "PEN"
    assert "color" not in body and "is_person" not in body  # bank-only, no person flag


def test_new_account_required_name_blocks_submit(fake_client):
    async def scenario():
        app = ExpenseApp(no_cache=True)
        async with app.run_test() as pilot:
            screen = NewAccountScreen()
            await app.push_screen(screen)
            await pilot.pause(0.05)
            screen.action_submit()  # nothing entered
            await pilot.pause(0.1)
            assert not fake_client.calls

    asyncio.run(scenario())
