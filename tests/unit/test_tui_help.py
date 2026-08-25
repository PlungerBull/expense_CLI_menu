"""Phase 8 — the `?` key card, and the removal of the command palette.

Approved as variant C in docs/mockups/expense-world-phase8-discoverability.html
(2026-08-17). The card is *derived* from BINDINGS rather than hand-listed, so the
tests that matter here are the ones that fail when the derivation drifts:

  · every binding we declare has text for the card to show (the guard)
  · Textual's own widget keys stay out, without a suppression list
  · a key the screen cannot actually service is not advertised
  · the palette is off, and the footer no longer offers it
"""

import asyncio
import importlib
import io
import pkgutil

from rich.console import Console
from textual.binding import Binding

import expense.tui as tui_pkg
from expense.tui.app import ExpenseApp
from expense.tui.screens._form import form_bindings
from expense.tui.screens.accounts import AccountsScreen
from expense.tui.screens.help import (
    FOLD_INTO,
    HelpModal,
    declared_bindings,
    key_rows,
    render_card,
    screen_inventory,
)
from expense.tui.screens.inbox import InboxScreen
from expense.tui.widgets.cursor_list import CursorList
from tests.unit.helpers import wait_for, wait_for_loaded


def _stub_engine(monkeypatch, items=()):
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())
    monkeypatch.setattr(
        "expense.commands.accounts_cmd.fetch_accounts", lambda cfg, **k: {"items": list(items)}
    )
    monkeypatch.setattr(
        "expense.commands.inbox_cmd.fetch_inbox", lambda cfg, **k: {"items": [], "total": 0}
    )


def _card_text(groups) -> str:
    console = Console(width=66, file=io.StringIO(), record=True, legacy_windows=False)
    console.print(render_card(groups, "#000000"))
    return console.export_text()


def _titles(groups) -> list[str]:
    return [group.title for group in groups]


def _rows(groups, title):
    return next(group.rows for group in groups if group.title == title)


# ---------------------------------------------------------------------------
# the guard: nothing we declare may be undocumented
# ---------------------------------------------------------------------------


def _declaring_classes():
    """Every class under expense.tui that declares BINDINGS in its own body."""
    for info in pkgutil.walk_packages(tui_pkg.__path__, f"{tui_pkg.__name__}."):
        module = importlib.import_module(info.name)
        for obj in vars(module).values():
            if not isinstance(obj, type) or obj.__module__ != module.__name__:
                continue
            if "BINDINGS" in obj.__dict__:
                yield obj


def test_every_declared_binding_has_help_text():
    """The card can only show what the binding carries.

    A binding added with no description and no tooltip renders as a row with a
    blank right-hand side — exactly the defect that makes Textual's own panel
    hard to read (the `↑ k` row captured in the mockup §1.2). Folded inverses are
    the one exception: they are absorbed into their partner's row.
    """
    undocumented = []
    for klass in _declaring_classes():
        for item in klass.__dict__["BINDINGS"]:
            for binding in Binding.make_bindings([item]):
                if binding.action in FOLD_INTO:
                    continue
                if not (binding.tooltip or binding.description):
                    undocumented.append(f"{klass.__name__}: {binding.key} → {binding.action}")
    assert not undocumented, f"bindings with nothing for the ? card to show: {undocumented}"


def test_folded_bindings_still_carry_their_word():
    """A folded inverse renders as `(k / ↑ up)` — it needs its description even
    though it never gets a row, or the parenthetical reads `(k / ↑ )`."""
    for klass in _declaring_classes():
        for item in klass.__dict__["BINDINGS"]:
            for binding in Binding.make_bindings([item]):
                if binding.action in FOLD_INTO:
                    assert binding.description, f"{klass.__name__}: {binding.key} has no word"


# ---------------------------------------------------------------------------
# derivation
# ---------------------------------------------------------------------------


def test_declared_bindings_keeps_only_our_own():
    """Textual's OptionList contributes home/end/tab/left/right/ctrl+c to a
    CursorList at runtime. None are ours to document, and none may appear —
    achieved by walking the MRO for *declaring* classes, not by a suppression
    list that would rot as Textual changes."""
    keys = {binding.key for binding in declared_bindings(CursorList)}
    assert keys == {"down", "j", "up", "k", "enter", "pagedown", "full_stop", "pageup", "comma"}
    for intruder in ("home", "end", "tab", "shift+tab", "left", "right", "ctrl+c"):
        assert intruder not in keys


