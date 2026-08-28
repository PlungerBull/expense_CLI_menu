"""Outstanding Amounts screen — current-month balances + spend.

Reads live data via the shared `dashboard_cmd.fetch_dashboard` (the fetch/print
split), off the UI thread in a worker so the screen never freezes.

Accounts and totals are static Rich tables. Two panels are interactive, sharing
one `▼/▶` collapse idiom: `CategoriesView` (the category → hashtag breakdown,
arrow-key navigation with expand/collapse per category) and `PeopleView` (people,
with settled ones folded behind a `▶ 3 settled` row). Render helpers and both
`_build`s are pure (no event loop), so formatting + collapse are unit-testable
directly.
"""

from rich import box
from rich.console import RenderableType
from rich.table import Table
from rich.text import Text
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import Static

from expense.commands import dashboard_cmd
from expense.commands._resource import (
    format_aggregate,
    format_month,
    has_aggregate,
    settled_label,
    split_settled,
    unconverted_of,
)
from expense.tui.screens._base import SectionScreen, screen_fetch_kwargs
from expense.tui.theme import AMOUNT_RULE, PALETTE, Palette
from expense.tui.widgets.cells import aggregate_cell, amount_cell


def _cat_is_shown(cat: dict) -> bool:
    """Whether a category earns a row: it spent something, or could not be priced.

    A category with nothing spent this month is not drawn (user decision,
    2026-08-16) — the engine returns every non-deleted category whether or not
    it has activity, and this screen is a report, not a category list.
    """
    return has_aggregate(cat.get("spent_home_cents"), unconverted_of(cat))


def _shown_breakdown(cat: dict) -> list[dict]:
    """A category's hashtag combos, minus the ones with nothing spent."""
    return [
        sub
        for sub in cat.get("hashtag_breakdown") or []
        if has_aggregate(sub.get("spent_home_cents"), unconverted_of(sub))
    ]


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
    """The inflow / outflow / net block, home currency only.

    The `native` column is gone with the engine keys behind it (2026-08-05) — a
    sum across accounts in different currencies is a number in no currency. The
    survivor is called `Home`, matching the CLI's tables.

    All three figures share one `unconverted_count`, so they fail together: an
    unpriceable month collapses the block to a single `3 unrated` line rather
    than repeating the count three times.
    """
    if not isinstance(totals, dict):
        return Text("  (no totals)", style="dim")
    unconverted = unconverted_of(totals)
    if unconverted > 0:
        text = Text(f"  {format_aggregate(None, unconverted)} — no totals this month")
        if palette is not None:
            text.stylize(palette.warning)
        return text
    t = Table(box=box.SIMPLE, pad_edge=False, expand=True)
    t.add_column("Totals")
    t.add_column("Home", justify="right")
    for key in ("inflow", "outflow", "net"):
        t.add_row(
            key,
            aggregate_cell(totals.get(f"{key}_home_cents"), unconverted, palette, AMOUNT_RULE),
        )
    return t


