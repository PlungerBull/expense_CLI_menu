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
from expense.tui.widgets.header import Breadcrumb


def screen_fetch_kwargs(app) -> dict:
    """The standard TUI read kwargs: replica mode + verbosity off the app,
    cold-start notice silenced (screens render their own sync note).

    Returns a fresh dict with a fresh StringIO each call — a shared stream
    would interleave notices across concurrent fetches.
    """
    import io

    return dict(
        no_cache=app._no_cache,
        verbose=app._verbose,
        cold_start_notice=False,
        notice_stream=io.StringIO(),
    )


@dataclass
class _QueuedWrite:
    method: str
    path: str
    json_body: dict | None
    success: str
    on_success: Callable[[], None] | None
    on_error: Callable[[str], None] | None
    refresh: bool


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
    typically resyncs. Writes queued with `refresh=False` coalesce their
    replica refresh into a single delta sync when the queue drains
    (backlog 6.5a) — after an error drain too, since earlier skipped-refresh
    successes already changed engine state.
    """

    _write_queue: deque[_QueuedWrite] | None = None  # lazily created; UI-thread only
    _write_inflight: bool = False
    _refresh_on_drain: bool = False

    def run_write(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        success: str = "Done.",
        on_success: Callable[[], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        refresh: bool = True,
    ) -> None:
        if self._write_queue is None:
            self._write_queue = deque()
        self._write_queue.append(
            _QueuedWrite(method, path, json_body, success, on_success, on_error, refresh)
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
        import io

        from expense import config as config_module
        from expense.cache import refresh_after_write
        from expense.http import ExpenseClient

        error: str | None = None
        stale = False
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
                if item.refresh:
                    # Capture (don't discard) the refresh notice: content in the
                    # stream means the post-write sync failed and the on-screen
                    # replica is now stale — surface it, don't swallow (backlog §5).
                    notice = io.StringIO()
                    refresh_after_write(
                        client,
                        cfg,
                        no_cache=self.app._no_cache,
                        no_sync_after=False,
                        notice_stream=notice,
                    )
                    stale = bool(notice.getvalue().strip())
        except Exception as exc:
            error = format_error(exc)
        self.app.call_from_thread(self._write_finished, item, error, stale)

    def _write_finished(self, item: _QueuedWrite, error: str | None, stale: bool = False) -> None:
        # UI thread: report the outcome, then pump the next write or, on a
        # drained queue, run the coalesced refresh.
        self._write_inflight = False
        if error is not None:
            if self._write_queue:
                self._write_queue.clear()
            if item.on_error is not None:
                item.on_error(error)
            else:
                self.notify(error, title="Failed", severity="error")
        else:
            if not item.refresh:
                self._refresh_on_drain = True
            if item.on_success is not None:
                item.on_success()
            else:
                self._after_write(item.success)
            if stale:
                self._notify_stale_replica()
        if self._write_queue:
            self._pump_writes()
        elif self._refresh_on_drain:
            self._refresh_on_drain = False
            self._drain_refresh()

    def _notify_stale_replica(self) -> None:
        """Warn that the write landed but the local copy didn't refresh (backlog §5)."""
        self.notify(
            "The change was written, but the local copy didn't refresh and may "
            "be stale. Open Sync to refresh.",
            title="Saved — cache not refreshed",
            severity="warning",
        )

    @work(thread=True, group="engine-write")
    def _drain_refresh(self) -> None:
        import io

        from expense import config as config_module
        from expense.cache import refresh_after_write
        from expense.http import ExpenseClient

        stale = False
        try:
            cfg = config_module.ensure_loaded()
            with ExpenseClient(cfg, verbose=self.app._verbose) as client:
                notice = io.StringIO()
                refresh_after_write(
                    client,
                    cfg,
                    no_cache=self.app._no_cache,
                    no_sync_after=False,
                    notice_stream=notice,
                )
                stale = bool(notice.getvalue().strip())
        except Exception:
            # config/client setup failed before the refresh ran — the replica
            # may be stale. (A stale replica also self-heals on the next read's
            # sync, but the user should know now.)
            stale = True
        if stale:
            self.app.call_from_thread(self._notify_stale_replica)

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
    record the body's `total` into `_page_total` (fetch- or build-side), and
    call `reset_page()` whenever a filter change invalidates the offset.
    """

    _page: int = 0
    _page_total: int | None = None

    @property
    def page_offset(self) -> int:
        return DEFAULT_PAGE_ROWS * self._page

    def page_fetch_kwargs(self) -> dict:
        return {"limit": DEFAULT_PAGE_ROWS, "offset": self.page_offset}

    def reset_page(self) -> None:
        self._page = 0

    def on_cursor_list_page_requested(self, event) -> None:
        event.stop()
        target = self._page + event.delta
        if target < 0:
            return
        total = self._page_total
        if total is not None and target * DEFAULT_PAGE_ROWS >= total:
            return  # no page there — the last page stays put
        self._page = target
        self._load()


class SectionScreen(EngineWriteMixin, ContentSwapLockMixin, Screen):
    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
        ("r", "reload", "Refresh"),
    ]
    crumb: tuple[str, ...] = ()
    CARD_WIDTH: int | None = 64  # cap the content card; None = fill width
    # Last fetched payload, cached so a theme swap re-renders from memory instead
    # of re-fetching. None = nothing loaded yet (an empty list/dict is still cached).
    _data: object = None

    def compose(self) -> ComposeResult:
        yield Breadcrumb(self.crumb, id="crumb")
        yield VerticalScroll(LoadingIndicator(), id="content")
        yield Footer()

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, self._on_theme_change)
        self._load()

    def _on_theme_change(self, _theme: object) -> None:
        # Rich content bakes resolved hexes at build time, so a live theme change
        # must rebuild the card — but from data already in memory, not a fresh
        # engine/cache fetch (backlog §5). Only load if nothing's cached yet.
        if self._data is not None:
            self.run_worker(self._show(self._data), exclusive=False, group="section-render")
        else:
            self._load()

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
        if self._will_cold_start():
            self.app.call_from_thread(
                self._set_loading,
                "Syncing your data — first run, this can take a moment…",
            )
        try:
            data = self.fetch()
        except Exception as exc:  # surface engine/config errors in-app, don't crash
            if not worker.is_cancelled:
                self.app.call_from_thread(self._error, format_error(exc))
            return
        if worker.is_cancelled:
            return
        self.app.call_from_thread(self._show, data)

    def _will_cold_start(self) -> bool:
        """Cheap check: will the upcoming fetch trigger a full first-run sync?

        Lets the screen swap the bare spinner for a "Syncing…" note so a slow
        cold-start doesn't look like a hang. Best-effort; False on any doubt.
        """
        if getattr(self.app, "_no_cache", False):
            return False
        try:
            from expense import config as config_module
            from expense.cache import db, state

            config_module.ensure_loaded()
            conn = db.connect()
            try:
                cur = state.read(conn)
            finally:
                conn.close()
            return cur.user_id is None or cur.sync_token is None
        except Exception:
            return False

    async def _set_loading(self, message: str) -> None:
        content = self.query_one("#content", VerticalScroll)
        async with self._content_lock():
            await content.remove_children()
            await content.mount(
                Vertical(Static(message, classes="sync-note"), LoadingIndicator(), id="loadbox")
            )

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
    the new-record form; `e` the prefilled edit form for the cursor row; `a`
    archives/unarchives the cursor row immediately — no confirm, a second `a`
    undoes (decision 2026-07-11 in decisions.md). `enter` is a no-op here.

    Subclasses set the class attrs and four hooks. Row builders stay pure
    module functions (they have direct unit tests).
    """

    TITLE: str = ""
    HEADERS: list[str] = []
    EMPTY: str = "(empty)"
    LEGEND: str | None = None
    ALIGN_RIGHT: set[int] = set()
    RESOURCE: str = ""  # engine collection for the archive toggle, e.g. "accounts"
    BINDINGS = [
        ("n", "new", "New"),
        ("e", "edit", "Edit"),
        ("a", "archive", "Archive"),
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
        if action == "archive" and (self.selected_record() or {}).get("is_system"):
            return None  # system categories: archive deterministically 403s — hide, don't offer
        return True

    def on_cursor_list_highlighted(self, event) -> None:
        self.refresh_bindings()  # re-check e/a for the row the cursor just landed on

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

    def action_archive(self) -> None:
        if self._toggle_busy:
            return
        item = self.selected_record()
        if not item or item.get("is_system"):
            return
        verb, msg = (
            ("unarchive", "Unarchived.") if item.get("is_archived") else ("archive", "Archived.")
        )
        self._toggle_busy = True
        self._restore_key = item.get("id")
        self.run_write(
            "POST",
            f"/{self.RESOURCE}/{item['id']}/{verb}",
            success=msg,
            on_error=self._toggle_failed,
        )

    def _toggle_failed(self, message: str) -> None:
        self._toggle_busy = False
        self.notify(message, title="Failed", severity="error")
