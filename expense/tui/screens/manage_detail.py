"""Manage record detail — the per-record screen behind `enter` on the
Accounts / Categories / Hashtags lists (Phase 2, Option B).

`enter` on a list row opens a read detail here (enter never mutates). From the
detail: `e` edits (rename/recolor via the prefilled create bar-form), `a`
archives/unarchives, `esc` returns to the list. After any write the record is
re-fetched so the detail shows the new state in place; the list reloads when you
`esc` back (its push callback).

System categories: `e` **is** offered — the engine resolves system categories
by `system_key`, not name, so rename/recolor is pipeline-safe and allowed
(engine-spec §Categories). `a` is hidden — archive/delete deterministically
`403` for system categories (they anchor the transfer pipeline), so suppressing
the action reflects engine truth rather than inventing a client-side rule.
"""

from rich import box
from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Static
from textual.worker import get_current_worker

from expense.commands._resource import items_of
from expense.errors import format_error
from expense.tui.screens._base import EngineWriteMixin, screen_fetch_kwargs
from expense.tui.screens.create_forms import (
    EditAccountScreen,
    EditCategoryScreen,
    EditHashtagScreen,
)
from expense.tui.screens.modals import ConfirmModal
from expense.tui.theme import AMOUNT_RULE, resolve_palette
from expense.tui.widgets.cells import amount_cell, swatch
from expense.tui.widgets.header import Breadcrumb


def color_value(color: object) -> Text:
    """A swatch + hex for the Color detail row, or a dim em-dash if unset."""
    sw = swatch(color)
    if sw.plain == "—":  # unset → swatch already renders the em-dash
        return sw
    out = sw.copy()
    out.append(f"  {color}", style="dim")
    return out


def status_value(record: dict) -> Text:
    """`archived` (dim) or `active` for the Status detail row."""
    if record.get("is_archived"):
        return Text("archived", style="dim")
    return Text("active")


class ManageDetailScreen(EngineWriteMixin, Screen):
    """Base detail for one Manage record. Subclasses set RESOURCE / LABEL /
    SECTION / EDIT_FORM and implement `_rows()` + `_fetch_fresh()`."""

    RESOURCE = ""  # engine collection, e.g. "accounts"
    LABEL = ""  # singular noun for prompts, e.g. "account"
    SECTION = ""  # breadcrumb section, e.g. "Accounts"
    EDIT_FORM: type | None = None

    BINDINGS = [
        ("escape", "back", "Back"),
        ("e", "edit", "Edit"),
        ("a", "archive", "Archive"),
    ]

    def __init__(self, record: dict) -> None:
        super().__init__()
        self._record = record or {}
        self._rid = self._record.get("id")
        self._busy = False

    # ---- binding availability -------------------------------------------
    def check_action(self, action: str, parameters: tuple) -> bool | None:
        if action == "edit" and self.EDIT_FORM is None:
            return None
        if action == "archive" and self._record.get("is_system"):
            return None  # system categories 403 on archive — hide, don't offer
        return True

    # ---- layout ----------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Breadcrumb(("Manage", self.SECTION, self._display_name()), id="crumb")
        yield VerticalScroll(Static("", id="detail"), id="content")
        yield Static("", id="dhint")
        yield Footer()

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, lambda _theme: self._repaint())
        self._repaint()

    def _display_name(self) -> str:
        return self._record.get("name") or "—"

    def _repaint(self) -> None:
        self.query_one("#detail", Static).update(
            Group(Text(self._display_name(), style="bold"), self._detail_table())
        )
        self.query_one("#dhint", Static).update(Text(self._hint(), style="dim"))

    def _detail_table(self) -> RenderableType:
        t = Table(box=box.SIMPLE, pad_edge=False, show_header=False)
        t.add_column("field", style="dim", no_wrap=True)
        t.add_column("value")
        for label, value in self._rows():
            t.add_row(label, value)
        return t

    def _hint(self) -> str:
        parts = []
        if self.EDIT_FORM is not None:
            parts.append("e edit")
        if not self._record.get("is_system"):
            parts.append("a unarchive" if self._record.get("is_archived") else "a archive")
        parts.append("esc back")
        return " · ".join(parts)

    # ---- actions ---------------------------------------------------------
    def action_back(self) -> None:
        self.dismiss()

    def action_edit(self) -> None:
        if self.EDIT_FORM is None:
            return
        self.app.push_screen(self.EDIT_FORM(self._record), lambda _result: self._reload())

    def action_archive(self) -> None:
        if self._busy or self._record.get("is_system"):
            return
        if self._record.get("is_archived"):
            self._write(f"/{self.RESOURCE}/{self._rid}/unarchive", "Unarchived.")
            return

        def _cb(confirmed: bool | None) -> None:
            if confirmed:
                self._write(f"/{self.RESOURCE}/{self._rid}/archive", "Archived.")

        self.app.push_screen(
            ConfirmModal(f"Archive {self.LABEL}?", f"Archive “{self._display_name()}”."), _cb
        )

    def _write(self, path: str, done: str) -> None:
        self._busy = True
        self.run_write(
            "POST",
            path,
            on_success=lambda: self._written(done),
            on_error=self._failed,
        )

    def _written(self, message: str) -> None:
        self._busy = False
        self.notify(message)
        self._reload()

    def _failed(self, message: str) -> None:
        self._busy = False
        self.notify(message, title="Failed", severity="error")

    # ---- reload the single record after a write --------------------------
    # Own group so a reload never cancels an in-flight run_write (engine-write).
    @work(thread=True, exclusive=True, group="manage-detail-load")
    def _reload(self) -> None:
        from expense import config as config_module

        worker = get_current_worker()
        try:
            cfg = config_module.ensure_loaded()
            fresh = next((it for it in self._fetch_fresh(cfg) if it.get("id") == self._rid), None)
        except Exception as exc:  # surface engine/config errors in-app, don't crash
            if not worker.is_cancelled:
                self.app.call_from_thread(self.notify, format_error(exc), severity="error")
            return
        if worker.is_cancelled:
            return
        if fresh is None:
            self.app.call_from_thread(self._gone)
            return
        self._record = fresh
        self.app.call_from_thread(self._repaint)
        self.app.call_from_thread(self.refresh_bindings)

    def _gone(self) -> None:
        self.notify(f"This {self.LABEL} no longer exists.", severity="error")
        self.dismiss()

    # ---- subclass hooks --------------------------------------------------
    def _rows(self) -> list[tuple[str, RenderableType]]:
        raise NotImplementedError

    def _fetch_fresh(self, cfg) -> list[dict]:
        raise NotImplementedError

    def _fetch_kw(self) -> dict:
        return screen_fetch_kwargs(self.app)


