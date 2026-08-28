"""CursorList — a focusable, keyboard-navigable table list with a row cursor.

Reused by every list screen (inbox, transactions, accounts, categories...).
Rows are `(key, cells)` pairs: `key` identifies the row (e.g. a record id) and
is carried on the `Selected` message; `cells` are the column strings. `_build()`
is pure, so formatting is unit-testable without an event loop.

Every list renders at most `page_size` rows — min(20, what fits the terminal)
since 2026-07-13 (adaptive rows, pick A + cap 20; the screen measures and calls
`set_page_size` on resize); `pgdn`/`pgup` page. Two modes share the
one widget:

- window mode (default): `_rows` holds the full dataset and the visible
  window follows the cursor (`cursor // page_size`), so `↑`/`↓` walk straight
  through page boundaries and cursor-restore-after-write lands on the right
  page for free.
- fetched-page mode (`page_meta=(offset, total)`): `_rows` is one page a
  screen fetched with real limit/offset; the page keys post `PageRequested`
  and the screen refetches (see `PagedListMixin`). `↑`/`↓` clamp at the edge —
  paging is always a deliberate keypress (mockup pick A).

The widget is its own quiet-border panel (app.tcss): screens name it via
`title` (border title) and the page status renders in the border subtitle
(mockup pick B) — `rows 21-40 of 133 · page 2 of 7`.
"""

from collections.abc import Iterable, Sequence
from typing import NamedTuple

from rich import box
from rich.console import RenderableType
from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.strip import Strip
from textual.widgets import OptionList, Static

from expense.commands._resource import DEFAULT_PAGE_ROWS


