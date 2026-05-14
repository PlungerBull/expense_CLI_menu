"""Step 9.5.7 — menu-driven Auth & profile flows.

Covers show-profile / bootstrap / update-display-name / update-settings /
update-main-currency, plus the first-run gate (no token → hint + pause).
HTTP layer is mocked with respx; questionary prompts are driven by a
queued script — same pattern as test_menu_config.py.
"""

import json
from uuid import uuid4

import httpx
import pytest
import respx

from expense import config as config_module
from expense.config import Config
from expense.menu import prompts
from expense.menu.groups import _common as menu_common
from expense.menu.groups import auth as menu_auth

BOOTSTRAP_RESPONSE = {
    "user": {
        "id": "u_123",
        "email": "x@y.com",
        "display_name": "Alex",
        "last_login_at": "2026-04-23T10:00:00Z",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-04-23T10:00:00Z",
    },
    "settings": {
        "user_id": "u_123",
        "theme": 0,
        "start_of_week": 0,
        "main_currency": "USD",
        "transaction_sort_preference": 0,
        "display_timezone": "America/Lima",
        "sidebar_show_bank_accounts": True,
        "sidebar_show_people": True,
        "sidebar_show_categories": True,
        "version": 1,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-04-23T10:00:00Z",
        "deleted_at": None,
    },
}


@pytest.fixture
def no_token(tmp_path, monkeypatch):
    """EXPENSE_CONFIG points at a temp path with no config file."""
    config_path = tmp_path / "config.json"
    monkeypatch.setenv("EXPENSE_CONFIG", str(config_path))
    monkeypatch.setenv("EXPENSE_STATELESS", "1")
    yield config_path


@pytest.fixture
def bootstrapped_config(tmp_path, monkeypatch):
    """Config with engine_url and token set — auth flows can hit the (mocked) engine."""
    config_path = tmp_path / "config.json"
    monkeypatch.setenv("EXPENSE_CONFIG", str(config_path))
    monkeypatch.setenv("EXPENSE_STATELESS", "1")
    config_module.save(
        Config(
            engine_url="https://api.example.com",
            token="ewe_pat_test",
            client_id=uuid4(),
        )
    )
    yield config_path


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
    for mod in (menu_common, menu_auth, prompts):
        monkeypatch.setattr(mod.questionary, "text", script)
        monkeypatch.setattr(mod.questionary, "select", script)
    monkeypatch.setattr(menu_common.questionary, "password", script)


class _StubCtx:
    def __init__(self):
        from expense.context import AppContext

        self.obj = AppContext(verbose=False, no_cache=True, no_sync_after=True)


def _make_ctx() -> _StubCtx:
    return _StubCtx()


# ----- validator unit tests -----


def test_display_name_validator():
    assert menu_auth._validate_display_name("") != True  # noqa: E712
    assert menu_auth._validate_display_name("   ") != True  # noqa: E712
    assert menu_auth._validate_display_name("Alex") is True
    assert menu_auth._validate_display_name("  Alex Tern  ") is True


def test_currency_code_validator():
    assert menu_auth._validate_currency_code("") != True  # noqa: E712
    assert menu_auth._validate_currency_code("usd") != True  # noqa: E712
    assert menu_auth._validate_currency_code("US") != True  # noqa: E712
    assert menu_auth._validate_currency_code("USDT") != True  # noqa: E712
    assert menu_auth._validate_currency_code("US1") != True  # noqa: E712
    assert menu_auth._validate_currency_code("USD") is True
    assert menu_auth._validate_currency_code("PEN") is True


def test_int_validator():
    assert menu_auth._validate_int("") != True  # noqa: E712
    assert menu_auth._validate_int("abc") != True  # noqa: E712
    assert menu_auth._validate_int("0") is True
    assert menu_auth._validate_int("1") is True
    assert menu_auth._validate_int("-3") is True


def test_non_empty_text_validator():
    assert menu_auth._validate_non_empty_text("") != True  # noqa: E712
    assert menu_auth._validate_non_empty_text("   ") != True  # noqa: E712
    assert menu_auth._validate_non_empty_text("America/Lima") is True


def test_optional_timezone_validator_accepts_anything():
    assert menu_auth._validate_optional_timezone("") is True
    assert menu_auth._validate_optional_timezone("America/Lima") is True
    assert menu_auth._validate_optional_timezone("garbage") is True


# ----- flow tests -----


def test_back_exits_cleanly(bootstrapped_config, monkeypatch):
    script = _PromptScript(["← Back"])
    _patch_questionary(monkeypatch, script)
    menu_auth.run_auth_menu(_make_ctx())
    assert script.remaining == 0


def test_keyboard_interrupt_exits(bootstrapped_config, monkeypatch):
    script = _PromptScript([KeyboardInterrupt()])
    _patch_questionary(monkeypatch, script)
    menu_auth.run_auth_menu(_make_ctx())


