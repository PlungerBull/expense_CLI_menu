"""Step 9.5.13 — menu-driven Sync flows.

Covers:
  - Refresh (delta sync) renders the delta summary
  - Refresh on empty cache falls through to cold_start internally
  - Full rebuild prompts to confirm; on Yes, wipes + cold-starts; on No, no engine call
  - Header line reflects cache state (synced / empty / stateless)
  - BACK / Ctrl-C exit the submenu cleanly
  - Stateless mode routes through a single full-snapshot engine call
"""

from uuid import uuid4

import httpx
import pytest
import respx

from expense import config as config_module
from expense.cache import db as cache_db
from expense.cache import state as cache_state
from expense.menu import prompts
from expense.menu.groups import _common as menu_common
from expense.menu.groups import sync as menu_sync

# ----------------------------------------------------------- fixtures


@pytest.fixture
def configured(tmp_path, monkeypatch):
    config_path = tmp_path / ".expense-config"
    cache_file = tmp_path / ".expense-cache.sqlite3"
    monkeypatch.setenv("EXPENSE_CONFIG", str(config_path))
    monkeypatch.setenv("EXPENSE_CACHE", str(cache_file))
    monkeypatch.setenv("EXPENSE_NO_SYNC_AFTER", "1")
    config_module.save(
        config_module.Config(
            engine_url="https://api.example.com",
            token="ewe_pat_test",
            client_id=uuid4(),
        )
    )
    yield


@pytest.fixture
def configured_stateless(configured, monkeypatch):
    monkeypatch.setenv("EXPENSE_STATELESS", "1")
    yield


# ----------------------------------------------------------- helpers


class _FakeAsk:
    def __init__(self, answer):
        self._answer = answer

    def ask(self):
        if isinstance(self._answer, BaseException):
            raise self._answer
        return self._answer


class _PromptScript:
    def __init__(self, answers: list):
        self._queue = list(answers)

    def __call__(self, *_args, **_kwargs):
        if not self._queue:
            raise AssertionError("Prompt script exhausted — unexpected questionary call.")
        return _FakeAsk(self._queue.pop(0))

    @property
    def remaining(self) -> int:
        return len(self._queue)


def _patch_questionary(monkeypatch, script: _PromptScript) -> None:
    monkeypatch.setattr(menu_common.questionary, "text", script)
    monkeypatch.setattr(menu_common.questionary, "select", script)
    monkeypatch.setattr(menu_sync.questionary, "select", script)
    monkeypatch.setattr(prompts.questionary, "select", script)
    monkeypatch.setattr(prompts.questionary, "text", script)


class _StubCtx:
    def __init__(self, *, no_cache: bool = False):
        from expense.context import AppContext

        self.obj = AppContext(verbose=False, no_cache=no_cache, no_sync_after=True)


def _make_ctx(*, no_cache: bool = False) -> _StubCtx:
    return _StubCtx(no_cache=no_cache)


def _seed_cache(*, sync_token: str, last_synced_at: str, client_id: str) -> None:
    """Seed the SQLite replica with a healthy meta row."""
    conn = cache_db.connect()
    try:
        cache_state.write_identity(
            conn,
            user_id="user-1",
            client_id=client_id,
            engine_url="https://api.example.com",
        )
        conn.execute(
            "UPDATE _cache_meta SET sync_token = ?, last_synced_at = ? WHERE id = 1",
            (sync_token, last_synced_at),
        )
    finally:
        conn.close()


# ----------------------------------------------------------- fixtures: engine responses


DELTA_RESPONSE = {
    "accounts": [],
    "categories": [],
    "hashtags": [],
    "transactions": [],
    "inbox": [],
    "reconciliations": [],
    "settings": None,
    "sync_token": "delta-token-after",
}


COLD_START_RESPONSE = {
    "accounts": [],
    "categories": [],
    "hashtags": [],
    "transactions": [],
    "inbox": [],
    "reconciliations": [],
    "settings": {
        "user_id": "user-1",
        "default_currency_code": "USD",
    },
    "sync_token": "cold-start-token",
}


# ----------------------------------------------------------- 1. Refresh


@respx.mock
def test_run_refresh_delta_after_warm_cache(configured, monkeypatch, capsys):
    """Pre-seeded cache → delta sync; renderer shows the per-resource block."""
    cfg = config_module.ensure_loaded()
    _seed_cache(
        sync_token="prior-token-abcdef",
        last_synced_at="2026-05-25T10:00:00Z",
        client_id=str(cfg.client_id),
    )
    route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=DELTA_RESPONSE)
    )
    script = _PromptScript([""])  # pause
    _patch_questionary(monkeypatch, script)

    menu_sync.run_refresh(_make_ctx())

    assert route.call_count == 1
    # Delta sync sends the stored token.
    assert route.calls.last.request.url.params.get("sync_token") == "prior-token-abcdef"
    out = capsys.readouterr().out
    assert "Sync (delta)" in out
    assert "About to call:" in out
    assert "expense sync" in out


@respx.mock
def test_run_refresh_cold_starts_when_cache_absent(configured, monkeypatch, capsys):
    """No prior cache → delta_sync falls through to cold_start; renderer shows full snapshot."""
    route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=COLD_START_RESPONSE)
    )
    script = _PromptScript([""])  # pause
    _patch_questionary(monkeypatch, script)

    menu_sync.run_refresh(_make_ctx())

    assert route.call_count == 1
    # Cold-start sends sync_token=*.
    assert route.calls.last.request.url.params.get("sync_token") == "*"
    out = capsys.readouterr().out
    assert "Sync (full snapshot)" in out


