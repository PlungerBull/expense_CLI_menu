"""Home screen — single-line header (wordmark + live stat cluster) + section menu.

The header is one line: the wordmark on the left, and a right-pinned
`net · spent · owed` cluster fed by one current-month dashboard read. The read
runs in a background worker on mount and again whenever you return home (so a
just-logged transaction is reflected); it is failure-silent — offline, no
config, or engine-down leaves the cluster empty and the menu fully usable. The
cluster paints after first paint, so the menu never waits on the network.

The section list is the top-level entry point into every TUI screen; every
entry is wired (the last "soon" stub, Monthly report, shipped 2026-07-08).
"""

from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, OptionList, Static
from textual.widgets.option_list import Option

from expense.commands import dashboard_cmd
from expense.commands._resource import format_cents
from expense.tui.screens._base import screen_fetch_kwargs
from expense.tui.screens.accounts import AccountsScreen
from expense.tui.screens.categories import CategoriesScreen
from expense.tui.screens.hashtags import HashtagsScreen
from expense.tui.screens.inbox import InboxScreen
from expense.tui.screens.outstanding import OutstandingScreen
from expense.tui.screens.quick_log import QuickAddLogScreen
from expense.tui.screens.reconciliations import ReconciliationsScreen
from expense.tui.screens.reports import MonthlyReportScreen
from expense.tui.screens.system import (
    ActivityScreen,
    AuthScreen,
    ConfigScreen,
    RatesScreen,
)
from expense.tui.screens.transactions import TransactionsScreen
from expense.tui.theme import Palette, resolve_palette
from expense.tui.widgets.header import RATE_ALERT_GAP, rate_alert

_BANNER = "◈  EXPENSE WORLD"

# (id, label) — id None renders a non-selectable group header.
_MENU: list[tuple[str | None, str]] = [
    (None, "Capture & ledger"),
    ("log", "Log a transaction"),
    ("inbox", "Inbox"),
    ("transactions", "Transactions"),
    ("reconciliations", "Reconciliations"),
    (None, "Reports"),
    ("outstanding", "Outstanding Amounts"),
    ("report", "Monthly report"),
    (None, "Manage"),
    ("accounts", "Accounts"),
    ("categories", "Categories"),
    ("hashtags", "Hashtags"),
    (None, "System"),
    ("config", "Config"),
    ("auth", "Auth & profile"),
    ("activity", "Activity"),
    ("rates", "Rates"),
]

# kind → screen to push. One table instead of a 14-arm elif (backlog §5); the
# `test_screens_map_covers_every_wired_menu_entry` guard keeps it in lockstep
# with the wired _MENU entries, so a new menu row can't be left dead.
_SCREENS: dict[str, type[Screen]] = {
    "log": QuickAddLogScreen,
    "inbox": InboxScreen,
    "transactions": TransactionsScreen,
    "reconciliations": ReconciliationsScreen,
    "outstanding": OutstandingScreen,
    "report": MonthlyReportScreen,
    "accounts": AccountsScreen,
    "categories": CategoriesScreen,
    "hashtags": HashtagsScreen,
    "config": ConfigScreen,
    "auth": AuthScreen,
    "activity": ActivityScreen,
    "rates": RatesScreen,
}


def _signed(cents: object) -> str:
    """`format_cents` with a leading `+` for non-negative amounts (e.g. `+1,240.50`)."""
    text = format_cents(cents)
    return f"+{text}" if isinstance(cents, int) and cents >= 0 else text


def _extract_stats(body: dict) -> dict:
    """Pull the header's three home-currency figures from a dashboard body.

    net/spent come straight from `totals`; `owed` is the net of every person's
    *home-converted* balance (positive = they owe you, negative = you owe them).
    Native `current_balance_cents` is intentionally ignored — summing across
    currencies would be meaningless — and `None` home-cents are skipped.
    """
    totals = body.get("totals") or {}
    people = body.get("people") or []
    owed = sum(
        p["current_balance_home_cents"]
        for p in people
        if isinstance(p.get("current_balance_home_cents"), int)
    )
    return {
        "net": totals.get("net_home_cents"),
        "spent": totals.get("outflow_home_cents"),
        "owed": owed,
    }


