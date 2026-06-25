"""Home screen — header banner + the section menu.

Phase 0 wires only Outstanding Amounts (the one approved live view); every
other section is a placeholder that says it's coming. The section list mirrors
the groups in `expense/menu/app.py`.
"""

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, OptionList, Static
from textual.widgets.option_list import Option

from expense.tui.screens.inbox import InboxScreen
from expense.tui.screens.outstanding import OutstandingScreen
from expense.tui.screens.transactions import TransactionsScreen

_BANNER = "◈  EXPENSE WORLD"

# (id, label) — id None renders a non-selectable group header.
_MENU: list[tuple[str | None, str]] = [
    (None, "Capture & ledger"),
    ("soon", "Log a transaction"),
    ("inbox", "Inbox"),
    ("transactions", "Transactions"),
    ("soon", "Reconciliations"),
    (None, "Reports"),
    ("outstanding", "Outstanding Amounts"),
    ("soon", "Monthly report"),
    (None, "Manage"),
    ("soon", "Accounts"),
    ("soon", "Categories"),
    ("soon", "Hashtags"),
    (None, "System"),
    ("soon", "Config · Auth · Sync · Activity · Rates"),
]


class HomeScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Static(f"{_BANNER}\nyour money, in the terminal", id="brand")
        yield Static("● connected — engine via ~/.expense-config", id="status")
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
        elif kind == "inbox":
            self.app.push_screen(InboxScreen())
        elif kind == "transactions":
            self.app.push_screen(TransactionsScreen())
        elif kind == "soon":
            self.notify("Coming in a later phase.", title="Not wired yet")