def test_show_profile_without_token_shows_hint(no_token, monkeypatch, capsys):
    script = _PromptScript(
        [
            "Show my profile (whoami)",
            "",  # pause after hint
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_auth.run_auth_menu(_make_ctx())
    combined = capsys.readouterr()
    assert "Set engine URL and token first" in (combined.out + combined.err)


@respx.mock
def test_show_profile_round_trip(bootstrapped_config, monkeypatch, capsys):
    respx.get("https://api.example.com/v1/auth/me").mock(
        return_value=httpx.Response(200, json=BOOTSTRAP_RESPONSE)
    )
    script = _PromptScript(
        [
            "Show my profile (whoami)",
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_auth.run_auth_menu(_make_ctx())
    out = capsys.readouterr().out
    assert "display_name: Alex" in out
    assert "main_currency: USD" in out


@respx.mock
def test_bootstrap_round_trip_with_explicit_tz(bootstrapped_config, monkeypatch):
    route = respx.post("https://api.example.com/v1/auth/bootstrap").mock(
        return_value=httpx.Response(200, json=BOOTSTRAP_RESPONSE)
    )
    script = _PromptScript(
        [
            "Bootstrap (first-time login)",
            "Alex",  # display name
            "America/Lima",  # timezone
            True,  # confirm
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_auth.run_auth_menu(_make_ctx())
    assert route.call_count == 1
    body = json.loads(route.calls.last.request.content)
    assert body == {"display_name": "Alex", "timezone": "America/Lima"}


@respx.mock
def test_bootstrap_auto_detect_timezone(bootstrapped_config, monkeypatch):
    monkeypatch.setenv("TZ", "America/Lima")
    route = respx.post("https://api.example.com/v1/auth/bootstrap").mock(
        return_value=httpx.Response(200, json=BOOTSTRAP_RESPONSE)
    )
    script = _PromptScript(
        [
            "Bootstrap (first-time login)",
            "Alex",
            "",  # blank tz → auto-detect
            True,
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_auth.run_auth_menu(_make_ctx())
    assert route.call_count == 1
    body = json.loads(route.calls.last.request.content)
    assert body["timezone"] == "America/Lima"


def test_bootstrap_aborted(bootstrapped_config, monkeypatch):
    script = _PromptScript(
        [
            "Bootstrap (first-time login)",
            "Alex",
            "America/Lima",
            False,  # decline confirm
            "",  # pause after Aborted.
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_auth.run_auth_menu(_make_ctx())
    # If respx isn't active, any HTTP call would fail outright; the menu
    # must not reach the network. No respx.mock decorator on purpose.


@respx.mock
def test_update_display_name_round_trip(bootstrapped_config, monkeypatch):
    updated = {**BOOTSTRAP_RESPONSE["user"], "display_name": "Alex Tern"}
    route = respx.put("https://api.example.com/v1/auth/profile").mock(
        return_value=httpx.Response(200, json=updated)
    )
    script = _PromptScript(
        [
            "Update display name",
            "Alex Tern",
            True,  # confirm
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_auth.run_auth_menu(_make_ctx())
    assert route.call_count == 1
    body = json.loads(route.calls.last.request.content)
    assert body == {"display_name": "Alex Tern"}


def test_update_display_name_aborted(bootstrapped_config, monkeypatch):
    script = _PromptScript(
        [
            "Update display name",
            "Alex Tern",
            False,  # decline confirm
            "",  # pause after Aborted.
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_auth.run_auth_menu(_make_ctx())


@respx.mock
def test_update_settings_theme(bootstrapped_config, monkeypatch):
    updated_settings = {**BOOTSTRAP_RESPONSE["settings"], "theme": 1}
    route = respx.put("https://api.example.com/v1/auth/settings").mock(
        return_value=httpx.Response(200, json=updated_settings)
    )
    script = _PromptScript(
        [
            "Update settings…",
            "Theme",
            "1",
            True,  # confirm
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_auth.run_auth_menu(_make_ctx())
    assert route.call_count == 1
    body = json.loads(route.calls.last.request.content)
    assert body == {"theme": 1}


@respx.mock
def test_update_settings_sidebar_bool(bootstrapped_config, monkeypatch):
    updated_settings = {**BOOTSTRAP_RESPONSE["settings"], "sidebar_show_people": False}
    route = respx.put("https://api.example.com/v1/auth/settings").mock(
        return_value=httpx.Response(200, json=updated_settings)
    )
    script = _PromptScript(
        [
            "Update settings…",
            "Sidebar — show people",
            False,  # yes/no answer for "Show people?"
            True,  # confirm
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_auth.run_auth_menu(_make_ctx())
    assert route.call_count == 1
    body = json.loads(route.calls.last.request.content)
    assert body == {"sidebar_show_people": False}


def test_update_settings_inner_back(bootstrapped_config, monkeypatch):
    script = _PromptScript(
        [
            "Update settings…",
            "← Back",  # inner picker back
            "← Back",  # outer back
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_auth.run_auth_menu(_make_ctx())


@respx.mock
def test_main_currency_change_confirmed(bootstrapped_config, monkeypatch, capsys):
    updated_settings = {
        **BOOTSTRAP_RESPONSE["settings"],
        "main_currency": "PEN",
        "recalculation": {
            "regular_transactions": 142,
            "transfer_transactions": 6,
            "orphan_transfer_legs": 0,
            "inbox_items": 3,
            "total": 151,
        },
    }
    route = respx.put("https://api.example.com/v1/auth/settings").mock(
        return_value=httpx.Response(200, json=updated_settings)
    )
    script = _PromptScript(
        [
            "Update main currency",
            "PEN",
            True,  # confirm_destructive
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_auth.run_auth_menu(_make_ctx())
    assert route.call_count == 1
    body = json.loads(route.calls.last.request.content)
    assert body == {"main_currency": "PEN"}

    cfg = config_module.load()
    assert cfg is not None
    assert cfg.main_currency == "PEN"

    out = capsys.readouterr().out
    assert "Rewrote 151 transaction(s) in home currency." in out
    # No orphans in this fixture → no warning line.
    assert "need attention" not in out


def test_main_currency_change_declined(bootstrapped_config, monkeypatch):
    script = _PromptScript(
        [
            "Update main currency",
            "PEN",
            False,  # decline destructive confirm
            "",  # pause after Aborted.
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_auth.run_auth_menu(_make_ctx())
    cfg = config_module.load()
    assert cfg is not None
    assert cfg.main_currency != "PEN"  # unchanged
