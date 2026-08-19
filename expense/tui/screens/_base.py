"""SectionScreen — the shared base for every data-backed section screen.

Owns the breadcrumb header, the bounded content card, the worker-backed fetch
(so the UI never blocks), and loading/error states. Subclasses supply only:

    crumb  : tuple[str, ...]          # breadcrumb trail after EXPENSE WORLD
    fetch()                           # runs in a worker thread, returns data
    build(data) -> list[Widget]       # the widgets to show inside the card

`r` refreshes; `escape` pops back to the menu.
"""

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from rich.console import Group
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer, LoadingIndicator, Static
from textual.worker import get_current_worker

from expense.commands._resource import DEFAULT_PAGE_ROWS
from expense.errors import format_error
from expense.tui.screens.help import HelpBindingMixin
from expense.tui.widgets.header import Breadcrumb


def screen_fetch_kwargs(app) -> dict:
    """The standard TUI read kwargs: verbosity off the app."""
    return dict(verbose=app._verbose)


@dataclass
class _QueuedWrite:
    method: str
    path: str
    json_body: dict | None
    success: str
    on_success: Callable[[], None] | None
    on_error: Callable[[str], None] | None


class EngineWriteMixin:
    """Engine writes off the UI thread — one at a time, in order, per screen.

    Shared by SectionScreen and the bar-cycle form screens (which subclass
    plain Screen). `run_write` appends to a per-screen FIFO and exactly one
    request is in flight at any moment: thread workers cancel cooperatively,
    so `exclusive=True` alone never serialized overlapping writes
    (backlog 6.4b). Success/error callbacks land on the UI thread; without
    callbacks, errors notify a "Failed" toast and success runs `_after_write`.
    Idempotency + error envelope come from the client. The `engine-write`
    worker group keeps loads/theme changes from ever cancelling a write.

    A failed write **drops the queued remainder** — those intents were decided
    against a screen state the engine just contradicted; the error callback
    typically resyncs.
    """

    _write_queue: deque[_QueuedWrite] | None = None  # lazily created; UI-thread only
    _write_inflight: bool = False

    def run_write(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        success: str = "Done.",
        on_success: Callable[[], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        if self._write_queue is None:
            self._write_queue = deque()
        self._write_queue.append(
            _QueuedWrite(method, path, json_body, success, on_success, on_error)
        )
        self._pump_writes()

    def _pump_writes(self) -> None:
        if self._write_inflight or not self._write_queue:
            return
        self._write_inflight = True
        self._execute_write(self._write_queue.popleft())

    @work(thread=True, group="engine-write")
    def _execute_write(self, item: _QueuedWrite) -> None:
        # Imports stay function-local: the test fixtures patch these module
        # attributes, and only a lazy lookup sees the patch.
        from expense import config as config_module
        from expense.http import ExpenseClient

        error: str | None = None
        try:
            cfg = config_module.ensure_loaded()
            with ExpenseClient(cfg, verbose=self.app._verbose) as client:
                if item.method == "POST":
                    client.post(item.path, json_body=item.json_body)
                elif item.method == "PUT":
                    client.put(item.path, json_body=item.json_body)
                elif item.method == "DELETE":
                    client.delete(item.path)
                else:
                    raise ValueError(f"unsupported write method: {item.method}")
        except Exception as exc:
            error = format_error(exc)
        self.app.call_from_thread(self._write_finished, item, error)

    def _write_finished(self, item: _QueuedWrite, error: str | None) -> None:
        # UI thread: report the outcome, then pump the next write.
        self._write_inflight = False
        if error is not None:
            if self._write_queue:
                self._write_queue.clear()
            if item.on_error is not None:
                item.on_error(error)
            else:
                self.notify(error, title="Failed", severity="error")
        else:
            if item.on_success is not None:
                item.on_success()
            else:
                self._after_write(item.success)
        if self._write_queue:
            self._pump_writes()

    def _after_write(self, message: str) -> None:
        self.notify(message)


class ContentSwapLockMixin:
    """Serializes every remove/mount pair on a screen's content container.

    Two repaints can land near-simultaneously (e.g. a manual refresh while a
    write's post-refresh reload is in flight); each swap suspends between
    remove and mount, and interleaved swaps would mount duplicate content
    (DuplicateIds on SectionScreen's '#card', stacked checklists on the
    reconciliation detail screen).
    """

    _swap_lock: asyncio.Lock | None = None

    def _content_lock(self) -> asyncio.Lock:
        if self._swap_lock is None:  # lazily created; only ever touched on the UI thread
            self._swap_lock = asyncio.Lock()
        return self._swap_lock


class PagedListMixin:
    """Fetch-side pagination for SectionScreens whose fetch sends limit/offset.

    The list widget renders one fetched page (`CursorList(page_meta=…)`) and
    posts `PageRequested` on the page keys; this mixin clamps against the last
    known total, bumps the page, and reloads through the normal section-load
    worker. The subclass contract: call `page_fetch_kwargs()` inside `fetch()`,
    record the body's `total` into `_page_total` (fetch- or build-side), pass
    `page_size=self.page_rows` to the CursorList, and call `reset_page()`
    whenever a filter change invalidates the offset.

    Rows-per-page adapt to the terminal (2026-07-13, pick A + cap 20): the
    page IS the screenful — `_start_load` measures before the first fetch and
    a terminal resize refetches with the new limit, re-anchoring the offset so
    the old first visible row stays on the new page.
    """

    _page: int = 0
    _page_total: int | None = None
    _page_rows: int | None = None  # measured rows-per-page; None until first layout

    @property
    def page_rows(self) -> int:
        return self._page_rows or DEFAULT_PAGE_ROWS

    @property
    def page_offset(self) -> int:
        return self.page_rows * self._page

    def page_fetch_kwargs(self) -> dict:
        return {"limit": self.page_rows, "offset": self.page_offset}

    def reset_page(self) -> None:
        self._page = 0

    def _start_load(self) -> None:
        self._page_rows = self.measure_list_rows()
        super()._start_load()

    def _viewport_resized(self) -> None:
        new = self.measure_list_rows()
        if new == self.page_rows:
            return
        first_row = self.page_offset  # keep the old first visible row on the new page
        self._page_rows = new
        self._page = first_row // new
        self._load()

    def page_meta(self) -> tuple[int, int] | None:
        """(offset, total) for the CursorList subtitle; None until a fetch
        recorded a real total (the widget then acts single-page)."""
        return (self.page_offset, self._page_total) if self._page_total is not None else None

    def fetch_page_body(self, fetch_page: Callable[[dict], Any]) -> Any:
        """Fetch the current page via `fetch_page(page_kwargs)` and record the
        body's total. If the page now points past the end (rows shrank since —
        e.g. a delete emptied the last page), snap to the last real page and
        refetch once."""
        body = fetch_page(self.page_fetch_kwargs())
        total = body.get("total") if isinstance(body, dict) else None
        self._page_total = total if isinstance(total, int) else None
        if self._page and self._page_total is not None and self.page_offset >= self._page_total:
            last = self._page_total - 1
            self._page = last // self.page_rows if last >= 0 else 0
            body = fetch_page(self.page_fetch_kwargs())
            total = body.get("total") if isinstance(body, dict) else None
            self._page_total = total if isinstance(total, int) else None
        return body

    def on_cursor_list_page_requested(self, event) -> None:
        event.stop()
        target = self._page + event.delta
        if target < 0:
            return
        total = self._page_total
        if total is not None and target * self.page_rows >= total:
            return  # no page there — the last page stays put
        self._page = target
        self._load()


class SectionScreen(HelpBindingMixin, EngineWriteMixin, ContentSwapLockMixin, Screen):
    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
        ("r", "reload", "Refresh"),
        *HelpBindingMixin.BINDINGS,
    ]
    crumb: tuple[str, ...] = ()
    CARD_WIDTH: int | None = 64  # cap the content card; None = fill width
    # Last fetched payload, cached so a theme swap re-renders from memory instead
    # of re-fetching. None = nothing loaded yet (an empty list/dict is still cached).
    _data: object = None
    _started: bool = False  # first load ran (it waits for the first layout pass)

    # ---- adaptive list sizing (2026-07-13, mockups/expense-world-adaptive-rows.html)
    LIST_FRAME_LINES = 4  # panel border 2 + column header + header rule
    PAGE_ROWS_FLOOR = 5  # below this the panel clips again (a <16-line terminal)

    def compose(self) -> ComposeResult:
        yield Breadcrumb(self.crumb, id="crumb")
        yield VerticalScroll(LoadingIndicator(), id="content")
        yield Footer()

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, self._on_theme_change)
        # First load waits for the first layout pass: adaptive page sizing
        # (measure_list_rows) reads #content's height, which is 0 at mount.
        self.call_after_refresh(self._start_load)

    def _start_load(self) -> None:
        if self._started:
            return
        self._started = True
        self._load()

    def on_resize(self, _event) -> None:
        # The initial layout fires Resize too; adaptive re-windowing only makes
        # sense once the first load measured this same geometry.
        if self._started:
            self._viewport_resized()

    def _viewport_resized(self) -> None:
        """Hook — adaptive-list screens re-window (window mode) or refetch with
        the new limit (fetched-page mode) when the terminal size changes."""

    def list_extra_lines(self) -> int:
        """Lines the screen renders around its list inside #content (legends…)."""
        return 0

    def measure_list_rows(self) -> int:
        """Rows-per-page = min(20, what fits #content), floor PAGE_ROWS_FLOOR —
        pick A + cap 20, 2026-07-13. Pre-layout / unmeasurable → the 20 default."""
        try:
            avail = self.query_one("#content", VerticalScroll).content_size.height
        except Exception:
            return DEFAULT_PAGE_ROWS
        if avail <= 0:
            return DEFAULT_PAGE_ROWS
        rows = avail - self.LIST_FRAME_LINES - self.list_extra_lines()
        return max(self.PAGE_ROWS_FLOOR, min(DEFAULT_PAGE_ROWS, rows))

    def _on_theme_change(self, _theme: object) -> None:
        # Rich content bakes resolved hexes at build time, so a live theme change
        # must rebuild the card — but from data already in memory, not a fresh
        # engine/cache fetch (backlog §5). Only load if nothing's cached yet.
        if self._data is not None:
            self.run_worker(self._show(self._data), exclusive=False, group="section-render")
        else:
            self._start_load()

    async def action_reload(self) -> None:
        async with self._content_lock():
            content = self.query_one("#content", VerticalScroll)
            await content.remove_children()
            await content.mount(LoadingIndicator())
        self._load()

    # Own group: loads may cancel stale loads, but never a run_write worker.
    @work(thread=True, exclusive=True, group="section-load")
    def _load(self) -> None:
        # Cancellation is cooperative: a newer exclusive load only flags this
        # worker, so check before painting or a superseded load can clobber
        # (or race) the fresh one's content swap.
        worker = get_current_worker()
        try:
            data = self.fetch()
        except Exception as exc:  # surface engine/config errors in-app, don't crash
            if not worker.is_cancelled:
                self.app.call_from_thread(self._error, format_error(exc))
            return
        if worker.is_cancelled:
            return
        self.app.call_from_thread(self._show, data)

    async def _show(self, data: object) -> None:
        self._data = data  # cache for theme re-render (see _on_theme_change)
        content = self.query_one("#content", VerticalScroll)
        async with self._content_lock():
            await content.remove_children()
            card = Vertical(*self.build(data), id="card")
            if self.CARD_WIDTH is not None:
                card.styles.max_width = self.CARD_WIDTH
            await content.mount(card)

    async def _error(self, message: str) -> None:
        content = self.query_one("#content", VerticalScroll)
        async with self._content_lock():
            await content.remove_children()
            banner = Group(Text("Could not load.", style="bold"), Text(message))
            await content.mount(Static(banner, classes="error"))

    # ---- shared write helpers (Phase 2) ----------------------------------
    def selected_record(self) -> dict | None:
        """The record under the list cursor (screens keep `_by_id`)."""
        from expense.tui.widgets.cursor_list import CursorList

        try:
            cursor_list = self.query_one(CursorList)
        except Exception:
            return None
        return getattr(self, "_by_id", {}).get(cursor_list.cursor_key)

    def _after_write(self, message: str) -> None:
        self.notify(message)
        self._load()  # re-fetch; content swaps are lock-serialized, no card clash

    def confirm_write(
        self, title: str, message: str, method: str, path: str, *, success: str = "Done."
    ) -> None:
        """Push a yes/no modal; on yes, run the write + refresh + reload."""
        from expense.tui.screens.modals import ConfirmModal

        def _cb(confirmed: bool | None) -> None:
            if confirmed:
                self.run_write(method, path, success=success)

        self.app.push_screen(ConfirmModal(title, message), _cb)

    # ---- subclass hooks --------------------------------------------------
    def fetch(self) -> object:
        """Fetch data in a worker thread. Raise to surface an in-app error."""
        raise NotImplementedError

    def build(self, data: object) -> list[Widget]:
        """Return the widgets to mount inside the card (runs on the UI thread)."""
        raise NotImplementedError


