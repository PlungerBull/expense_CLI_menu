"""SectionScreen — the shared base for every data-backed section screen.

Owns the breadcrumb header, the bounded content card, the worker-backed fetch
(so the UI never blocks), and loading/error states. Subclasses supply only:

    crumb  : tuple[str, ...]          # breadcrumb trail after EXPENSE WORLD
    fetch()                           # runs in a worker thread, returns data
    build(data) -> list[Widget]       # the widgets to show inside the card

`r` refreshes; `escape` pops back to the menu.
"""

from rich.console import Group
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer, LoadingIndicator, Static

from expense.errors import format_error
from expense.tui.widgets.header import Breadcrumb


class SectionScreen(Screen):
    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
        ("r", "reload", "Refresh"),
    ]
    crumb: tuple[str, ...] = ()
    CARD_WIDTH: int | None = 64  # cap the content card; None = fill width

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
        content = self.query_one("#content", VerticalScroll)
        await content.remove_children()
        await content.mount(LoadingIndicator())
        self._load()

    @work(thread=True, exclusive=True)
    def _load(self) -> None:
        if self._will_cold_start():
            self.app.call_from_thread(
                self._set_loading,
                "Syncing your data — first run, this can take a moment…",
            )
        try:
            data = self.fetch()
        except Exception as exc:  # surface engine/config errors in-app, don't crash
            self.app.call_from_thread(self._error, format_error(exc))
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
        await content.remove_children()
        await content.mount(
            Vertical(Static(message, classes="sync-note"), LoadingIndicator(), id="loadbox")
        )

    async def _show(self, data: object) -> None:
        content = self.query_one("#content", VerticalScroll)
        await content.remove_children()
        card = Vertical(*self.build(data), id="card")
        if self.CARD_WIDTH is not None:
            card.styles.max_width = self.CARD_WIDTH
        await content.mount(card)

    async def _error(self, message: str) -> None:
        content = self.query_one("#content", VerticalScroll)
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

    @work(thread=True)
    def run_write(self, method: str, path: str, *, success: str = "Done.") -> None:
        """POST/DELETE an engine endpoint off the UI thread, refresh the replica,
        then reload the screen. Idempotency + error envelope come from the client.
        """
        import io

        from expense import config as config_module
        from expense.cache import refresh_after_write
        from expense.http import ExpenseClient

        cfg = config_module.ensure_loaded()
        try:
            with ExpenseClient(cfg, verbose=self.app._verbose) as client:
                if method == "POST":
                    client.post(path)
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
            self.app.call_from_thread(
                self.notify, format_error(exc), title="Failed", severity="error"
            )
            return
        self.app.call_from_thread(self._after_write, success)

    def _after_write(self, message: str) -> None:
        self.notify(message)
        self._load()  # re-fetch; _show awaits the swap so there's no card clash

    def confirm_write(
        self, title: str, message: str, method: str, path: str, *, success: str = "Done."
    ) -> None:
        """Push a yes/no modal; on yes, run the write + refresh + reload."""
        from expense.tui.screens.modals import ConfirmModal

        def _cb(confirmed: bool | None) -> None:
            if confirmed:
                self.run_write(method, path, success=success)

        self.app.push_screen(ConfirmModal(title, message), _cb)

    def archive_selected(self, resource: str, label: str) -> None:
        """Archive (confirmed) or unarchive (direct) the cursor record.

        Only the hiding direction confirms — restoring visibility is harmless
        and self-reversing, and the flat CLI is already prompt-free there
        (backlog 1.2; aligned by 4.7).
        """
        item = self.selected_record()
        if not item:
            return
        if item.get("is_archived"):
            self.run_write("POST", f"/{resource}/{item['id']}/unarchive", success="Unarchived.")
            return
        name = item.get("name") or item.get("title") or "—"
        self.confirm_write(
            f"Archive {label}?",
            f"Archive “{name}”.",
            "POST",
            f"/{resource}/{item['id']}/archive",
            success="Archived.",
        )

    # ---- subclass hooks --------------------------------------------------
    def fetch(self) -> object:
        """Fetch data in a worker thread. Raise to surface an in-app error."""
        raise NotImplementedError

    def build(self, data: object) -> list[Widget]:
        """Return the widgets to mount inside the card (runs on the UI thread)."""
        raise NotImplementedError