class AccountDetailScreen(ManageDetailScreen):
    RESOURCE = "accounts"
    LABEL = "account"
    SECTION = "Accounts"
    EDIT_FORM = EditAccountScreen

    def _rows(self) -> list[tuple[str, RenderableType]]:
        r = self._record
        currency = Text(r.get("currency_code") or "?")
        currency.append("   read-only", style="dim")
        bal_cents = r.get("current_balance_cents")
        balance = amount_cell(bal_cents, resolve_palette(self.app), AMOUNT_RULE)
        return [
            ("Name", Text(r.get("name") or "—")),
            ("Type", Text("person" if r.get("is_person") else "bank")),
            ("Currency", currency),
            ("Color", color_value(r.get("color"))),
            ("Balance", balance),
            ("Status", status_value(r)),
        ]

    def _fetch_fresh(self, cfg) -> list[dict]:
        from expense.commands import accounts_cmd

        return items_of(
            accounts_cmd.fetch_accounts(
                cfg, include_archived=True, include_people=True, **self._fetch_kw()
            )
        )


class CategoryDetailScreen(ManageDetailScreen):
    RESOURCE = "categories"
    LABEL = "category"
    SECTION = "Categories"
    EDIT_FORM = EditCategoryScreen

    def _rows(self) -> list[tuple[str, RenderableType]]:
        r = self._record
        system = Text("yes 🔒", style="bold") if r.get("is_system") else Text("—", style="dim")
        return [
            ("Name", Text(r.get("name") or "—")),
            ("Color", color_value(r.get("color"))),
            ("System", system),
            ("Status", status_value(r)),
        ]

    def _fetch_fresh(self, cfg) -> list[dict]:
        from expense.commands import categories_cmd

        return items_of(
            categories_cmd.fetch_categories(cfg, include_archived=True, **self._fetch_kw())
        )


class HashtagDetailScreen(ManageDetailScreen):
    RESOURCE = "hashtags"
    LABEL = "hashtag"
    SECTION = "Hashtags"
    EDIT_FORM = EditHashtagScreen

    def _display_name(self) -> str:
        name = self._record.get("name")
        return "#" + name.lstrip("#") if name else "—"

    def _rows(self) -> list[tuple[str, RenderableType]]:
        return [
            ("Name", Text(self._display_name())),
            ("Status", status_value(self._record)),
        ]

    def _fetch_fresh(self, cfg) -> list[dict]:
        from expense.commands import hashtags_cmd

        return items_of(hashtags_cmd.fetch_hashtags(cfg, include_archived=True, **self._fetch_kw()))