class ResourceListScreen(SectionScreen):
    """Scaffold for the simple manage lists (Accounts / Categories / Hashtags):
    quiet fetch → title + CursorList of rows (+ optional legend). `n` pushes
    the new-record form; `e` the prefilled edit form for the cursor row.
    `enter` is a no-op here. The `a` archive toggle lives on AccountsScreen
    only — the engine removed category/hashtag archive (2026-08-06 schema
    slimming); the no-confirm toggle decision (2026-07-11 in decisions.md)
    still governs it there.

    Subclasses set the class attrs and four hooks. Row builders stay pure
    module functions (they have direct unit tests).
    """

    TITLE: str = ""
    HEADERS: list[str] = []
    EMPTY: str = "(empty)"
    LEGEND: str | None = None
    ALIGN_RIGHT: set[int] = set()
    RESOURCE: str = ""  # engine collection, e.g. "accounts"
    BINDINGS = [
        ("n", "new", "New"),
        ("e", "edit", "Edit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._by_id: dict = {}
        self._restore_key: object | None = None  # cursor row to re-select after a reload
        self._toggle_busy = False  # one archive toggle at a time until the reload lands

    # ---- hooks ------------------------------------------------------------
    def fetch_items(self, cfg, **kw) -> object:
        """Call the shared fetch_* for this resource (worker thread)."""
        raise NotImplementedError

    def rows(self, items: list) -> list:
        """items → the pure row builder's (id, cells, style) rows."""
        raise NotImplementedError

    def edit_screen(self, item: dict):
        """The prefilled edit form for `e` on a row."""
        raise NotImplementedError

    def new_screen(self):
        """The create-form screen for `n`."""
        raise NotImplementedError

    # ---- binding availability ----------------------------------------------
    def check_action(self, action: str, parameters: tuple) -> bool | None:
        if action in ("edit", "archive") and self.selected_record() is None:
            return None  # empty list → nothing to act on
        return True

    def on_cursor_list_highlighted(self, event) -> None:
        self.refresh_bindings()  # re-check e/a for the row the cursor just landed on

    # ---- adaptive window (2026-07-13) --------------------------------------
    def list_extra_lines(self) -> int:
        return 2 if self.LEGEND else 0  # legend Static: margin-top 1 + one text line

    def _viewport_resized(self) -> None:
        from expense.tui.widgets.cursor_list import CursorList

        try:
            cursor_list = self.query_one(CursorList)
        except Exception:
            return  # not built yet (loading/error state)
        cursor_list.set_page_size(self.measure_list_rows())

    # ---- scaffold ----------------------------------------------------------
    def fetch(self) -> list:
        from expense import config as config_module
        from expense.commands._resource import items_of

        cfg = config_module.ensure_loaded()
        return items_of(self.fetch_items(cfg, **screen_fetch_kwargs(self.app)))

    def build(self, items: list) -> list[Widget]:
        from expense.tui.widgets.cursor_list import CursorList

        self._by_id = {it.get("id"): it for it in items}
        cursor_list = CursorList(
            self.HEADERS,
            self.rows(items),
            align_right=self.ALIGN_RIGHT,
            empty=self.EMPTY,
            title=self.TITLE,  # panel border title (L2, 2026-07-11) — no title row
            page_size=self.measure_list_rows(),  # adaptive window (2026-07-13)
        )
        # Re-select the acted-on row: _show mounts a fresh CursorList each load,
        # so without this an archive toggle would snap the cursor back to row 0
        # and "press `a` again to undo" would hit the wrong record.
        if self._restore_key is not None:
            cursor_list.set_cursor(cursor_list.index_of(self._restore_key))
            self._restore_key = None
        self._toggle_busy = False
        self.call_after_refresh(self.refresh_bindings)
        widgets: list[Widget] = [cursor_list]
        if self.LEGEND:
            widgets.append(Static(Text(self.LEGEND), classes="legend"))
        return widgets

    def action_new(self) -> None:
        self.app.push_screen(self.new_screen(), lambda _result: self._load())

    def action_edit(self) -> None:
        item = self.selected_record()
        if not item:
            return
        self._restore_key = item.get("id")
        self.app.push_screen(self.edit_screen(item), lambda _result: self._load())
