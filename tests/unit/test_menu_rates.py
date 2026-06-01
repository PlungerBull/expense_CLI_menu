"""Step 9.5.15 — menu-driven Exchange rates flows.

Covers the single submenu action (Look up a rate):
  - target-only happy path
  - target + base + date passes all three params
  - RATE_UNAVAILABLE 422 renders the standard error envelope
  - validator catches lowercase / bad-format inputs before the engine
  - BACK / Ctrl-C exit the submenu cleanly
  - validate_date_iso unit coverage (new helper)
"""

from uuid import uuid4

import httpx
import pytest
import respx

from expense import config as config_module
from expense.menu.groups import _common as menu_common
from expense.menu.groups import rates as menu_rates

RATE_RESPONSE = {
    "base": "USD",
    "target": "EUR",
    "date": "2026-05-26",
    "rate": "0.9234",
}

RATE_UNAVAILABLE_422 = {
    "error": {
        "code": "RATE_UNAVAILABLE",
        "message": "No rate on or before 2026-05-26 for USD->XOF.",
        "fields": {
            "exchange_rate": (
                "No rate on or before 2026-05-26 for USD->XOF. "
                "Wait for the daily fetch or supply an explicit "
                "exchange_rate."
            )
        },
    }
}


# ----------------------------------------------------------- fixtures


@pytest.fixture
def configured(tmp_path, monkeypatch):
    config_path = tmp_path / ".expense-config"
    monkeypatch.setenv("EXPENSE_CONFIG", str(config_path))
    monkeypatch.setenv("EXPENSE_STATELESS", "1")
    monkeypatch.setenv("EXPENSE_NO_SYNC_AFTER", "1")
    config_module.save(
        config_module.Config(
            engine_url="https://api.example.com",
            token="ewe_pat_test",
            client_id=uuid4(),
        )
    )
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
    monkeypatch.setattr(menu_rates.questionary, "select", script)
    monkeypatch.setattr(menu_rates.questionary, "text", script)


class _StubCtx:
    def __init__(self):
        from expense.context import AppContext

        self.obj = AppContext(verbose=False, no_cache=True, no_sync_after=True)


def _make_ctx() -> _StubCtx:
    return _StubCtx()


# ----------------------------------------------------------- 1. Lookup


@respx.mock
def test_lookup_target_only_happy_path(configured, monkeypatch, capsys):
    """Target only → engine called with target, base + date omitted."""
    route = respx.get("https://api.example.com/v1/exchange-rates").mock(
        return_value=httpx.Response(200, json=RATE_RESPONSE)
    )
    script = _PromptScript(
        [
            "EUR",  # target
            "",  # base (skip)
            "",  # date (skip)
            "",  # pause
        ]
    )
    _patch_questionary(monkeypatch, script)

    menu_rates.run_lookup(_make_ctx())

    assert route.call_count == 1
    params = route.calls.last.request.url.params
    assert params.get("target") == "EUR"
    assert params.get("base") is None
    assert params.get("date") is None
    out = capsys.readouterr().out
    assert "rate: 0.9234" in out
    assert "About to call:" in out
    assert "expense rates get" in out


@respx.mock
def test_lookup_with_all_three_params(configured, monkeypatch, capsys):
    """Target + base + date are all forwarded to the engine call."""
    route = respx.get("https://api.example.com/v1/exchange-rates").mock(
        return_value=httpx.Response(
            200,
            json={**RATE_RESPONSE, "base": "GBP", "date": "2026-04-01"},
        )
    )
    script = _PromptScript(
        [
            "EUR",  # target
            "GBP",  # base
            "2026-04-01",  # date
            "",  # pause
        ]
    )
    _patch_questionary(monkeypatch, script)

    menu_rates.run_lookup(_make_ctx())

    assert route.call_count == 1
    params = route.calls.last.request.url.params
    assert params.get("target") == "EUR"
    assert params.get("base") == "GBP"
    assert params.get("date") == "2026-04-01"
    out = capsys.readouterr().out
    assert "--target EUR" in out
    assert "--base GBP" in out
    assert "--date 2026-04-01" in out


# ----------------------------------------------------------- 2. Error envelope


@respx.mock
def test_lookup_rate_unavailable_renders_envelope(configured, monkeypatch, capsys):
    """422 RATE_UNAVAILABLE surfaces via the standard error envelope."""
    respx.get("https://api.example.com/v1/exchange-rates").mock(
        return_value=httpx.Response(422, json=RATE_UNAVAILABLE_422)
    )
    script = _PromptScript(
        [
            "XOF",  # target
            "",  # base (skip)
            "",  # date (skip)
            "",  # pause
        ]
    )
    _patch_questionary(monkeypatch, script)

    menu_rates.run_lookup(_make_ctx())

    out = capsys.readouterr()
    combined = out.out + out.err
    assert "RATE_UNAVAILABLE" in combined
    assert "exchange_rate" in combined


# ----------------------------------------------------------- 3. Submenu loop


@respx.mock
def test_submenu_dispatches_lookup(configured, monkeypatch):
    """Loop routes 'Look up a rate' → run_lookup, then BACK exits cleanly."""
    respx.get("https://api.example.com/v1/exchange-rates").mock(
        return_value=httpx.Response(200, json=RATE_RESPONSE)
    )
    script = _PromptScript(
        [
            "Look up a rate",  # root submenu choice
            "EUR",  # target
            "",  # base (skip)
            "",  # date (skip)
            "",  # pause
            menu_rates.BACK_LABEL,  # exit loop
        ]
    )
    _patch_questionary(monkeypatch, script)

    menu_rates.run_rates_menu(_make_ctx())

    assert script.remaining == 0


def test_submenu_back_returns_immediately(configured, monkeypatch):
    script = _PromptScript([menu_rates.BACK_LABEL])
    _patch_questionary(monkeypatch, script)
    menu_rates.run_rates_menu(_make_ctx())
    assert script.remaining == 0


def test_submenu_ctrl_c_returns(configured, monkeypatch):
    script = _PromptScript([KeyboardInterrupt()])
    _patch_questionary(monkeypatch, script)
    menu_rates.run_rates_menu(_make_ctx())  # silent return = pass


# ----------------------------------------------------------- 4. validate_date_iso


def test_validate_date_iso_accepts_canonical():
    assert menu_common.validate_date_iso("2026-05-26") is True


def test_validate_date_iso_rejects_empty():
    assert menu_common.validate_date_iso("") == "Date is required."


def test_validate_date_iso_rejects_single_digit_month():
    result = menu_common.validate_date_iso("2026-5-26")
    assert isinstance(result, str)
    assert "YYYY-MM-DD" in result


def test_validate_date_iso_rejects_slash_separator():
    result = menu_common.validate_date_iso("2026/05/26")
    assert isinstance(result, str)
    assert "YYYY-MM-DD" in result


def test_validate_date_iso_rejects_bad_month():
    """Regex passes, but date.fromisoformat raises ValueError."""
    result = menu_common.validate_date_iso("2026-13-01")
    assert isinstance(result, str)
    assert "real calendar date" in result


def test_validate_date_iso_rejects_bad_day():
    result = menu_common.validate_date_iso("2026-02-30")
    assert isinstance(result, str)
    assert "real calendar date" in result
