"""Step 9.5.11b — terminal-control helper for clear-on-navigate.

Covers `expense.menu.term.clear_screen()`:
- no-op when stdout is non-TTY (the default in CliRunner-based tests)
- no-op when `EXPENSE_NO_CLEAR` is set to a truthy value
- calls `click.clear()` when TTY + env var unset
- explicit truthy parsing: falsy strings (`"0"`, `"false"`, `"no"`, `""`)
  must NOT suppress clearing
"""

import sys

import pytest

from expense.menu import term


def _make_tty(monkeypatch):
    """Force `sys.stdout.isatty()` to return True for the test."""
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)


def _track_clear(monkeypatch):
    """Replace `click.clear` with a counter and return the call-count getter."""
    calls = {"n": 0}

    def _fake_clear() -> None:
        calls["n"] += 1

    monkeypatch.setattr(term.click, "clear", _fake_clear)
    return lambda: calls["n"]


def test_clear_screen_is_noop_when_stdout_is_not_a_tty(monkeypatch):
    # CliRunner-style: stdout is non-TTY. clear_screen must not call click.clear.
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    monkeypatch.delenv("EXPENSE_NO_CLEAR", raising=False)
    n = _track_clear(monkeypatch)

    term.clear_screen()

    assert n() == 0


def test_clear_screen_is_noop_when_env_var_set(monkeypatch):
    # Even with a TTY, EXPENSE_NO_CLEAR=1 must suppress the clear.
    _make_tty(monkeypatch)
    monkeypatch.setenv("EXPENSE_NO_CLEAR", "1")
    n = _track_clear(monkeypatch)

    term.clear_screen()

    assert n() == 0


def test_clear_screen_calls_click_clear_when_tty_and_env_var_unset(monkeypatch):
    _make_tty(monkeypatch)
    monkeypatch.delenv("EXPENSE_NO_CLEAR", raising=False)
    n = _track_clear(monkeypatch)

    term.clear_screen()

    assert n() == 1


@pytest.mark.parametrize("value", ["0", "false", "no", "False", "NO", ""])
def test_falsy_env_var_values_do_not_suppress_clearing(monkeypatch, value):
    # The opt-out follows Click's bool conventions: only truthy strings
    # disable clearing. "0" / "false" / "no" / empty string must NOT.
    _make_tty(monkeypatch)
    monkeypatch.setenv("EXPENSE_NO_CLEAR", value)
    n = _track_clear(monkeypatch)

    term.clear_screen()

    assert n() == 1, f"value={value!r} should NOT suppress clearing"
