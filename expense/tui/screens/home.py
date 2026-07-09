"""Home screen — header banner + the section menu.

The section list is the top-level entry point into every TUI screen; every
entry is wired (the last "soon" stub, Monthly report, shipped 2026-07-08).
"""

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, OptionList, Static
from textual.widgets.option_list import Option

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
    SyncScreen,
)
from expense.tui.screens.transactions import TransactionsScreen

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
    ("sync", "Sync"),
    ("activity", "Activity"),
    ("rates", "Rates"),
]


class HomeScreen(Screen):
    # q lives here, not on the App — a stray q mid-flow (modal, list) must
    # never kill the app (backlog 4.6). ctrl+q stays the everywhere-quit.
    BINDINGS = [("q", "app.quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Static(f"{_BANNER}\nyour money, in the terminal", id="brand")
        options: list = []
        for opt_id, label in _MENU:
            if opt_id is None:
                options.append(None)  # separator rule
                options.append(Option(label.upper(), disabled=True))
            else:
                options.append(Option(label, id=f"{opt_id}:{label}"))
        yield OptionList(*options, id="menu")
        yield Footer()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        opt_id = event.option.id or ""
        kind = opt_id.split(":", 1)[0]
        if kind == "outstanding":
            self.app.push_screen(OutstandingScreen())
        elif kind == "log":
            self.app.push_screen(QuickAddLogScreen())
        elif kind == "inbox":
            self.app.push_screen(InboxScreen())
        elif kind == "transactions":
            self.app.push_screen(TransactionsScreen())
        elif kind == "reconciliations":
            self.app.push_screen(ReconciliationsScreen())
        elif kind == "config":
            self.app.push_screen(ConfigScreen())
        elif kind == "auth":
            self.app.push_screen(AuthScreen())
        elif kind == "accounts":
            self.app.push_screen(AccountsScreen())
        elif kind == "categories":
            self.app.push_screen(CategoriesScreen())
        elif kind == "hashtags":
            self.app.push_screen(HashtagsScreen())
        elif kind == "sync":
            self.app.push_screen(SyncScreen())
        elif kind == "activity":
            self.app.push_screen(ActivityScreen())
        elif kind == "rates":
            self.app.push_screen(RatesScreen())
        elif kind == "report":
            self.app.push_screen(MonthlyReportScreen())
