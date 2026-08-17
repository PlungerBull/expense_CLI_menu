"""Phase 2 create-form tests (new hashtag / category / account, fake client)."""

import asyncio

from textual.widgets import Input

from expense.tui.app import ExpenseApp
from expense.tui.screens.create_forms import (
    EditAccountScreen,
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
        app = ExpenseApp()
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


def test_new_account_defaults_to_bank_on_empty_type(fake_client):
    """Empty enter on TYPE keeps `bank` — adding an account costs no extra decision."""
    # type (empty → the prefilled bank), name, currency PEN, skip color
    path, body = _run(fake_client, NewAccountScreen(), ["", "Interbank Sueldo", "PEN", ""])
    assert path == "/accounts"
    assert body["name"] == "Interbank Sueldo" and body["currency_code"] == "PEN"
    assert "color" not in body
    # `is_person` is a 422 on both routes — the endpoint is the flag, never a field.
    assert "is_person" not in body


def test_new_account_type_person_posts_to_people(fake_client):
    """Picking `person` routes the same fields to POST /people (backlog 6.2)."""
    path, body = _run(fake_client, NewAccountScreen(), ["person", "Eliana", "PEN", ""])
    assert path == "/people"
    assert body["name"] == "Eliana" and body["currency_code"] == "PEN"
    assert "is_person" not in body


def test_edit_account_locks_type_and_currency(fake_client):
    """`is_person` is creation-time-only, so editing shows TYPE read-only."""
    screen = EditAccountScreen(
        {"id": "abc", "name": "Eliana", "currency_code": "PEN", "is_person": True}
    )
    assert screen._locked == {"currency", "type"}
    assert screen._values["type"] == "person"
    assert screen._submit_request()[:2] == ("PUT", "/accounts/abc")
    assert "is_person" not in screen._payload()


def test_new_account_required_name_blocks_submit(fake_client):
    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = NewAccountScreen()
            await app.push_screen(screen)
            await pilot.pause(0.05)
            screen.action_submit()  # nothing entered
            await pilot.pause(0.1)
            assert not fake_client.calls

    asyncio.run(scenario())