def test_rows_join_keys_typed_character_first():
    """`j / ↓` and `. / pgdn`, not the reverse: the letter is what you press."""
    rows = {row.description: row.keys for row in key_rows(declared_bindings(CursorList))}
    assert rows["Down"] == "j / ↓"
    assert rows["Next page"] == ". / pgdn"
    assert rows["Previous page"] == ", / pgup"
    assert rows["Open"] == "⏎"


def test_inverse_alias_folds_into_its_partner_row():
    """`up,k` is `show=False` and has no row of its own — it rides along on the
    down row instead of becoming a blank-description row."""
    rows = key_rows(declared_bindings(CursorList))
    assert not any(row.keys == "k / ↑" for row in rows)
    down = next(row for row in rows if row.description == "Down")
    assert down.note == "(k / ↑ up)"


def test_refresh_and_back_sort_to_the_end():
    """Every screen has them, so leading with them buries what is specific."""
    rows = key_rows(declared_bindings(AccountsScreen))
    assert [row.description for row in rows][-2:] == ["Refresh", "Back"]


def test_tooltip_beats_description():
    """The footer label stays terse; the card says what the key does. Both come
    from one declaration, so they cannot describe different behaviour."""
    rows = {row.description for row in key_rows(declared_bindings(AccountsScreen))}
    assert "Archive / unarchive" in rows  # tooltip
    assert "Archive" not in rows  # the footer's word


# ---------------------------------------------------------------------------
# the assembled card
# ---------------------------------------------------------------------------


def test_accounts_card_matches_the_approved_layout(monkeypatch):
    """Variant C: four blocks, screen keys and conventions left, list keys and
    app-wide keys right."""
    _stub_engine(monkeypatch)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test(size=(100, 32)) as pilot:
            await app.push_screen(AccountsScreen())
            await wait_for_loaded(pilot, app)
            await pilot.pause()
            title, groups = screen_inventory(app.screen)

            assert title == "Keys — Accounts"
            assert _titles(groups) == [
                "This screen",
                "Moving around",
                "Always true",
                "Everywhere",
            ]
            assert [row.description for row in _rows(groups, "This screen")] == [
                "New",
                "Edit",
                "Archive / unarchive",
                "Refresh",
                "Back",
            ]
            text = _card_text(groups)
            # the two columns' second blocks start on the same line
            lines = text.split("\n")
            conventions = next(i for i, line in enumerate(lines) if "Always true" in line)
            assert "Everywhere" in lines[conventions]
            # nothing overflows the 66-column card
            assert max(len(line) for line in lines) <= 66

    asyncio.run(scenario())


def test_help_never_advertises_a_key_the_screen_cannot_service(monkeypatch):
    """`enter` is a literal no-op on the Manage lists (tui-plan §4.1) because no
    screen there handles CursorList.Selected. Inbox does handle it. The card has
    to tell those two apart, or it is documenting a key that does nothing."""
    _stub_engine(monkeypatch)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test(size=(100, 32)) as pilot:
            await app.push_screen(AccountsScreen())
            await wait_for_loaded(pilot, app)
            await pilot.pause()
            _, manage = screen_inventory(app.screen)
            app.pop_screen()

            await app.push_screen(InboxScreen())
            await wait_for_loaded(pilot, app)
            await pilot.pause()
            _, inbox = screen_inventory(app.screen)

            assert not any(r.description == "Open" for r in _rows(manage, "Moving around"))
            assert any(r.description == "Open" for r in _rows(inbox, "Moving around"))

    asyncio.run(scenario())


def test_home_card_names_itself_without_a_crumb():
    """Home paints its own header and has no crumb, so the title falls back to
    the class name rather than rendering a bare `Keys`."""

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            title, groups = screen_inventory(app.screen)
            assert title == "Keys — Home"
            # `+` joined `q` on 2026-08-20, when `Log a transaction` stopped being a
            # menu row. The card is now the only place the key is written down in
            # full, so this assertion is what keeps it discoverable.
            assert [row.keys for row in _rows(groups, "This screen")] == ["+", "q"]

    asyncio.run(scenario())


