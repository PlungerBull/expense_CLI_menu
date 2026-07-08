"""SectionScreen — the shared base for every data-backed section screen.

Owns the breadcrumb header, the bounded content card, the worker-backed fetch
(so the UI never blocks), and loading/error states. Subclasses supply only:

    crumb  : tuple[str, ...]          # breadcrumb trail after EXPENSE WORLD
    fetch()                           # runs in a worker thread, returns data
    build(data) -> list[Widget]       # the widgets to show inside the card

`r` refreshes; `escape` pops back to the menu.
"""

import asyncio
from collections.abc import Callable

from rich.console import Group
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer, LoadingIndicator, Static
from textual.worker import get_current_worker

from expense.errors import format_error
from expense.tui.widgets.header import Breadcrumb


class EngineWriteMixin:
    """One engine write off the UI thread: config → client → verb → replica refresh.

    Shared by SectionScreen and the bar-cycle form screens (which subclass plain
    Screen). Success/error callbacks land back on the UI thread via
    `call_from_thread`; without callbacks, errors notify with a "Failed" toast
    and success runs `_after_write`. Idempotency + error envelope come from the
    client. Writes run in their own `engine-write` group so a load/refresh or
    theme change can never cancel an in-flight write worker (or vice versa);
    `exclusive=True` within the group still guards against stale queued writes —
    an in-flight request always completes (thread workers cancel cooperatively).
    """

    @work(thread=True, exclusive=True, group="engine-write")
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
        # Imports stay function-local: the test fixtures patch these module
        # attributes, and only a lazy lookup sees the patch.
        import io

        from expense import config as config_module
        from expense.cache import refresh_after_write
        from expense.http import ExpenseClient

        cfg = config_module.ensure_loaded()
        try:
            with ExpenseClient(cfg, verbose=self.app._verbose) as client:
                if method == "POST":
                    client.post(path, json_body=json_body)
                elif method == "PUT":
                    client.put(path, json_body=json_body)
                elif method == "DELETE":
                    client.delete(path)
                else:
                    raise ValueError(f"unsupported write method: {method}")
                refresh_after_write(
                    client,
                    cfg,
                    no_cache=self.app._no_cache,
                    no_sync_after=False,
                    notice_stream=io.StringIO(),
                )
        except Exception as exc:
            message = format_error(exc)
            if on_error is not None:
                self.app.call_from_thread(on_error, message)
            else:
                self.app.call_from_thread(self.notify, message, title="Failed", severity="error")
            return
        if on_success is not None:
            self.app.call_from_thread(on_success)
        else:
            self.app.call_from_thread(self._after_write, success)

    def _after_write(self, message: str) -> None:
        self.notify(message)


class SectionScreen(EngineWriteMixin, Screen):
    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
        ("r", "reload", "Refresh"),
    ]
    crumb: tuple[str, ...] = ()
    CARD_WIDTH: int | None = 64  # cap the content card; None = fill width

    # Serializes every remove/mount pair on #content. Two loads can land
    # near-simultaneously (e.g. a manual refresh while a write's post-refresh
    # reload is in flight); each swap suspends between remove and mount, and
    # interleaved swaps would mount a second '#card' (DuplicateIds).
    _swap_lock: asyncio.Lock | None = None

    def _content_lock(self) -> asyncio.Lock:
        if self._swap_lock is None:  # lazily created; only ever touched on the UI thread
            self._swap_lock = asyncio.Lock()
        return self._swap_lock

    def compose(self) -> ComposeResult:
        yield Breadcrumb(self.crumb, id="crumb")
        yield VerticalScroll(LoadingIndicator(), id="content")
        yield Footer()

    def on_mount(self) -> None:
        # re-render on theme swap: Rich content bakes resolved hexes at build
        # time, so a live theme change must rebuild (exclusive worker → cheap)
        self.app.theme_changed_signal.subscribe(self, lambda _theme: self._load())
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
