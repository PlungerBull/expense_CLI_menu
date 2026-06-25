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
        self._load()

    def action_reload(self) -> None:
        content = self.query_one("#content", VerticalScroll)
        content.remove_children()
        content.mount(LoadingIndicator())
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
            self.app.call_from_thread(self._error, str(exc))
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

    def _set_loading(self, message: str) -> None:
        content = self.query_one("#content", VerticalScroll)
        content.remove_children()
        content.mount(
            Vertical(Static(message, classes="sync-note"), LoadingIndicator(), id="loadbox")
        )

    def _show(self, data: object) -> None:
        content = self.query_one("#content", VerticalScroll)
        content.remove_children()
        card = Vertical(*self.build(data), id="card")
        if self.CARD_WIDTH is not None:
            card.styles.max_width = self.CARD_WIDTH
        content.mount(card)

    def _error(self, message: str) -> None:
        content = self.query_one("#content", VerticalScroll)
        content.remove_children()
        banner = Group(Text("Could not load.", style="bold"), Text(message))
        content.mount(Static(banner, classes="error"))

    # ---- subclass hooks --------------------------------------------------
    def fetch(self) -> object:
        """Fetch data in a worker thread. Raise to surface an in-app error."""
        raise NotImplementedError

    def build(self, data: object) -> list[Widget]:
        """Return the widgets to mount inside the card (runs on the UI thread)."""
        raise NotImplementedError