# ----------------------------------------------------------- 2. Full rebuild


@respx.mock
def test_run_full_rebuild_confirmed_wipes_and_cold_starts(configured, monkeypatch, capsys):
    """Confirmed Full rebuild wipes cache, cold-starts, renders cold-start summary."""
    cfg = config_module.ensure_loaded()
    _seed_cache(
        sync_token="prior-token",
        last_synced_at="2026-05-25T10:00:00Z",
        client_id=str(cfg.client_id),
    )
    route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=COLD_START_RESPONSE)
    )
    script = _PromptScript(
        [
            True,  # confirm_destructive → Yes
            "",  # pause
        ]
    )
    _patch_questionary(monkeypatch, script)

    menu_sync.run_full_rebuild(_make_ctx())

    assert route.call_count == 1
    # --full always sends sync_token=*.
    assert route.calls.last.request.url.params.get("sync_token") == "*"
    out = capsys.readouterr().out
    assert "Sync (full snapshot)" in out


@respx.mock
def test_run_full_rebuild_declined_makes_no_engine_call(configured, monkeypatch, capsys):
    """Declined confirm prompts 'Aborted.' and never touches the engine."""
    # No mocked route registered — any HTTP call would raise.
    script = _PromptScript(
        [
            False,  # confirm_destructive → No
            "",  # pause
        ]
    )
    _patch_questionary(monkeypatch, script)

    menu_sync.run_full_rebuild(_make_ctx())

    assert "Aborted." in capsys.readouterr().out
    assert len(respx.calls) == 0


# ----------------------------------------------------------- 3. Header


def test_header_no_cache_yet(configured, monkeypatch, capsys):
    """Empty cache → header advertises cold-start fallback."""
    menu_sync._print_header(_make_ctx())
    out = capsys.readouterr().out
    assert "no local cache yet" in out


def test_header_warm_cache_shows_timestamp_and_token_tail(configured, monkeypatch, capsys):
    cfg = config_module.ensure_loaded()
    _seed_cache(
        sync_token="01HXYZK3V4WG7B2N9ENA4F9C2",
        last_synced_at="2026-05-25T14:32:11Z",
        client_id=str(cfg.client_id),
    )
    menu_sync._print_header(_make_ctx())
    out = capsys.readouterr().out
    assert "Last synced: 2026-05-25T14:32:11Z" in out
    assert "token …A4F9C2" in out  # last 6 chars of the seeded token


def test_header_stateless_mode(configured, monkeypatch, capsys):
    menu_sync._print_header(_make_ctx(no_cache=True))
    out = capsys.readouterr().out
    assert "stateless mode" in out


# ----------------------------------------------------------- 4. Stateless mode (sync)


@respx.mock
def test_run_refresh_stateless_uses_full_snapshot(configured_stateless, monkeypatch, capsys):
    """Stateless mode routes Refresh to a single sync_token=* engine call."""
    route = respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=COLD_START_RESPONSE)
    )
    script = _PromptScript([""])  # pause
    _patch_questionary(monkeypatch, script)

    menu_sync.run_refresh(_make_ctx(no_cache=True))

    assert route.call_count == 1
    assert route.calls.last.request.url.params.get("sync_token") == "*"
    out = capsys.readouterr().out
    assert "Sync (full snapshot)" in out


# ----------------------------------------------------------- 5. Submenu loop


@respx.mock
def test_submenu_dispatches_refresh(configured, monkeypatch):
    """Submenu loop routes 'Refresh (delta sync)' → run_refresh."""
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=COLD_START_RESPONSE)
    )
    script = _PromptScript(
        [
            "Refresh (delta sync)",  # root submenu choice
            "",  # pause after run
            menu_sync.BACK_LABEL,  # exit loop
        ]
    )
    _patch_questionary(monkeypatch, script)

    menu_sync.run_sync_menu(_make_ctx())

    assert script.remaining == 0


def test_submenu_back_returns_immediately(configured, monkeypatch):
    script = _PromptScript([menu_sync.BACK_LABEL])
    _patch_questionary(monkeypatch, script)
    menu_sync.run_sync_menu(_make_ctx())
    assert script.remaining == 0


def test_submenu_ctrl_c_returns(configured, monkeypatch):
    script = _PromptScript([KeyboardInterrupt()])
    _patch_questionary(monkeypatch, script)
    menu_sync.run_sync_menu(_make_ctx())  # silent return = pass


# ----------------------------------------------------------- 6. Recap


@respx.mock
def test_recap_printed_before_call(configured, monkeypatch, capsys):
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=COLD_START_RESPONSE)
    )
    script = _PromptScript([""])
    _patch_questionary(monkeypatch, script)
    menu_sync.run_refresh(_make_ctx())
    out = capsys.readouterr().out
    assert "About to call:" in out
    assert "expense sync" in out


@respx.mock
def test_full_rebuild_recap_includes_full_flag(configured, monkeypatch, capsys):
    respx.get("https://api.example.com/v1/sync").mock(
        return_value=httpx.Response(200, json=COLD_START_RESPONSE)
    )
    script = _PromptScript([True, ""])  # confirm Yes, pause
    _patch_questionary(monkeypatch, script)
    menu_sync.run_full_rebuild(_make_ctx())
    out = capsys.readouterr().out
    assert "expense sync" in out
    assert "--full" in out
