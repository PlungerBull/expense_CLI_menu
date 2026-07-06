"""System screens — Config, Auth & profile, and the system reads (Phase 2).

Config: read view of engine URL / token (masked) / client id / main currency /
cache state; `e` edits the engine URL, `t` sets the token (both write
~/.expense-config). Auth & profile: identity + settings from GET /auth/me; `b`
bootstraps (provisions the user record), `m` sets the main currency (PUT
/auth/settings, which triggers the engine's home-currency recalc).

System reads (the last three sections before TUI parity):
  Sync     — status of the local replica + `s` sync (delta) / `f` full rebuild
             (confirms first: a long re-download, though never engine data loss).
  Activity — engine-direct audit log; `enter` shows one entry's before/after.
  Rates    — reference FX lookup (conversion on writes is automatic engine-side).
"""

import io

from rich import box
from rich.table import Table
from rich.text import Text
from textual import work
from textual.widget import Widget
from textual.widgets import Static

from expense.errors import format_error
from expense.tui.screens._base import SectionScreen
from expense.tui.screens.modals import ConfirmModal, PromptModal, SnapshotModal
from expense.tui.widgets.cursor_list import CursorList


def _redact_token(token: str | None) -> str:
    if not token:
        return "(none)"
    if len(token) <= 8:
        return "****"
    return f"{token[:8]}****{token[-4:]}"


