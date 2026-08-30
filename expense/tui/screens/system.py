"""System screens — Config, Auth & profile, and the system reads (Phase 2).

Config: read view of engine URL / token (masked) / main currency; `e` edits
the engine URL, `t` sets the token (both write ~/.expense-config). Auth &
profile: identity + settings from GET /auth/me; `b` bootstraps (provisions the
user record). The main currency is display-only — it is locked engine-side
(2026-08-01 rework).

System reads:
  Activity — engine-direct audit log; `enter` shows one entry's before/after.
  Rates    — reference FX lookup (conversion on writes is automatic engine-side).
"""

from rich import box
from rich.table import Table
from rich.text import Text
from textual.widget import Widget
from textual.widgets import Static

from expense.commands._resource import items_of, redact_token
from expense.errors import format_error
from expense.tui.screens._base import PagedListMixin, SectionScreen
from expense.tui.screens.modals import PromptModal, SnapshotModal
from expense.tui.widgets.cursor_list import CursorList


def _redact_token(token: str | None) -> str:
    return "(none)" if not token else redact_token(token)


def _kv_table(rows: list[tuple[str, object]]) -> Table:
    t = Table(box=box.SIMPLE, pad_edge=False, show_header=False)
    t.add_column("k", style="dim")
    t.add_column("v")
    for key, value in rows:
        # a pre-styled Text passes through; the rest stringify
        cell = (
            value
            if isinstance(value, Text)
            else Text(str(value if value not in (None, "") else "—"))
        )
        t.add_row(key, cell)
    return t


