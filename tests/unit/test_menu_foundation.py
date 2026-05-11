"""Step 9.5.1 — menu foundation.

Covers the TTY guard, root-loop quit semantics, the placeholder stubs,
Ctrl-C handling, and the shared prompt helpers (`pick_account`,
`confirm_destructive`). No HTTP calls — questionary and cache reads are
both monkeypatched, matching the pattern in `test_cmd_*.py`.
"""

from typer.testing import CliRunner

from expense.__main__ import app
from expense.menu import app as menu_app
from expense.menu import prompts

runner = CliRunner()


class _FakeAsk:
    """Minimal stand-in for `questionary.select(...)` / `.checkbox(...)`."""

    def __init__(self, answer):
        self._answer = answer

    def ask(self):
        if isinstance(self._answer, BaseException):
            raise self._answer
        return self._answer


def _make_select_factory(answers):
    """Returns a factory whose successive calls pop from `answers`."""
    queue = list(answers)

    def _factory(*_args, **_kwargs):
        return _FakeAsk(queue.pop(0))

    return _factory


# ----------------------------------------------------------------- TTY guard

# CliRunner replaces sys.stdin/sys.stdout with non-TTY streams during invoke,
# so `_require_tty` fires naturally — no monkeypatch needed for the guard
# tests. Loop tests bypass the guard via `_no_tty_guard`.


def test_menu_exits_when_stdin_is_not_a_tty():
    result = runner.invoke(app, ["menu"])
    assert result.exit_code == 1
    combined = (result.stderr or "") + (result.output or "")
    assert "interactive terminal" in combined


# ----------------------------------------------------------------- Root loop


def _no_tty_guard(monkeypatch):
    monkeypatch.setattr(menu_app, "_require_tty", lambda: None)


def test_root_menu_quits_cleanly_on_quit(monkeypatch):
    _no_tty_guard(monkeypatch)
    monkeypatch.setattr(menu_app.questionary, "select", _make_select_factory(["Quit"]))
    result = runner.invoke(app, ["menu"])
    assert result.exit_code == 0


def test_root_menu_quits_cleanly_on_none(monkeypatch):
    """questionary returns None when the user types `q` or aborts a prompt."""
    _no_tty_guard(monkeypatch)
    monkeypatch.setattr(menu_app.questionary, "select", _make_select_factory([None]))
    result = runner.invoke(app, ["menu"])
    assert result.exit_code == 0


def test_root_menu_handles_ctrl_c(monkeypatch):
    _no_tty_guard(monkeypatch)
    monkeypatch.setattr(menu_app.questionary, "select", _make_select_factory([KeyboardInterrupt()]))
    result = runner.invoke(app, ["menu"])
    assert result.exit_code == 0


def test_stub_placeholder_advertises_correct_phase(monkeypatch):
    _no_tty_guard(monkeypatch)
    # Pick a group that is still unwired (Transactions ships in 9.5.4).
    monkeypatch.setattr(
        menu_app.questionary, "select", _make_select_factory(["Transactions", "Quit"])
    )
    result = runner.invoke(app, ["menu"])
    assert result.exit_code == 0
    assert "not yet wired" in result.output
    assert "9.5.4" in result.output


def test_every_group_advertises_its_phase():
    """Every root-menu group has a phase mapping (no silent omissions)."""
    expected = {
        "Log a transaction",
        "Inbox",
        "Transactions",
        "Dashboard",
        "Reports",
        "Reconciliations",
        "Accounts",
        "Categories",
        "Hashtags",
        "Sync",
        "Activity log",
        "Exchange rates",
        "Auth & profile",
        "Config",
    }
    assert set(menu_app._GROUP_PHASES) == expected


# ------------------------------------------------------------- pick_account


def test_pick_account_returns_chosen_id(monkeypatch):
    accounts = [
        {"id": "11111111-1111-1111-1111-111111111111", "name": "Checking"},
        {"id": "22222222-2222-2222-2222-222222222222", "name": "Savings"},
    ]
    monkeypatch.setattr(prompts.queries, "list_accounts", lambda **_k: accounts)
    monkeypatch.setattr(
        prompts.questionary,
        "select",
        _make_select_factory(["11111111-1111-1111-1111-111111111111"]),
    )
    result = prompts.pick_account()
    assert result == "11111111-1111-1111-1111-111111111111"


def test_pick_account_returns_back_when_cache_empty(monkeypatch, capsys):
    monkeypatch.setattr(prompts.queries, "list_accounts", lambda **_k: [])
    result = prompts.pick_account()
    assert result is prompts.BACK
    captured = capsys.readouterr()
    assert "No accounts found" in captured.err
    assert "expense sync --full" in captured.err


def test_pick_account_returns_back_when_user_aborts(monkeypatch):
    accounts = [{"id": "11111111-1111-1111-1111-111111111111", "name": "Checking"}]
    monkeypatch.setattr(prompts.queries, "list_accounts", lambda **_k: accounts)
    monkeypatch.setattr(prompts.questionary, "select", _make_select_factory([None]))
    result = prompts.pick_account()
    assert result is prompts.BACK


# --------------------------------------------------------- confirm_destructive


def test_confirm_destructive_yes(monkeypatch):
    monkeypatch.setattr(prompts.questionary, "select", _make_select_factory([True]))
    assert prompts.confirm_destructive("Delete it?", warning="This is permanent.") is True


def test_confirm_destructive_no(monkeypatch):
    monkeypatch.setattr(prompts.questionary, "select", _make_select_factory([False]))
    assert prompts.confirm_destructive("Delete it?") is False


def test_confirm_destructive_aborted_returns_false(monkeypatch):
    monkeypatch.setattr(prompts.questionary, "select", _make_select_factory([None]))
    assert prompts.confirm_destructive("Delete it?") is False