def _kv_table(rows: list[tuple[str, object]]) -> Table:
    t = Table(box=box.SIMPLE, pad_edge=False, show_header=False)
    t.add_column("k", style="dim")
    t.add_column("v")
    for key, value in rows:
        t.add_row(key, Text(str(value if value not in (None, "") else "—")))
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

        cfg = config_module.load()
        ready = False
        try:
            from expense.cache import db, state

            conn = db.connect()
            try:
                ready = state.read(conn).sync_token is not None
            finally:
                conn.close()
        except Exception:
            ready = False
        return {"cfg": cfg, "ready": ready}

    def build(self, data: dict) -> list[Widget]:
        self._cfg = data["cfg"]
        cfg = self._cfg
        rows = [
            ("engine url", getattr(cfg, "engine_url", None)),
            ("token", _redact_token(getattr(cfg, "token", None))),
            ("client id", getattr(cfg, "client_id", None)),
            ("main currency", getattr(cfg, "main_currency", None)),
            ("cache", "ready (synced)" if data["ready"] else "not synced yet"),
        ]
        return [
            Static(Text("Config — engine connection & local state"), classes="section-title"),
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

        if not self._cfg:
            self.notify("No config loaded.", severity="error")
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
        ("m", "currency", "Main currency"),
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
            ("email", user.get("email")),
            ("user id", user.get("id")),
            ("main currency", settings.get("main_currency")),
            ("timezone", settings.get("display_timezone") or user.get("timezone")),
        ]
        return [
            Static(Text("Auth & profile — your identity & settings"), classes="section-title"),
            Static(_kv_table([(k, v) for k, v in rows if v is not None])),
            Static(
                Text("b bootstrap (provision) · m set main currency (USD/PEN)", style="dim"),
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

    def action_currency(self) -> None:
        def cb(value: str | None) -> None:
            if not value:
                return
            cur = value.upper()
            if cur not in ("USD", "PEN"):
                self.notify("Enter USD or PEN.", severity="error")
                return

            def confirm(ok: bool | None) -> None:
                if ok:
                    self._set_currency(cur)

            self.app.push_screen(
                ConfirmModal(
                    "Change main currency?",
                    f"Set main currency to {cur}. This triggers a home-currency "
                    "recalculation across your transactions on the engine.",
                ),
                confirm,
            )

        self.app.push_screen(PromptModal("Main currency", "USD or PEN"), cb)

    @work(thread=True, exclusive=True)
    def _bootstrap(self, display_name: str) -> None:
        from expense import config as config_module
        from expense.cache import refresh_after_write
        from expense.commands import auth_cmd
        from expense.http import ExpenseClient

        cfg = config_module.ensure_loaded()
        try:
            with ExpenseClient(cfg, verbose=self.app._verbose) as client:
                client.post(
                    "/auth/bootstrap",
                    json_body={
                        "display_name": display_name,
                        "timezone": auth_cmd._detect_timezone(),
                    },
                )
                refresh_after_write(
                    client,
                    cfg,
                    no_cache=self.app._no_cache,
                    no_sync_after=False,
                    notice_stream=io.StringIO(),
                )
        except Exception as exc:
            self.app.call_from_thread(
                self.notify, format_error(exc), title="Bootstrap failed", severity="error"
            )
            return
        self.app.call_from_thread(self._done, "Provisioned.")

    @work(thread=True, exclusive=True)
    def _set_currency(self, currency: str) -> None:
        from expense import config as config_module
        from expense.cache import refresh_after_write
        from expense.http import ExpenseClient

        cfg = config_module.ensure_loaded()
        try:
            with ExpenseClient(cfg, verbose=self.app._verbose) as client:
                client.put("/auth/settings", json_body={"main_currency": currency})
                refresh_after_write(
                    client,
                    cfg,
                    no_cache=self.app._no_cache,
                    no_sync_after=False,
                    notice_stream=io.StringIO(),
                )
            config_module.save(cfg.model_copy(update={"main_currency": currency}))
        except Exception as exc:
            self.app.call_from_thread(
                self.notify, format_error(exc), title="Couldn't update", severity="error"
            )
            return
        self.app.call_from_thread(self._done, f"Main currency set to {currency}.")

    def _done(self, message: str) -> None:
        self.notify(message)
        self._load()


# ---------------------------------------------------------------------------
# System reads — Sync · Activity · Rates
# ---------------------------------------------------------------------------


def _short_token(token: str | None) -> str:
    if not token:
        return "(none)"
    if len(token) <= 12:
        return token
    return f"{token[:6]}…{token[-4:]}"


class SyncScreen(SectionScreen):
    """The local-replica status + refresh controls.

    Sync normally runs on its own after every write; this screen exists for
    the cross-client case (data changed elsewhere) and for a manual full
    rebuild. Reuses `cache.delta_sync` / `cache.cold_start` — no logic here.
    """

    crumb = ("System", "Sync")
    CARD_WIDTH = 80
    BINDINGS = [
        ("s", "sync", "Sync"),
        ("f", "full", "Full rebuild"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._last = None  # last SyncSummary from an in-app run

    def fetch(self) -> dict:
        from expense.cache import cache_path, db, state

        info: dict = {"sync_token": None, "last_synced_at": None, "ready": False}
        try:
            info["cache_path"] = str(cache_path())
        except Exception:
            info["cache_path"] = None
        if getattr(self.app, "_no_cache", False):
            info["disabled"] = True
            return info
        try:
            conn = db.connect()
            try:
                cur = state.read(conn)
            finally:
                conn.close()
            info["sync_token"] = cur.sync_token
            info["last_synced_at"] = cur.last_synced_at
            info["ready"] = cur.sync_token is not None
        except Exception:
            pass
        return info

    def build(self, data: dict) -> list[Widget]:
        widgets: list[Widget] = [
            Static(Text("Sync — refresh the local copy from the engine"), classes="section-title"),
        ]
        if data.get("disabled"):
            widgets.append(
                Static(
                    Text(
                        "Cache is disabled (--no-cache / EXPENSE_STATELESS). Nothing to sync.",
                        style="dim",
                    ),
                    classes="legend",
                )
            )
            return widgets
        rows = [
            ("last synced", data.get("last_synced_at") or "never"),
            ("sync token", _short_token(data.get("sync_token"))),
            ("cache file", data.get("cache_path")),
            ("state", "ready (synced)" if data.get("ready") else "not synced yet"),
        ]
        widgets.append(Static(_kv_table(rows)))
        if self._last is not None:
            widgets.append(
                Static(
                    Text(
                        "rebuilt" if self._last.kind == "cold_start" else "last run — delta applied"
                    ),
                    classes="section-title",
                )
            )
            widgets.append(Static(_delta_table(self._last)))
        widgets.append(
            Static(
                Text(
                    "s sync · f full rebuild · engine is the source of truth",
                    style="dim",
                ),
                classes="legend",
            )
        )
        return widgets

    def action_sync(self) -> None:
        self._run_sync(full=False)

    def action_full(self) -> None:
        # confirms not because data is at risk (replica only; next read
        # auto-cold-starts) but because an f=Filter slip buys a long re-download
        def _cb(confirmed: bool | None) -> None:
            if confirmed:
                self._run_sync(full=True)

        self.app.push_screen(
            ConfirmModal(
                "Rebuild local cache?",
                "Deletes ~/.expense-cache.sqlite3 and re-downloads everything — "
                "no engine data is touched, but it can take a while.",
            ),
            _cb,
        )

    @work(thread=True, exclusive=True)
    def _run_sync(self, *, full: bool) -> None:
        from expense import cache as cache_pkg
        from expense import config as config_module
        from expense.http import ExpenseClient

        if getattr(self.app, "_no_cache", False):
            self.app.call_from_thread(
                self.notify, "Cache is disabled; nothing to sync.", severity="warning"
            )
            return
        cfg = config_module.ensure_loaded()
        try:
            with ExpenseClient(cfg, verbose=self.app._verbose, cold_start_notice=False) as client:
                summary = (
                    cache_pkg.cold_start(client, cfg) if full else cache_pkg.delta_sync(client, cfg)
                )
        except Exception as exc:
            self.app.call_from_thread(
                self.notify, format_error(exc), title="Sync failed", severity="error"
            )
            return
        self.app.call_from_thread(self._synced, summary)

    def _synced(self, summary) -> None:
        self._last = summary
        verb = "Rebuilt cache" if summary.kind == "cold_start" else "Refreshed"
        self.notify(f"{verb}. token {_short_token(summary.sync_token)}")
        self._load()


def _delta_table(summary) -> Table:
    """Per-resource added/changed/removed counts from a SyncSummary.

    Cold-start populates only `inserts`; the missing update/tombstone dicts
    read as 0, which is correct (a fresh cache has nothing to change/remove).
    """
    from expense.cache import RESOURCE_KEYS

    t = Table(box=box.SIMPLE, pad_edge=False)
    t.add_column("resource", style="dim")
    t.add_column("added", justify="right")
    t.add_column("changed", justify="right")
    t.add_column("removed", justify="right")
    for key in RESOURCE_KEYS:
        ins = summary.inserts.get(key, 0)
        upd = summary.updates.get(key, 0)
        tomb = summary.tombstones.get(key, 0)
        t.add_row(key, f"+{ins}", f"~{upd}", f"−{tomb}")
    t.add_row(
        "settings",
        "replaced" if summary.settings_changed else "unchanged",
        "",
        "",
    )
    return t


_ACTIVITY_PAGE = 50
_ACTIVITY_HEADERS = ["Date", "Time", "Action", "Actor", "Type", "Record"]


class ActivityScreen(SectionScreen):
    """Engine-direct audit log — the most recent page of changes.

    `enter` opens the before/after snapshot for one entry (the nested dicts the
    CLI human view omits). v1 is unfiltered; filters/pagination are a later pass.
    """

    crumb = ("System", "Activity")
    CARD_WIDTH = 118

    def __init__(self) -> None:
        super().__init__()
        self._by_id: dict = {}

    def fetch(self) -> dict:
        from expense import config as config_module
        from expense.commands import activity_cmd

        cfg = config_module.ensure_loaded()
        body = activity_cmd.fetch_activity(cfg, limit=_ACTIVITY_PAGE, verbose=self.app._verbose)
        items = body.get("items", body) if isinstance(body, dict) else (body or [])
        total = body.get("total") if isinstance(body, dict) else None
        return {"items": items, "total": total}

    def build(self, data: dict) -> list[Widget]:
        from expense.commands import activity_cmd

        items = data["items"]
        self._by_id = {}
        rows = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            key = item.get("id") or f"row-{i}"
            self._by_id[key] = item
            rows.append((key, activity_cmd.activity_display_cells(item)))
        total = data["total"]
        shown = len(rows)
        count = f"showing {shown} of {total}" if isinstance(total, int) else f"showing {shown}"
        return [
            Static(Text("Activity — who changed what, and when"), classes="section-title"),
            CursorList(_ACTIVITY_HEADERS, rows, empty="(no activity)"),
            Static(
                Text(f"{count}   ·   most recent first   ·   ↵ view before/after"),
                classes="legend",
            ),
        ]

    def on_cursor_list_selected(self, event: CursorList.Selected) -> None:
        item = self._by_id.get(event.key)
        if not item:
            return
        from expense.commands import activity_cmd

        cells = activity_cmd.activity_display_cells(item)
        title = f"{cells[2]} · {cells[4]} · {cells[5]}"  # ACTION · type · record
        self.app.push_screen(
            SnapshotModal(title, item.get("before_snapshot"), item.get("after_snapshot"))
        )


_RATES_PAGE = 50
_RATES_HEADERS = ["Date", "Base", "Target", "Rate"]


class RatesScreen(SectionScreen):
    """Stored daily FX rates — GET /v1/exchange-rates/history (backlog 4.8).

    A plain read table: newest first, one row per currency pair per day.
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

    def fetch(self) -> dict:
        from expense import config as config_module
        from expense.commands import rates_cmd

        cfg = config_module.ensure_loaded()
        body = rates_cmd.fetch_rates_history(
            cfg, date=self._date, limit=_RATES_PAGE, verbose=self.app._verbose
        )
        items = body.get("items", body) if isinstance(body, dict) else (body or [])
        total = body.get("total") if isinstance(body, dict) else None
        return {"items": items, "total": total}

    def build(self, data: dict) -> list[Widget]:
        from expense.commands.rates_cmd import format_rate

        rows = [
            (
                f"{it.get('rate_date')}:{it.get('base')}:{it.get('target')}",
                [
                    str(it.get("rate_date") or "—"),
                    str(it.get("base") or "—"),
                    str(it.get("target") or "—"),
                    format_rate(it.get("rate")),
                ],
            )
            for it in data["items"]
            if isinstance(it, dict)
        ]
        total = data["total"]
        shown = len(rows)
        count = f"showing {shown} of {total}" if isinstance(total, int) else f"showing {shown}"
        filtered = f"filtered: {self._date}   ·   " if self._date else ""
        empty = f"(no rates stored for {self._date})" if self._date else "(no rates stored yet)"
        return [
            Static(Text("Exchange rates — stored daily history"), classes="section-title"),
            Static(
                Text(
                    "Cross-currency writes convert automatically — this is the reference table.",
                    style="dim",
                ),
                classes="legend",
            ),
            CursorList(_RATES_HEADERS, rows, align_right={3}, empty=empty),
            Static(
                Text(f"{filtered}{count}   ·   newest first   ·   f filter date"),
                classes="legend",
            ),
        ]

    def action_filter_date(self) -> None:
        def cb(value: str | None) -> None:
            if value is None:
                return  # esc — keep the current filter
            self._date = value.strip() or None  # blank enter clears
            self._load()

        self.app.push_screen(
            PromptModal("Filter by date", "YYYY-MM-DD · blank = all days", value=self._date or ""),
            cb,
        )
