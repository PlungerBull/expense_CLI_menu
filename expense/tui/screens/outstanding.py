"""Outstanding Amounts screen — current-month balances + spend.

Reads live data via the shared `dashboard_cmd.fetch_dashboard` (the fetch/print
split), off the UI thread in a worker so the screen never freezes.

Accounts / people / totals are static Rich tables. The category → hashtag
breakdown is an interactive `CategoriesView`: arrow-key navigation with `▼/▶`
expand/collapse per category. Render helpers and `CategoriesView._build` are
pure (no event loop), so formatting + collapse are unit-testable directly.
"""

from rich import box
from rich.console import RenderableType
from rich.table import Table
from rich.text import Text
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import Static

from expense.commands import dashboard_cmd
from expense.commands._resource import format_month
from expense.tui.screens._base import SectionScreen, screen_fetch_kwargs
from expense.tui.theme import AMOUNT_RULE, Palette, resolve_palette
from expense.tui.widgets.cells import amount_cell


def _accounts_table(items: list[dict], palette: Palette | None = None) -> RenderableType:
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
            amount_cell(item.get("current_balance_cents"), palette, AMOUNT_RULE),
        )
    return t


def _totals_table(totals: dict | None, palette: Palette | None = None) -> RenderableType:
    if not isinstance(totals, dict):
        return Text("  (no totals)", style="dim")
    t = Table(box=box.SIMPLE, pad_edge=False, expand=True)
    t.add_column("Totals")
    t.add_column("native", justify="right")
    t.add_column("home", justify="right")
    for key in ("inflow", "outflow", "net"):
        t.add_row(
            key,
            amount_cell(totals.get(f"{key}_cents"), palette, AMOUNT_RULE),
            amount_cell(totals.get(f"{key}_home_cents"), palette, AMOUNT_RULE),
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

    def __init__(
        self,
        categories: list[dict],
        name_map: dict[str, str],
        palette: Palette | None = None,
    ) -> None:
        super().__init__()
        self._cats = categories
        self._name_map = name_map
        self._palette = palette
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
                amount_cell(cat.get("spent_cents"), self._palette, AMOUNT_RULE),
                style=row_style,
            )
            if kids and i not in self._collapsed:
                for sub in cat["hashtag_breakdown"]:
                    ids = sub.get("hashtag_ids") or []
                    t.add_row(
                        "    " + dashboard_cmd.hashtag_label(ids, self._name_map),
                        amount_cell(sub.get("spent_cents"), self._palette, AMOUNT_RULE),
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


class OutstandingScreen(SectionScreen):
    """Current-month balances + spend. Only supplies the breadcrumb, the fetch,
    and the widgets; SectionScreen owns the worker/card/loading/error/refresh."""

    crumb = ("Reports", "Outstanding Amounts")

    def fetch(self) -> dict:
        from expense import config as config_module

        cfg = config_module.ensure_loaded()
        body = dashboard_cmd.fetch_dashboard(cfg, **screen_fetch_kwargs(self.app))
        # name map resolved worker-side — a full-table SQLite read on the
        # render path blocked first paint (backlog 6.5c)
        return {"body": body, "tag_names": dashboard_cmd.load_hashtag_name_map()}

    def build(self, data: dict) -> list[Widget]:
        body = data["body"]
        palette = resolve_palette(self.app)
        month = format_month(body.get("month"))
        title = Text(f"Outstanding Amounts  ·  {month}  (current month)")
        widgets: list[Widget] = [
            Static(title, classes="section-title"),
            Static(Text("Bank accounts"), classes="sect"),
            Static(_accounts_table(body.get("bank_accounts") or [], palette)),
        ]
        people = body.get("people") or []
        if people:
            widgets.append(Static(Text("People"), classes="sect"))
            widgets.append(Static(_accounts_table(people, palette)))
        widgets.append(Static(Text("Categories — spent this month"), classes="sect"))
        widgets.append(
            CategoriesView(body.get("categories") or [], data["tag_names"], palette=palette)
        )
        widgets.append(Static(Text("Totals"), classes="sect"))
        widgets.append(Static(_totals_table(body.get("totals"), palette)))
        return widgets