class PeopleView(Static):
    """People, with settled ones folded behind `▶ 3 settled`.

    Same three columns as the bank-accounts table above it, so the two panels
    read as one; the fold is the `CategoriesView` fold — same carets, same keys
    (`→/←`, `enter`) — so there is only one collapse idiom on this screen
    (sketch pick J, 2026-08-16).

    A settled person is **folded, never dropped**: the engine returns her on
    purpose and refuses to filter on a computed balance, because "she paid me
    back" and "I never recorded the loan" must not look alike. The count row is
    always drawn, and one keypress shows exactly who.

    With nobody settled there is nothing to fold, so the widget drops out of the
    focus chain and behaves as the plain table it used to be. `_build` is pure —
    collapse is unit-testable without an event loop.
    """

    BINDINGS = [
        Binding("right", "expand", "Expand"),
        Binding("left", "collapse", "Collapse"),
        Binding("enter,space", "toggle", "Expand or collapse", show=False),
    ]

    def __init__(self, people: list[dict], palette: Palette | None = None) -> None:
        super().__init__()
        self._outstanding, self._settled = split_settled(people)
        self._palette = palette
        self._collapsed = True  # settled people start folded away
        # Only foldable when there is something to fold; otherwise stay out of
        # the way of the Categories tree in the tab order.
        self.can_focus = bool(self._settled)

    def on_mount(self) -> None:
        self._render_tree()

    def on_focus(self) -> None:
        self._render_tree()

    def on_blur(self) -> None:
        self._render_tree()

    def _render_tree(self) -> None:
        self.update(self._build())

    def _row(self, table: Table, person: dict, *, indent: str = "", style: str = "") -> None:
        table.add_row(
            indent + (person.get("name") or "(unnamed)"),
            person.get("currency_code") or "?",
            amount_cell(person.get("current_balance_cents"), self._palette, AMOUNT_RULE),
            style=style,
        )

    def _build(self) -> RenderableType:
        if not self._outstanding and not self._settled:
            return Text("  (none)", style="dim")
        t = Table(box=box.SIMPLE, pad_edge=False, expand=True)
        t.add_column("Name")
        t.add_column("Cur")
        t.add_column("Balance", justify="right")
        for person in self._outstanding:
            self._row(t, person)
        if self._settled:
            caret = "▶ " if self._collapsed else "▼ "
            label = settled_label(len(self._settled)).removeprefix("▸ ")
            t.add_row(caret + label, "", "", style="reverse" if self.has_focus else "dim")
            if not self._collapsed:
                for person in self._settled:
                    self._row(t, person, indent="   ", style="dim")
        return t

    def action_expand(self) -> None:
        self._collapsed = False
        self._render_tree()

    def action_collapse(self) -> None:
        self._collapsed = True
        self._render_tree()

    def action_toggle(self) -> None:
        self._collapsed = not self._collapsed
        self._render_tree()


class CategoriesView(Static):
    """Interactive category tree: `↑↓` move, `→/←` expand/collapse, `enter` toggle.

    The cursor moves over categories; a category with a hashtag breakdown shows a
    `▼/▶` caret and reveals its (indented, dimmed) sub-rows when expanded.
    """

    can_focus = True
    BINDINGS = [
        # Not shown in the footer: "the arrow keys move the cursor" is not worth a
        # footer slot (user, 2026-08-20 — "its obvious and it just occupies space
        # unnecessarily"). The keys are unchanged and the `?` card still lists them,
        # which is where a key that needs explaining belongs.
        Binding("down", "move(1)", "Navigate", tooltip="Down", show=False),
        Binding("up", "move(-1)", "Up", show=False),
        Binding("right", "expand", "Expand"),
        Binding("left", "collapse", "Collapse"),
        Binding("enter,space", "toggle", "Expand or collapse", show=False),
    ]

    def __init__(
        self,
        categories: list[dict],
        name_map: dict[str, str],
        palette: Palette | None = None,
    ) -> None:
        super().__init__()
        self._cats = [c for c in categories if _cat_is_shown(c)]
        self._name_map = name_map
        self._palette = palette
        self._collapsed: set[int] = set()
        self._cursor = 0

    def on_mount(self) -> None:
        self._render_tree()
        self.focus()

    @staticmethod
    def _has_kids(cat: dict) -> bool:
        return bool(_shown_breakdown(cat))

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
                aggregate_cell(
                    cat.get("spent_home_cents"), unconverted_of(cat), self._palette, AMOUNT_RULE
                ),
                style=row_style,
            )
            if kids and i not in self._collapsed:
                for sub in _shown_breakdown(cat):
                    ids = sub.get("hashtag_ids") or []
                    t.add_row(
                        "    " + dashboard_cmd.hashtag_label(ids, self._name_map),
                        aggregate_cell(
                            sub.get("spent_home_cents"),
                            unconverted_of(sub),
                            self._palette,
                            AMOUNT_RULE,
                        ),
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
        palette = PALETTE
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
            widgets.append(PeopleView(people, palette))
        widgets.append(Static(Text("Categories — spent this month"), classes="sect"))
        widgets.append(
            CategoriesView(body.get("categories") or [], data["tag_names"], palette=palette)
        )
        widgets.append(Static(Text("Totals"), classes="sect"))
        widgets.append(Static(_totals_table(body.get("totals"), palette)))
        return widgets
