"""Outstanding Amounts screen — current-month balances + spend.

Reads live data via the shared `dashboard_cmd.fetch_dashboard` (the fetch/print
split), off the UI thread in a worker so the screen never freezes.

Accounts / people / totals are static Rich tables. The category → hashtag
breakdown is an interactive `CategoriesView`: arrow-key navigation with `▼/▶`
expand/collapse per category. Render helpers and `CategoriesView._build` are
pure (no event loop), so formatting + collapse are unit-testable directly.
"""

import io

from rich import box
from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, LoadingIndicator, Static

from expense.commands import dashboard_cmd
from expense.commands._resource import format_cents


def _accounts_table(items: list[dict]) -> RenderableType:
    if not items:
        return Text("  (none)", style="dim")
    t = Table(box=box.SIMPLE, pad_edge=False, expand=True)
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


def _totals_table(totals: dict | None) -> RenderableType:
    if not isinstance(totals, dict):
        return Text("  (no totals)", style="dim")
    t = Table(box=box.SIMPLE, pad_edge=False, expand=True)
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


class CategoriesView(Static):
    """Interactive category tree: `↑↓` move, `→/←` expand/collapse, `enter` toggle.

    The cursor moves over categories; a category with a hashtag breakdown shows a
    `▼/▶` caret and reveals its (indented, dimmed) sub-rows when expanded.
    """

    can_focus = True
    BINDINGS = [
        Binding("down,j", "move(1)", "Navigate"),
        Binding("up,k", "move(-1)", show=False),
        Binding("right,l", "expand", "Expand"),
        Binding("left,h", "collapse", "Collapse"),
        Binding("enter,space", "toggle", show=False),
    ]

    def __init__(self, categories: list[dict], name_map: dict[str, str]) -> None:
        super().__init__()
        self._cats = categories
        self._name_map = name_map
        self._collapsed: set[int] = set()
        self._cursor = 0

    def on_mount(self) -> None:
        self._render_tree()
        self.focus()

    @staticmethod
    def _has_kids(cat: dict) -> bool:
        return bool(cat.get("hashtag_breakdown"))

    def _render_tree(self) -> None:
        self.update(self._build())

    def _build(self) -> RenderableType:
        if not self._cats:
            return Text("  (no categories)", style="dim")
        t = Table(box=None, expand=True, pad_edge=False, show_header=False)
        t.add_column("name", ratio=1, no_wrap=True)
        t.add_column("amt", justify="right", no_wrap=True)
        for i, cat in enumerate(self._cats):
            kids = self._has_kids(cat)
            caret = ("▶ " if i in self._collapsed else "▼ ") if kids else "  "
            row_style = "reverse" if i == self._cursor else ""
            t.add_row(
                caret + (cat.get("name") or "(unnamed)"),
                format_cents(cat.get("spent_cents")),
                style=row_style,
            )
            if kids and i not in self._collapsed:
                for sub in cat["hashtag_breakdown"]:
                    ids = sub.get("hashtag_ids") or []
                    t.add_row(
                        "    " + dashboard_cmd.hashtag_label(ids, self._name_map),
                        format_cents(sub.get("spent_cents")),
                        style="dim",
                    )
        return t

    def action_move(self, delta: int) -> None:
        if not self._cats:
            return
        self._cursor = max(0, min(len(self._cats) - 1, self._cursor + delta))
        self._render_tree()

    def action_expand(self) -> None:
        self._collapsed.discard(self._cursor)
        self._render_tree()

    def action_collapse(self) -> None:
        self._collapsed.add(self._cursor)
        self._render_tree()

    def action_toggle(self) -> None:
        self._collapsed.symmetric_difference_update({self._cursor})
        self._render_tree()


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
        month = dashboard_cmd._format_month(body.get("month"))
        title = Text(f"Outstanding Amounts  ·  {month}  (current month)")
        widgets: list[Static] = [
            Static(title, classes="section-title"),
            Static(Text("Bank accounts"), classes="sect"),
            Static(_accounts_table(body.get("bank_accounts") or [])),
        ]
        people = body.get("people") or []
        if people:
            widgets.append(Static(Text("People"), classes="sect"))
            widgets.append(Static(_accounts_table(people)))
        widgets.append(Static(Text("Categories — spent this month"), classes="sect"))
        widgets.append(
            CategoriesView(body.get("categories") or [], dashboard_cmd.load_hashtag_name_map())
        )
        widgets.append(Static(Text("Totals"), classes="sect"))
        widgets.append(Static(_totals_table(body.get("totals"))))
        # Bound everything to a card so amounts form a tidy right-aligned column
        # instead of flying to the far edge of a wide terminal.
        content.mount(Vertical(*widgets, id="card"))