class ConfigScreen(SectionScreen):
    crumb = ("System", "Config")
    CARD_WIDTH = 76
    BINDINGS = [
        ("e", "set_engine", "Engine URL"),
        ("t", "set_token", "Token"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._cfg = None

    def fetch(self) -> dict:
        from expense import config as config_module

        return {"cfg": config_module.load()}

    def build(self, data: dict) -> list[Widget]:
        self._cfg = data["cfg"]
        cfg = self._cfg
        rows = [
            ("engine url", getattr(cfg, "engine_url", None)),
            ("token", _redact_token(getattr(cfg, "token", None))),
            ("main currency", getattr(cfg, "main_currency", None)),
        ]
        return [
            Static(Text("Config — engine connection"), classes="section-title"),
            Static(_kv_table(rows)),
            Static(
                Text(
                    "e set engine url · t set token · token is a secret — never logged", style="dim"
                ),
                classes="legend",
            ),
        ]

    def action_set_engine(self) -> None:
        current = getattr(self._cfg, "engine_url", "") or ""

        def cb(value: str | None) -> None:
            if value:
                self._save(engine_url=value)

        self.app.push_screen(PromptModal("Engine URL", value=current), cb)

    def action_set_token(self) -> None:
        def cb(value: str | None) -> None:
            if value:
                self._save(token=value)

        self.app.push_screen(
            PromptModal("Token", "PAT (ewe_pat_…) — hidden as you type", password=True), cb
        )

    def _save(self, **updates) -> None:
        from expense import config as config_module
        from expense.errors import ConfigInvalidError

        if not self._cfg:
            self.notify("No config loaded.", severity="error")
            return
        if "engine_url" in updates:
            # same save-time validation the CLI's `config set` got in backlog
            # 3.4 — a scheme-less URL used to save fine and fail every later
            # call with a generic connection error (backlog 6.3b)
            try:
                config_module.validate_engine_url(updates["engine_url"])
            except ConfigInvalidError as exc:
                self.notify(str(exc), title="Invalid URL", severity="error")
                return
        try:
            config_module.save(self._cfg.model_copy(update=updates))
        except Exception as exc:
            self.notify(format_error(exc), title="Couldn't save", severity="error")
            return
        self.notify("Config saved.")
        self._load()


class AuthScreen(SectionScreen):
    crumb = ("System", "Auth & profile")
    CARD_WIDTH = 76
    BINDINGS = [
        ("b", "bootstrap", "Bootstrap"),
    ]

    def fetch(self) -> dict:
        from expense import config as config_module
        from expense.errors import EngineError
        from expense.http import ExpenseClient

        cfg = config_module.ensure_loaded()
        try:
            with ExpenseClient(cfg, verbose=self.app._verbose) as client:
                body = client.get("/auth/me")
        except EngineError as exc:
            if exc.status == 404:
                return {"provisioned": False}
            raise
        return {
            "provisioned": True,
            "user": body.get("user", {}) or {},
            "settings": body.get("settings", {}) or {},
        }

    def build(self, data: dict) -> list[Widget]:
        if not data.get("provisioned"):
            return [
                Static(Text("Auth & profile"), classes="section-title"),
                Static(
                    Text("No user record yet — press b to bootstrap (provision) it.", style="dim"),
                    classes="legend",
                ),
            ]
        user = data["user"]
        settings = data["settings"]
        rows = [
            ("display name", user.get("display_name")),
            ("user id", user.get("id")),
            ("main currency", settings.get("main_currency")),
            ("timezone", settings.get("display_timezone") or user.get("timezone")),
        ]
        return [
            Static(Text("Auth & profile — your identity & settings"), classes="section-title"),
            Static(_kv_table([(k, v) for k, v in rows if v is not None])),
            Static(
                Text("b bootstrap (provision)", style="dim"),
                classes="legend",
            ),
        ]

    def action_bootstrap(self) -> None:
        def cb(name: str | None) -> None:
            if name:
                self._bootstrap(name)

        self.app.push_screen(
            PromptModal("Bootstrap", "your display name — creates your user record"), cb
        )

    def _bootstrap(self, display_name: str) -> None:
        from expense import dates

        # Resolve before run_write: an undetectable timezone must notify, not
        # crash the app through Textual's message pump (backlog 6.2d).
        try:
            timezone = dates.detect_timezone()
        except dates.TimezoneDetectionError:
            self.notify(
                "Could not detect your timezone. Set the TZ environment variable and "
                "relaunch, or run 'expense auth bootstrap --timezone <zone>' from the CLI.",
                title="Bootstrap failed",
                severity="error",
            )
            return
        self.run_write(
            "POST",
            "/auth/bootstrap",
            json_body={"display_name": display_name, "timezone": timezone},
            on_success=lambda: self._done("Provisioned."),
            on_error=lambda m: self.notify(m, title="Bootstrap failed", severity="error"),
        )

    def _done(self, message: str) -> None:
        self.notify(message)
        self._load()


# ---------------------------------------------------------------------------
# System reads — Activity · Rates
# ---------------------------------------------------------------------------


_ACTIVITY_HEADERS = ["Date", "Time", "Action", "Actor", "Type", "Record"]


class ActivityScreen(PagedListMixin, SectionScreen):
    """Engine-direct audit log, fetch-paged ≤20 rows at a time (PagedListMixin,
    sized to the terminal).

    `enter` opens the before/after snapshot for one entry (the nested dicts the
    CLI human view omits). v1 is unfiltered; filters are a later pass.
    """

    crumb = ("System", "Activity")
    CARD_WIDTH = 118

    def __init__(self) -> None:
        super().__init__()
        self._by_id: dict = {}
        self._cells: dict = {}

    def list_extra_lines(self) -> int:
        return 2  # the "most recent first · ↵ view" legend below (margin-top 1 + text)

    def fetch(self) -> dict:
        # Name resolution is a live engine read per row, so the cells are
        # computed here in the worker thread — build() must never do HTTP.
        from expense import config as config_module
        from expense.commands import activity_cmd
        from expense.http import ExpenseClient

        cfg = config_module.ensure_loaded()
        body = self.fetch_page_body(
            lambda pkw: activity_cmd.fetch_activity(cfg, verbose=self.app._verbose, **pkw)
        )
        rows: list[tuple[str, list[str]]] = []
        by_id: dict = {}
        with ExpenseClient(cfg, verbose=self.app._verbose) as client:
            for i, item in enumerate(items_of(body)):
                if not isinstance(item, dict):
                    continue
                key = item.get("id") or f"row-{i}"
                by_id[key] = item
                rows.append((key, activity_cmd.activity_display_cells(item, client)))
        return {"rows": rows, "by_id": by_id}

    def build(self, data: dict) -> list[Widget]:
        self._by_id = data["by_id"]
        self._cells = dict(data["rows"])
        return [
            CursorList(
                _ACTIVITY_HEADERS,
                data["rows"],
                empty="(no activity)",
                title="Activity — who changed what, and when",
                page_size=self.page_rows,
                page_meta=self.page_meta(),
            ),
            Static(
                Text("most recent first   ·   ↵ view before/after"),
                classes="legend",
            ),
        ]

    def on_cursor_list_selected(self, event: CursorList.Selected) -> None:
        item = self._by_id.get(event.key)
        if not item:
            return
        cells = self._cells.get(event.key) or []
        if len(cells) >= 6:
            title = f"{cells[2]} · {cells[4]} · {cells[5]}"  # ACTION · type · record
        else:
            title = "Activity"
        self.app.push_screen(
            SnapshotModal(title, item.get("before_snapshot"), item.get("after_snapshot"))
        )


_RATES_HEADERS = ["Date", "Base", "Target", "Rate"]


class RatesScreen(PagedListMixin, SectionScreen):
    """Stored daily FX rates — GET /v1/exchange-rates/history (backlog 4.8).

    A plain read table, fetch-paged ≤20 rows at a time (PagedListMixin, sized
    to the terminal): newest first, one row per currency pair per day.
    Cross-currency writes convert automatically engine-side, so this is
    reference data only. `f` filters to an exact day; blank enter clears.
    Replaced the t/b/d letter-jump lookup per the approved v2 mockup.
    """

    crumb = ("System", "Rates")
    CARD_WIDTH = 72
    BINDINGS = [
        ("f", "filter_date", "Filter date"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._date: str | None = None  # exact-day filter; None = full history

    def list_extra_lines(self) -> int:
        return 4  # legends above AND below the list (each: margin-top 1 + text)

    def fetch(self) -> dict:
        from expense import config as config_module
        from expense.commands import rates_cmd

        cfg = config_module.ensure_loaded()
        body = self.fetch_page_body(
            lambda pkw: rates_cmd.fetch_rates_history(
                cfg, date=self._date, verbose=self.app._verbose, **pkw
            )
        )
        return {"items": items_of(body)}

    def build(self, data: dict) -> list[Widget]:
        from expense.commands.rates_cmd import format_rate

        rows = [
            (
                f"{it.get('rate_date')}:{it.get('base')}:{it.get('target')}",
                [
                    str(it.get("rate_date") or "—"),
                    str(it.get("base") or "—"),
                    str(it.get("target") or "—"),
                    format_rate(it.get("rate_e8")),
                ],
            )
            for it in data["items"]
            if isinstance(it, dict)
        ]
        filtered = f"filtered: {self._date}   ·   " if self._date else ""
        empty = f"(no rates stored for {self._date})" if self._date else "(no rates stored yet)"
        return [
            Static(
                Text(
                    "Cross-currency writes convert automatically — this is the reference table.",
                    style="dim",
                ),
                classes="legend",
            ),
            CursorList(
                _RATES_HEADERS,
                rows,
                align_right={3},
                empty=empty,
                title="Exchange rates — stored daily history",
                page_size=self.page_rows,
                page_meta=self.page_meta(),
            ),
            Static(
                Text(f"{filtered}newest first   ·   f filter date"),
                classes="legend",
            ),
        ]

    def action_filter_date(self) -> None:
        def cb(value: str | None) -> None:
            if value is None:
                return  # esc — keep the current filter
            self._date = value.strip() or None  # blank enter clears
            self.reset_page()  # a new filter invalidates the old offset
            self._load()

        self.app.push_screen(
            PromptModal("Filter by date", "YYYY-MM-DD · blank = all days", value=self._date or ""),
            cb,
        )
