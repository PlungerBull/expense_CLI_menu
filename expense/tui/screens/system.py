"""System screens — Config and Auth & profile (Phase 2).

Config: read view of engine URL / token (masked) / client id / main currency /
cache state; `e` edits the engine URL, `t` sets the token (both write
~/.expense-config). Auth & profile: identity + settings from GET /auth/me; `b`
bootstraps (provisions the user record), `m` sets the main currency (PUT
/auth/settings, which triggers the engine's home-currency recalc).
"""

import io

from rich import box
from rich.table import Table
from rich.text import Text
from textual import work
from textual.widget import Widget
from textual.widgets import Static

from expense.tui.screens._base import SectionScreen
from expense.tui.screens.modals import ConfirmModal, PromptModal


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
        ("escape", "app.pop_screen", "Back"),
        ("r", "reload", "Refresh"),
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
            self.notify(str(exc), title="Couldn't save", severity="error")
            return
        self.notify("Config saved.")
        self._load()


class AuthScreen(SectionScreen):
    crumb = ("System", "Auth & profile")
    CARD_WIDTH = 76
    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
        ("r", "reload", "Refresh"),
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
                self.notify, str(exc), title="Bootstrap failed", severity="error"
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
                self.notify, str(exc), title="Couldn't update", severity="error"
            )
            return
        self.app.call_from_thread(self._done, f"Main currency set to {currency}.")

    def _done(self, message: str) -> None:
        self.notify(message)
        self._load()
