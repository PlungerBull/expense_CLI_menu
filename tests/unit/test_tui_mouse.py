"""Guard: `expense world` launches keyboard-only (mouse disabled).

`run_test()` uses the headless driver and bypasses the real `.run()`, so the
convention has to be locked by exercising `run_world` directly and asserting the
launch kwargs. See docs/decisions.md for why the TUI is keyboard-only.
"""

from expense.tui import app as tui_app


def test_world_launches_with_mouse_disabled(monkeypatch):
    seen = {}
    monkeypatch.setattr(tui_app.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(tui_app.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(tui_app, "get_verbose", lambda ctx: False)
    monkeypatch.setattr(tui_app, "get_no_cache", lambda ctx: False)
    monkeypatch.setattr(tui_app.ExpenseApp, "run", lambda self, **kw: seen.update(kw))
    tui_app.run_world(ctx=None)
    assert seen == {"mouse": False}