def test_question_mark_opens_and_closes_the_card(monkeypatch):
    """`?` is a peek: the key that opens it closes it, and so does esc."""
    _stub_engine(monkeypatch)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test(size=(100, 32)) as pilot:
            await app.push_screen(AccountsScreen())
            await wait_for_loaded(pilot, app)
            await pilot.press("question_mark")
            await wait_for(pilot, lambda: isinstance(app.screen, HelpModal))
            await pilot.press("question_mark")
            await wait_for(pilot, lambda: not isinstance(app.screen, HelpModal))
            await pilot.press("question_mark")
            await wait_for(pilot, lambda: isinstance(app.screen, HelpModal))
            await pilot.press("escape")
            await wait_for(pilot, lambda: not isinstance(app.screen, HelpModal))

    asyncio.run(scenario())


def test_question_mark_types_a_character_inside_a_form(monkeypatch):
    """Decided 2026-08-17: forms keep `?` as a typed character. A focused Input
    swallows printable keys, so no overlay opens and the note field gets its
    question mark — the behaviour we want, pinned so a later app-level binding
    cannot quietly take the key away."""
    _stub_engine(monkeypatch)
    monkeypatch.setattr(
        "expense.commands.accounts_cmd.fetch_accounts", lambda cfg, **k: {"items": []}
    )
    monkeypatch.setattr(
        "expense.commands.categories_cmd.fetch_categories", lambda cfg, **k: {"items": []}
    )
    monkeypatch.setattr(
        "expense.commands.hashtags_cmd.fetch_hashtags", lambda cfg, **k: {"items": []}
    )

    async def scenario():
        from textual.widgets import Input

        from expense.tui.screens.create_forms import NewHashtagScreen

        app = ExpenseApp()
        async with app.run_test(size=(100, 32)) as pilot:
            await app.push_screen(NewHashtagScreen())
            await pilot.pause()
            await pilot.press("question_mark")
            await pilot.pause()
            assert not isinstance(app.screen, HelpModal)
            assert "?" in app.screen.query_one("#bar", Input).value

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# the palette is gone
# ---------------------------------------------------------------------------


def test_command_palette_is_disabled():
    """Removed 2026-08-17 (docs/decisions.md). Textual's Footer gates its
    `^p palette` key on this same flag, so the strip leaves every footer with
    it — that shared flag is why no footer code was touched."""
    assert ExpenseApp.ENABLE_COMMAND_PALETTE is False


def test_footer_no_longer_offers_the_palette(monkeypatch):
    _stub_engine(monkeypatch)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test(size=(100, 32)) as pilot:
            await app.push_screen(AccountsScreen())
            await wait_for_loaded(pilot, app)
            await pilot.pause()
            from textual.widgets import Footer

            footer = app.screen.query_one(Footer)
            assert not footer.query(".-command-palette")

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# the bar-form footer
# ---------------------------------------------------------------------------


def test_form_navigation_keys_are_not_advertised():
    """The form footer offers only `esc Cancel` and `^s Save` (2026-08-24).

    Two separate reasons, one outcome. `↑` / `↓` walk the suggestion list — the
    plain-arrow navigation the list, tree and checklist widgets already stopped
    advertising in the 2026-08-20 footer trim, which missed the forms. `^↑` /
    `^↓` move between fields and **never worked on macOS**: the OS takes `⌃↑`
    for Mission Control and `⌃↓` for Application Windows before the terminal
    sees them, so the form was advertising two dead keys.

    All four stay *bound* — they work wherever those system shortcuts are off,
    and the replacement is still unpicked (docs/todo.md "Field navigation in
    the edit form is broken on macOS"). This guard is
    what fails if someone re-adds one as a plain tuple, which defaults to shown.
    """
    bindings = [
        binding for item in form_bindings("Save") for binding in Binding.make_bindings([item])
    ]
    by_key = {binding.key: binding for binding in bindings}

    assert {key for key, b in by_key.items() if b.show} == {"escape", "ctrl+s"}
    for key in ("up", "down", "ctrl+up", "ctrl+down"):
        assert by_key[key].show is False, f"{key} is advertised in the form footer"
        # the card guard above still applies: hidden or not, a binding we
        # declare carries text.
        assert by_key[key].description
