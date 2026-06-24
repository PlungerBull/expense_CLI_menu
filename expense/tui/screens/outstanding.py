"""Outstanding Amounts screen — current-month balances + spend.

Reads live data via the shared `dashboard_cmd.fetch_dashboard` (the fetch/print
split), off the UI thread in a worker so the screen never freezes. Rendering is
a pure `dashboard_renderables(body)` helper (Rich renderables) so it's unit-
testable without an event loop or a live engine.

Phase 0 renders the category → hashtag breakdown as a flat, fully-expanded
indented list; the interactive `▼/▶` tree lands in Phase 1.
"""

import io

from rich import box
from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, LoadingIndicator, Static

from expense.commands import dashboard_cmd
from expense.commands._resource import format_cents


def _accounts_table(items: list[dict]) -> RenderableType:
    if not items:
        return Text("  (none)", style="dim")
    t = Table(box=box.SIMPLE, pad_edge=False, expand=False)
    t.add_column("Name")
    t.add_column("Cur")
    t.add_column("Balance", justify="right")
    for item in items:
        t.add_row(
            item.get("name") or "(unnamed)",
            item.get("currency_code") or "?",
            format_cents(item.get("current_balance_cents")),
        )
    return t


def _categories_table(categories: list[dict]) -> RenderableType:
    if not categories:
        return Text("  (no categories)", style="dim")
    name_map = dashboard_cmd.load_hashtag_name_map()
    t = Table(box=box.SIMPLE, pad_edge=False, expand=False)
    t.add_column("Name")
    t.add_column("Spent", justify="right")
    for cat in categories:
        t.add_row(cat.get("name") or "(unnamed)", format_cents(cat.get("spent_cents")))
        for sub in cat.get("hashtag_breakdown") or []:
            ids = sub.get("hashtag_ids") or []
            t.add_row(
                "  " + dashboard_cmd.hashtag_label(ids, name_map),
                format_cents(sub.get("spent_cents")),
            )
    return t


def _totals_table(totals: dict | None) -> RenderableType:
    if not isinstance(totals, dict):
        return Text("  (no totals)", style="dim")
    t = Table(box=box.SIMPLE, pad_edge=False, expand=False)
    t.add_column("Totals")
    t.add_column("native", justify="right")
    t.add_column("home", justify="right")
    for key in ("inflow", "outflow", "net"):
        t.add_row(
            key,
            format_cents(totals.get(f"{key}_cents")),
            format_cents(totals.get(f"{key}_home_cents")),
        )
    return t


def dashboard_renderables(body: dict) -> list[tuple[str, RenderableType]]:
    """Pure data → (css-class, renderable) pairs. No widgets, no event loop."""
    month = dashboard_cmd._format_month(body.get("month"))
    out: list[tuple[str, RenderableType]] = [
        ("section-title", Text.from_markup(f"Outstanding Amounts  ·  {month}  (current month)")),
        ("sect", Text("Bank accounts")),
        ("", _accounts_table(body.get("bank_accounts") or [])),
    ]
    people = body.get("people") or []
    if people:
        out.append(("sect", Text("People")))
        out.append(("", _accounts_table(people)))
    out.append(("sect", Text("Categories — spent this month")))
    out.append(("", _categories_table(body.get("categories") or [])))
    out.append(("sect", Text("Totals")))
    out.append(("", _totals_table(body.get("totals"))))
    return out


class OutstandingScreen(Screen):
    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
        ("r", "refresh", "Refresh"),
    ]

    def compose(self) -> ComposeResult:
        yield Static("◈ EXPENSE WORLD   ▸ Reports ▸ Outstanding Amounts", id="crumb")
        yield VerticalScroll(LoadingIndicator(), id="content")
        yield Footer()

    def on_mount(self) -> None:
        self.load_dashboard()

    def action_refresh(self) -> None:
        content = self.query_one("#content", VerticalScroll)
        content.remove_children()
        content.mount(LoadingIndicator())
        self.load_dashboard()

    @work(thread=True, exclusive=True)
    def load_dashboard(self) -> None:
        from expense import config as config_module

        try:
            cfg = config_module.ensure_loaded()
            body = dashboard_cmd.fetch_dashboard(
                cfg,
                verbose=self.app._verbose,
                no_cache=self.app._no_cache,
                cold_start_notice=False,
                notice_stream=io.StringIO(),
            )
        except Exception as exc:  # surface engine/config errors in-app, don't crash
            self.app.call_from_thread(self._show_error, str(exc))
            return
        self.app.call_from_thread(self._populate, body)

    def _show_error(self, message: str) -> None:
        content = self.query_one("#content", VerticalScroll)
        content.remove_children()
        banner = Group(Text("Could not load dashboard.", style="bold"), Text(message))
        content.mount(Static(banner, classes="error"))

    def _populate(self, body: dict) -> None:
        content = self.query_one("#content", VerticalScroll)
        content.remove_children()
        content.mount(
            *(
                Static(renderable, classes=css or None)
                for css, renderable in dashboard_renderables(body)
            )
        )
