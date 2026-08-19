"""Guard: every modal's #modal box must actually render (non-zero size).

Regression armor for the Textual 8.x collapse — `width: auto` on #modal inside
`align: center middle` measured to 0, so the box shrank to an empty border and
every modal (Enter's detail view, the archive/delete confirm, activity
before/after) went invisible. app.tcss now sets a definite width; this test
fails loudly if a future Textual bump (or a stray edit) reintroduces the
collapse. Asserting the *screen* was pushed is not enough — the old tests did
that and still passed while the box rendered empty; we assert it has size.
"""

import asyncio

from expense.tui.app import ExpenseApp
from expense.tui.screens.modals import ConfirmModal, PromptModal, RecordModal, SnapshotModal
from tests.unit.helpers import wait_for

_RECORD = {
    "id": "a1",
    "name": "BCP USD",
    "currency_code": "PEN",
    "is_archived": False,
    "color": "#4a90d9",
}
_BEFORE = {"name": "Old name", "is_archived": False}
_AFTER = {"name": "BCP USD", "is_archived": True}

_MODALS = [
    lambda: RecordModal("Account · BCP USD", _RECORD),
    lambda: ConfirmModal("Archive account?", "Archive BCP USD."),
    lambda: PromptModal("Rename", "New name"),
    lambda: SnapshotModal("Change", _BEFORE, _AFTER),
]


def test_every_modal_box_renders_with_size():
    async def scenario():
        app = ExpenseApp()
        async with app.run_test(size=(100, 40)) as pilot:
            for make_modal in _MODALS:
                modal = make_modal()
                await app.push_screen(modal)
                await wait_for(pilot, lambda: app.screen.query("#modal"))
                box = app.screen.query_one("#modal")
                name = type(app.screen).__name__
                # A collapsed box is an empty border — the exact failure we guard.
                assert box.size.width > 10, f"{name} #modal collapsed: {box.size}"
                assert box.size.height > 2, f"{name} #modal collapsed: {box.size}"
                app.pop_screen()
                await wait_for(pilot, lambda: not app.screen.query("#modal"))

    asyncio.run(scenario())
