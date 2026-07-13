"""Guard: `expense world` launch conventions — keyboard-only (mouse disabled)
and the screen+scrollback clear before Textual takes over.

`run_test()` uses the headless driver and bypasses the real `.run()`, so the
conventions have to be locked by exercising `run_world` directly and asserting
the launch kwargs / emitted control sequences. See docs/decisions.md for why
the TUI is keyboard-only and why launch wipes the scrollback.
"""

from expense.tui import app as tui_app


def _launch(monkeypatch, seen: dict) -> None:
    monkeypatch.setattr(tui_app.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(tui_app.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(tui_app, "get_verbose", lambda ctx: False)
    monkeypatch.setattr(tui_app, "get_no_cache", lambda ctx: False)
    monkeypatch.setattr(tui_app.ExpenseApp, "run", lambda self, **kw: seen.update(kw))
    tui_app.run_world(ctx=None)


def test_world_launches_with_mouse_disabled(monkeypatch):
    seen = {}
    _launch(monkeypatch, seen)
    assert seen == {"mouse": False}


def test_world_clears_screen_and_scrollback_first(monkeypatch, capsys):
    """Launch emits CSI 2J (clear screen) + 3J (clear scrollback) + H (home):
    with the mouse off, terminal-level scrolling would otherwise reveal
    pre-launch scrollback above the running app (picked 2026-07-13)."""
    _launch(monkeypatch, seen={})
    assert capsys.readouterr().out == "\x1b[2J\x1b[3J\x1b[H"
