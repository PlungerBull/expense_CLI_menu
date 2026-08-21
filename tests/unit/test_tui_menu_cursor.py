"""The home menu's cursor must be *visible* — regression armor for 2026-08-20.

The bug this guards: `theme.py` gives the block cursor no colour of its own
(`block-cursor-foreground`/`-background` are both `ansi_default`) and relies
entirely on `block-cursor-text-style: reverse` for contrast. Textual 8.2.7
drops `reverse` from `get_visual_style()` when both colours are `ansi_default`,
so the highlighted menu row rendered `default on default` — byte-identical to
every unselected row. The menu had no cursor at all and nothing failed.

That is the shape of failure to defend against: not a crash, not a wrong value,
but a style silently resolving to nothing. So these tests assert on the
*rendered* style of the strip, which is the only place the difference is real —
asserting on CSS or component styles would have passed throughout the bug
(`get_component_styles` reported `text_style: reverse` the whole time).
"""

import asyncio

from textual.widgets import OptionList

from expense.tui.app import ExpenseApp
from expense.tui.screens.home import HomeScreen
from expense.tui.widgets.cursor_list import CURSOR_STYLE, CursorOptionList


def _line_style(menu, y: int) -> str:
    """The rendered style of the first non-blank segment on row `y`."""
    for segment in menu.render_line(y)._segments:
        if segment.text.strip():
            return str(segment.style)
    return ""


def _run(scenario):
    asyncio.run(scenario())


def test_home_menu_uses_the_cursor_widget():
    """A plain OptionList would reintroduce the invisible cursor."""
    assert issubclass(CursorOptionList, OptionList)


def test_highlighted_row_renders_differently_from_its_neighbours(monkeypatch):
    """The whole point: the cursor row must not look like the rows around it."""
    monkeypatch.setattr(HomeScreen, "_load_stats", lambda self: None)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            menu = app.screen.query_one("#menu", CursorOptionList)
            assert menu.has_focus, "the menu must be focused for the cursor to mean anything"
            highlighted = menu.highlighted
            assert highlighted is not None

            cursor_row = _line_style(menu, highlighted)
            assert CURSOR_STYLE in cursor_row, f"cursor row is {cursor_row!r}"
            for y in (highlighted - 1, highlighted + 1):
                assert _line_style(menu, y) != cursor_row

    _run(scenario)


def test_cursor_follows_the_keyboard(monkeypatch):
    """Moving down must move the reverse bar, not just an internal index."""
    monkeypatch.setattr(HomeScreen, "_load_stats", lambda self: None)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            menu = app.screen.query_one("#menu", CursorOptionList)
            first = menu.highlighted
            await pilot.press("down")
            await pilot.pause()
            assert menu.highlighted == first + 1
            assert CURSOR_STYLE not in _line_style(menu, first)
            assert CURSOR_STYLE in _line_style(menu, first + 1)

    _run(scenario)


def test_group_headers_never_take_the_cursor(monkeypatch):
    """Disabled options are section labels; reversing one would read as selectable."""
    monkeypatch.setattr(HomeScreen, "_load_stats", lambda self: None)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            menu = app.screen.query_one("#menu", CursorOptionList)
            disabled = [i for i, opt in enumerate(menu.options) if opt.disabled]
            assert disabled, "the menu is built from group headers + entries"
            for index in disabled:
                assert CURSOR_STYLE not in _line_style(menu, index)

    _run(scenario)


def test_cursor_bar_spans_the_full_row(monkeypatch):
    """Reverse video must cover the row's padding too, or it reads as a ragged blob."""
    monkeypatch.setattr(HomeScreen, "_load_stats", lambda self: None)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            menu = app.screen.query_one("#menu", CursorOptionList)
            segments = menu.render_line(menu.highlighted)._segments
            assert segments
            assert all(CURSOR_STYLE in str(s.style) for s in segments), (
                "every segment on the cursor row, including trailing padding, "
                f"must carry {CURSOR_STYLE}"
            )

    _run(scenario)
