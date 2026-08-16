"""Accounts screen — banks & people.

Built on SectionScreen + the shared CursorList. Includes people and archived
accounts (archived rows dimmed); the Color column renders the account's hex
color as a swatch. Native-currency balances (home equivalents live in
Outstanding Amounts). `n` creates; `e` edits the cursor row (prefilled
EditAccountScreen); `a` toggles archive immediately — a second `a` undoes.
`enter` does nothing.
"""

from expense.commands import accounts_cmd
from expense.tui.screens._base import ResourceListScreen
from expense.tui.theme import AMOUNT_RULE, Palette, resolve_palette
from expense.tui.widgets.cells import amount_cell, swatch

_HEADERS = ["Name", "Type", "Cur", "Color", "Balance", "Status"]


def account_rows(items: list[dict], palette: Palette | None = None) -> list:
    """Pure (id, cells, base_style) rows for a CursorList. Unit-testable."""
    rows = []
    for it in items:
        archived = bool(it.get("is_archived"))
        cells = [
            it.get("name") or "(unnamed)",
            "person" if it.get("is_person") else "bank",
            it.get("currency_code") or "?",
            swatch(it.get("color")),
            amount_cell(it.get("current_balance_cents"), palette, AMOUNT_RULE),
            "archived" if archived else "active",
        ]
        rows.append((it.get("id"), cells, "dim" if archived else ""))
    return rows


class AccountsScreen(ResourceListScreen):
    crumb = ("Manage", "Accounts")
    CARD_WIDTH = 80
    TITLE = "Accounts — banks & people"
    HEADERS = _HEADERS
    EMPTY = "(no accounts)"
    LEGEND = "balances are native currency · home equivalents in Outstanding Amounts"
    ALIGN_RIGHT = {4}
    RESOURCE = "accounts"
    # Accounts are the only archivable resource since the 2026-08-06 engine
    # schema slimming, so the `a` toggle lives here, not on the shared scaffold.
    BINDINGS = [
        *ResourceListScreen.BINDINGS,
        ("a", "archive", "Archive"),
    ]

    def fetch_items(self, cfg, **kw):
        return accounts_cmd.fetch_accounts(cfg, include_archived=True, include_people=True, **kw)

    def action_archive(self) -> None:
        if self._toggle_busy:
            return
        item = self.selected_record()
        if not item:
            return
        verb, msg = (
            ("unarchive", "Unarchived.") if item.get("is_archived") else ("archive", "Archived.")
        )
        self._toggle_busy = True
        self._restore_key = item.get("id")
        self.run_write(
            "POST",
            f"/{self.RESOURCE}/{item['id']}/{verb}",
            success=msg,
            on_error=self._toggle_failed,
        )

    def _toggle_failed(self, message: str) -> None:
        self._toggle_busy = False
        self.notify(message, title="Failed", severity="error")

    def rows(self, items: list) -> list:
        return account_rows(items, palette=resolve_palette(self.app))

    def edit_screen(self, item: dict):
        from expense.tui.screens.create_forms import EditAccountScreen

        return EditAccountScreen(item)

    def new_screen(self):
        from expense.tui.screens.create_forms import NewAccountScreen

        return NewAccountScreen()
