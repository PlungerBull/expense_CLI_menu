"""Step 9.5.6 — menu-driven Config flows.

Covers show / set-engine-url / set-token / set-main-currency / clear,
plus the freshman first-run guards (set-token / set-main-currency before
engine URL is set). Local file I/O only — no engine, no cache, no respx.
"""

from uuid import uuid4

import pytest

from expense import config as config_module
from expense.config import Config
from expense.menu import prompts
from expense.menu.groups import _common as menu_common
from expense.menu.groups import config as menu_config


@pytest.fixture
def no_config(tmp_path, monkeypatch):
    """EXPENSE_CONFIG points at a temp path, but no file written."""
    config_path = tmp_path / "config.json"
    monkeypatch.setenv("EXPENSE_CONFIG", str(config_path))
    monkeypatch.setenv("EXPENSE_STATELESS", "1")
    yield config_path


@pytest.fixture
def partial_config(tmp_path, monkeypatch):
    """Config exists with engine_url only — token and main_currency unset."""
    config_path = tmp_path / "config.json"
    monkeypatch.setenv("EXPENSE_CONFIG", str(config_path))
    config_module.save(Config(engine_url="https://api.example.com", client_id=uuid4(), token=None))
    monkeypatch.setenv("EXPENSE_STATELESS", "1")
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
    for mod in (menu_common, menu_config, prompts):
        monkeypatch.setattr(mod.questionary, "text", script)
        monkeypatch.setattr(mod.questionary, "select", script)
    monkeypatch.setattr(menu_common.questionary, "password", script)


class _StubCtx:
    def __init__(self):
        from expense.context import AppContext

        self.obj = AppContext(verbose=False, no_cache=True, no_sync_after=True)


def _make_ctx() -> _StubCtx:
    return _StubCtx()


# ----- validator unit tests (run synchronously inside questionary in prod) -----


def test_engine_url_validator():
    assert menu_config._validate_engine_url("") != True  # noqa: E712
    assert menu_config._validate_engine_url("   ") != True  # noqa: E712
    assert menu_config._validate_engine_url("not-a-url") != True  # noqa: E712
    assert menu_config._validate_engine_url("ftp://example.com") != True  # noqa: E712
    assert menu_config._validate_engine_url("http://localhost:8000") is True
    assert menu_config._validate_engine_url("https://api.example.com") is True


def test_currency_code_validator():
    assert menu_common.validate_currency_code("") != True  # noqa: E712
    assert menu_common.validate_currency_code("usd") != True  # noqa: E712
    assert menu_common.validate_currency_code("US") != True  # noqa: E712
    assert menu_common.validate_currency_code("USDT") != True  # noqa: E712
    assert menu_common.validate_currency_code("US1") != True  # noqa: E712
    assert menu_common.validate_currency_code("USD") is True
    assert menu_common.validate_currency_code("PEN") is True


# ----- flow tests -----


def test_back_exits_cleanly(no_config, monkeypatch):
    script = _PromptScript(["← Back"])
    _patch_questionary(monkeypatch, script)
    menu_config.run_config_menu(_make_ctx())
    assert not no_config.exists()


def test_show_no_config_surfaces_error(no_config, monkeypatch, capsys):
    script = _PromptScript(
        [
            "Show current config",
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_config.run_config_menu(_make_ctx())
    combined = capsys.readouterr()
    assert "No config" in (combined.out + combined.err)


def test_show_with_partial_config_renders_redacted(partial_config, monkeypatch, capsys):
    script = _PromptScript(
        [
            "Show current config",
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_config.run_config_menu(_make_ctx())
    out = capsys.readouterr().out
    assert "engine_url" in out
    assert "https://api.example.com" in out
    assert "token" in out
    assert "(not set)" in out  # token is None — rendered as "(not set)"


def test_set_engine_url_writes_file(no_config, monkeypatch):
    script = _PromptScript(
        [
            "Set engine URL",
            "https://api.example.com",
            True,  # confirm save
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_config.run_config_menu(_make_ctx())
    cfg = config_module.load()
    assert cfg is not None
    assert cfg.engine_url == "https://api.example.com"
    assert cfg.token is None


def test_set_engine_url_aborted_writes_nothing(no_config, monkeypatch):
    script = _PromptScript(
        [
            "Set engine URL",
            "https://api.example.com",
            False,  # decline confirm
            "",  # pause after Aborted.
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_config.run_config_menu(_make_ctx())
    assert not no_config.exists()


def test_set_token_writes_to_existing_config(partial_config, monkeypatch):
    script = _PromptScript(
        [
            "Set token (PAT)",
            "ewe_pat_xxxxx",
            True,  # confirm save
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_config.run_config_menu(_make_ctx())
    cfg = config_module.load()
    assert cfg is not None
    assert cfg.token == "ewe_pat_xxxxx"
    assert cfg.engine_url == "https://api.example.com"  # unchanged


def test_set_token_without_engine_url_shows_hint(no_config, monkeypatch, capsys):
    script = _PromptScript(
        [
            "Set token (PAT)",
            "",  # pause after hint
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_config.run_config_menu(_make_ctx())
    combined = capsys.readouterr()
    assert "Set engine URL first" in (combined.out + combined.err)
    assert not no_config.exists()


def test_set_main_currency_writes_to_existing_config(partial_config, monkeypatch):
    script = _PromptScript(
        [
            "Set main currency (local default)",
            "USD",
            True,  # confirm
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_config.run_config_menu(_make_ctx())
    cfg = config_module.load()
    assert cfg is not None
    assert cfg.main_currency == "USD"


def test_set_main_currency_without_engine_url_shows_hint(no_config, monkeypatch, capsys):
    script = _PromptScript(
        [
            "Set main currency (local default)",
            "",  # pause after hint
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_config.run_config_menu(_make_ctx())
    combined = capsys.readouterr()
    assert "Set engine URL first" in (combined.out + combined.err)


def test_clear_no_existing_file(no_config, monkeypatch, capsys):
    script = _PromptScript(
        [
            "Clear all config",
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_config.run_config_menu(_make_ctx())
    out = capsys.readouterr().out
    assert "No config file to clear" in out


def test_clear_declined_keeps_file(partial_config, monkeypatch):
    script = _PromptScript(
        [
            "Clear all config",
            False,  # confirm_destructive → No
            "",  # pause after Aborted.
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_config.run_config_menu(_make_ctx())
    assert partial_config.exists()


def test_clear_confirmed_wipes_file(partial_config, monkeypatch):
    script = _PromptScript(
        [
            "Clear all config",
            True,  # confirm_destructive → Yes
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_config.run_config_menu(_make_ctx())
    assert not partial_config.exists()


def test_keyboard_interrupt_exits(no_config, monkeypatch):
    script = _PromptScript([KeyboardInterrupt()])
    _patch_questionary(monkeypatch, script)
    menu_config.run_config_menu(_make_ctx())
    assert not no_config.exists()