def _stat_cluster(stats: dict | None, palette: Palette | None) -> Text:
    """The right-pinned `net · spent · owed` line as sign-colored Rich text.

    `None` (pre-fetch / failed fetch) → empty. The owed segment is dropped
    entirely when nothing is outstanding (`owed == 0`); otherwise its label and
    color flip with the sign. Colors come from the palette, never literal names.
    """
    if stats is None:
        return Text("")
    pos = palette.success if palette else ""
    neg = palette.error if palette else ""
    sep = ("  ·  ", "dim")
    parts: list = []
    net, spent, owed = stats.get("net"), stats.get("spent"), stats.get("owed")
    if isinstance(net, int):
        parts += [("net ", "dim"), (_signed(net), pos if net >= 0 else neg)]
    if isinstance(spent, int):
        if parts:
            parts.append(sep)
        parts += [("spent ", "dim"), (format_cents(spent), neg)]
    if isinstance(owed, int) and owed != 0:
        if parts:
            parts.append(sep)
        label = "owed to you " if owed > 0 else "you owe "
        parts += [(label, "dim"), (format_cents(abs(owed)), pos if owed > 0 else neg)]
    return Text.assemble(*parts)


def _build_header(
    stats: dict | None, palette: Palette | None, rate_stale: bool | None = None
) -> Table:
    """Wordmark (left) + stat cluster (right), one line, full width.

    `expand=True` with a `ratio=1` left column and a right-justified column pins
    the cluster to the terminal's right edge — the same idiom the section tables
    use. `no_wrap` keeps it on one line; overflow truncates rather than wraps.

    The rate alert trails the cluster, so it sits in the same place as on the
    section screens (far right of the header) despite the two being built
    differently. It is empty unless the rate is known-stale — see `rate_alert`.
    """
    grid = Table(box=None, expand=True, pad_edge=False, show_header=False)
    grid.add_column(ratio=1, no_wrap=True)
    grid.add_column(justify="right", no_wrap=True)

    right = _stat_cluster(stats, palette)
    alert = rate_alert(rate_stale, palette)
    if alert.plain:
        if right.plain:
            right.append(RATE_ALERT_GAP)
        right.append_text(alert)

    grid.add_row(Text(_BANNER, style="bold"), right)
    return grid


class HomeScreen(Screen):
    # q lives here, not on the App — a stray q mid-flow (modal, list) must
    # never kill the app (backlog 4.6). ctrl+q stays the everywhere-quit.
    BINDINGS = [("q", "app.quit", "Quit")]

    _stats: dict | None = None

    def compose(self) -> ComposeResult:
        yield Static(_build_header(None, None), id="brand")
        options: list = []
        for opt_id, label in _MENU:
            if opt_id is None:
                options.append(None)  # separator rule
                options.append(Option(label.upper(), disabled=True))
            else:
                options.append(Option(label, id=opt_id))
        yield OptionList(*options, id="menu")
        yield Footer()

    def on_mount(self) -> None:
        self._load_stats()
        # colors are baked palette hexes, so re-render when the theme switches
        self.app.theme_changed_signal.subscribe(self, lambda _theme: self._rerender())

    def on_screen_resume(self) -> None:
        # returning home after a write should reflect the new numbers
        self._load_stats()

    @work(thread=True, exclusive=True, group="home-stats")
    def _load_stats(self) -> None:
        # failure-silent: home must stay usable offline / unconfigured / engine-down
        from expense import config as config_module

        try:
            cfg = config_module.ensure_loaded()
            body = dashboard_cmd.fetch_dashboard(cfg, **screen_fetch_kwargs(self.app))
        except Exception:
            return
        self.app.call_from_thread(self._set_stats, _extract_stats(body))

    def _set_stats(self, stats: dict) -> None:
        self._stats = stats
        self._rerender()

    def _rerender(self) -> None:
        palette = resolve_palette(self.app)
        self.query_one("#brand", Static).update(
            _build_header(self._stats, palette, getattr(self.app, "rate_stale", None))
        )

    def repaint_header(self) -> None:
        """The app's hook for when `rate_stale` lands (see `ExpenseApp`).

        Home builds its own header instead of using `Breadcrumb`, so it cannot
        be repainted by the app's blanket breadcrumb refresh. The two fetches
        race — dashboard stats and rate status — and whichever finishes second
        must not paint away the first, which is why both go through `_rerender`
        against the current app state rather than through their own update.
        """
        self._rerender()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        screen_cls = _SCREENS.get(event.option.id or "")
        if screen_cls is not None:
            self.app.push_screen(screen_cls())