def page_indicator(
    start: int, shown: int, total: int, page_size: int, *, unit: str = "rows"
) -> str | None:
    """`rows 21-40 of 133 · page 2 of 7`, or None when one page holds it all."""
    if total <= page_size:
        return None
    page = start // page_size + 1
    pages = -(-total // page_size)  # ceil
    return f"{unit} {start + 1}-{start + shown} of {total} · page {page} of {pages}"


#: How "you are here" is drawn, app-wide: reverse video — the terminal's own
#: foreground and background, swapped. Colour-free, so it is correct on a dark,
#: light or Solarized ground by construction rather than by detection (the ANSI
#: palette decision, 2026-08-19).
#:
#: It must be applied as a **Rich style**, never as a Textual `text-style` rule.
#: Textual 8.2.7 drops `reverse` from `get_visual_style()` when foreground and
#: background are both `ansi_default` — which is exactly our theme — so a CSS
#: cursor renders identically to an unselected row. That is what made the home
#: menu cursor invisible until 2026-08-20; see `CursorOptionList` below.
CURSOR_STYLE = "reverse"


class Row(NamedTuple):
    """One list row.

    ``key`` identifies the row (carried on ``Selected``/``Highlighted``);
    ``cells`` are the column values — plain strings or Rich renderables like a
    colored swatch; ``base_style`` is the Rich style applied when the row is not
    the cursor (e.g. ``"dim"`` for archived rows).
    """

    key: object
    cells: Sequence[object]
    base_style: str = ""

    @classmethod
    def coerce(cls, row: "RowInput") -> "Row":
        """Accept a plain ``(key, cells[, base_style])`` tuple — what the pure row
        builders return — or an existing Row; always return a Row."""
        return row if isinstance(row, cls) else cls(*row)


# Row builders return plain tuples; the widget coerces them at its boundary.
RowInput = Row | tuple


class CursorList(Static):
    can_focus = True
    BINDINGS = [
        # Not shown in the footer: "the arrow keys move the cursor" is not worth a
        # footer slot (user, 2026-08-20 — "its obvious and it just occupies space
        # unnecessarily"). The keys are unchanged and the `?` card still lists them,
        # which is where a key that needs explaining belongs.
        Binding("down", "move(1)", "Navigate", tooltip="Down", show=False),
        Binding("up", "move(-1)", "Up", show=False),
        Binding("enter", "select", "Open"),
        Binding("pagedown", "page(1)", "Next", key_display="pgdn", tooltip="Next page"),
        Binding("pageup", "page(-1)", "Prev", key_display="pgup", tooltip="Previous page"),
    ]

    class Selected(Message):
        def __init__(self, control: "CursorList", key: object, index: int) -> None:
            super().__init__()
            self._control = control
            self.key = key
            self.index = index

        @property
        def control(self) -> "CursorList":
            """The list that posted this — handlers on screens with several
            CursorLists must filter by source (backlog 6.2c)."""
            return self._control

    class Highlighted(Message):
        """Posted when the row cursor moves (live), carrying the new row's key.
        Lets a parent react as you navigate (e.g. a master→detail two-pane)."""

        def __init__(self, control: "CursorList", key: object, index: int) -> None:
            super().__init__()
            self._control = control
            self.key = key
            self.index = index

        @property
        def control(self) -> "CursorList":
            """The list that posted this — handlers on screens with several
            CursorLists must filter by source (backlog 6.2c)."""
            return self._control

    class PageRequested(Message):
        """Posted in fetched-page mode when a page key needs data beyond the
        fetched window; the screen refetches (see PagedListMixin)."""

        def __init__(self, control: "CursorList", delta: int) -> None:
            super().__init__()
            self._control = control
            self.delta = delta

        @property
        def control(self) -> "CursorList":
            """The list that posted this — handlers on screens with several
            CursorLists must filter by source (backlog 6.2c)."""
            return self._control

    def __init__(
        self,
        headers: Sequence[str],
        rows: Iterable[RowInput],
        *,
        align_right: Iterable[int] = (),
        empty: str = "(empty)",
        title: str | None = None,
        page_size: int = DEFAULT_PAGE_ROWS,
        page_meta: tuple[int, int] | None = None,
    ) -> None:
        super().__init__()
        self._headers = list(headers)
        self._rows: list[Row] = [Row.coerce(r) for r in rows]
        self._align = set(align_right)
        self._empty = empty
        self._page_size = page_size
        self._page_meta = page_meta
        self._cursor = 0
        if title is not None:
            self.border_title = title

    def on_mount(self) -> None:
        self._refresh()
        self.focus()

    def set_rows(self, rows: Iterable[RowInput]) -> None:
        self._rows = [Row.coerce(r) for r in rows]
        self._cursor = min(self._cursor, max(0, len(self._rows) - 1))
        self._refresh()

    @property
    def cursor_key(self) -> object | None:
        return self._rows[self._cursor].key if self._rows else None

    def index_of(self, key: object) -> int:
        for i, row in enumerate(self._rows):
            if row.key == key:
                return i
        return 0

    def set_cursor(self, index: int) -> None:
        if self._rows:
            self._cursor = max(0, min(len(self._rows) - 1, index))
            self._refresh()

    def set_page_size(self, page_size: int) -> None:
        """Adaptive rows (2026-07-13): the screen re-measures on terminal resize.
        Window mode re-slices around the cursor here; fetched-page screens
        refetch and rebuild the widget instead."""
        if page_size < 1 or page_size == self._page_size:
            return
        self._page_size = page_size
        self._refresh()

    @property
    def _window_start(self) -> int:
        return (self._cursor // self._page_size) * self._page_size

    @property
    def page_status(self) -> str | None:
        """The border-subtitle string, or None when everything fits one page."""
        if self._page_meta is not None:
            offset, total = self._page_meta
            return page_indicator(offset, len(self._rows), total, self._page_size)
        start = self._window_start
        shown = min(self._page_size, len(self._rows) - start)
        return page_indicator(start, shown, len(self._rows), self._page_size)

    def _refresh(self) -> None:
        self.border_subtitle = self.page_status or ""
        self.update(self._build())

    @staticmethod
    def _cell(value: object) -> object:
        # pass Rich renderables (e.g. a Text swatch) through; stringify the rest.
        return value if isinstance(value, (str, Text)) else str(value)

    def _build(self) -> RenderableType:
        if not self._rows:
            return Text("  " + self._empty, style="dim")
        t = Table(box=box.SIMPLE, expand=True, pad_edge=False)
        for i, header in enumerate(self._headers):
            t.add_column(header, justify="right" if i in self._align else "left", no_wrap=True)
        start = self._window_start
        for r, row in enumerate(self._rows[start : start + self._page_size], start=start):
            style = CURSOR_STYLE if r == self._cursor else row.base_style
            t.add_row(*[self._cell(c) for c in row.cells], style=style)
        return t

    def action_move(self, delta: int) -> None:
        if not self._rows:
            return
        new = max(0, min(len(self._rows) - 1, self._cursor + delta))
        if new != self._cursor:
            self._cursor = new
            self._refresh()
            self.post_message(self.Highlighted(self, self.cursor_key, self._cursor))

    def action_page(self, delta: int) -> None:
        if self._page_meta is not None:
            # fetched-page mode: the screen owns the data; ask it to turn.
            self.post_message(self.PageRequested(self, delta))
            return
        if not self._rows:
            return
        new = max(0, min(len(self._rows) - 1, self._cursor + delta * self._page_size))
        if new != self._cursor:
            self._cursor = new
            self._refresh()
            self.post_message(self.Highlighted(self, self.cursor_key, self._cursor))

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "page":  # hide the page keys when one page holds it all
            if self._page_meta is not None:
                return self._page_meta[1] > self._page_size
            return len(self._rows) > self._page_size
        return True

    def action_select(self) -> None:
        if self._rows:
            self.post_message(self.Selected(self, self._rows[self._cursor].key, self._cursor))


class CursorOptionList(OptionList):
    """An `OptionList` whose highlighted row is reverse video, like every other list.

    Textual draws `OptionList`'s highlight through CSS
    (`.option-list--option-highlighted`), and under this app's ANSI theme that
    path is a dead end: `block-cursor-foreground` and `block-cursor-background`
    are both `ansi_default`, so all the contrast has to come from
    `text-style: reverse` — and Textual 8.2.7 drops `reverse` when both colours
    are `ansi_default`. Measured, the highlighted row rendered
    `default on default`, byte-identical to its neighbours, so the home menu had
    no visible cursor at all (reported 2026-08-20). Overriding the rule in
    `app.tcss` does not help; the style is dropped there too.

    So the cursor is applied to the finished strip instead, which is the same
    place `CursorList` applies it — a Rich style, not a CSS one. Disabled
    options (the group headers) are skipped: they are never the cursor.

    `_lines` is Textual-internal, and deliberately so — it is the same mapping
    `OptionList.render_line` itself uses to turn a y offset into an option
    index, and there is no public equivalent. `test_tui_menu_cursor.py` asserts
    the highlighted row renders differently from its neighbours, so a Textual
    bump that moves this breaks a test rather than silently blinding the menu
    the way the original regression did.
    """

    def render_line(self, y: int) -> Strip:
        strip = super().render_line(y)
        try:
            option_index, _offset = self._lines[self.scroll_offset.y + y]
        except IndexError:
            return strip
        if option_index != self.highlighted or self.options[option_index].disabled:
            return strip
        return strip.apply_style(Style(reverse=True))
