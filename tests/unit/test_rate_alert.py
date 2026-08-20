"""The exchange-rate staleness indicator — resolution, fetch, and rendering.

The header shows a `!` when today has no exchange rate of its own, so every
home-currency figure on screen is priced at an older day's rate. There is no
bespoke engine field behind it: `GET /exchange-rates` returns the day you asked
about (`date`) and the day it actually used (`rate_date`), and the whole signal
is `rate_date < date` — see engine-spec.md "Staleness: `rate_date` is the
signal". These lock the three halves that can independently rot: the comparison,
what happens on an engine error, and the render.

The property that matters most here is the *silent* one. Unknown (offline,
unconfigured, pre-fetch, unexpected shape) must render nothing at all. An
indicator that fires when it cannot reach the engine is reporting on the
connection, and one that cries wolf gets ignored on the day it is right.
"""

import asyncio
import io

import httpx
import respx
from rich.console import Console
from textual.widgets import Static

import expense.tui.screens.home as home
from expense.commands.rates_cmd import fetch_rate_staleness, rate_is_stale
from expense.tui.app import ExpenseApp
from expense.tui.theme import Palette
from expense.tui.widgets.header import RATE_ALERT_MARK, Breadcrumb, rate_alert

PALETTE = Palette(success="#7fbf8f", error="#cf8d8d", warning="#d6b878")


def _render(renderable, width=100) -> str:
    con = Console(file=io.StringIO(), width=width)
    con.print(renderable)
    return con.file.getvalue()


def _painted(widget) -> str:
    """What a mounted widget actually puts on screen, line by line.

    `Static.render()` returns a Visual wrapper in this Textual version, not the
    renderable handed to `update()`, so printing it yields a repr. Reading the
    rendered strips asserts against the real painted output instead — which is
    the point of these tests: that the mark reaches the screen.
    """
    return "\n".join(widget.render_line(y).text for y in range(widget.size.height))


# ---- rate_is_stale -------------------------------------------------------


def test_carried_forward_rate_is_stale():
    """The engine answered with an older day's row than the one asked for."""
    assert rate_is_stale({"date": "2026-08-13", "rate_date": "2026-08-11"}) is True


def test_rate_of_the_day_itself_is_fresh():
    assert rate_is_stale({"date": "2026-08-13", "rate_date": "2026-08-13"}) is False


def test_a_rate_date_ahead_of_the_asked_date_is_not_stale():
    """Asking about a past date returns that date's own row or earlier, never a
    later one — but if it ever did, "ahead" is not staleness."""
    assert rate_is_stale({"date": "2026-08-01", "rate_date": "2026-08-13"}) is False


def test_missing_or_wrong_typed_dates_are_unknown_not_stale():
    """A shape change must go quiet rather than light the header permanently."""
    assert rate_is_stale({"date": "2026-08-13"}) is None
    assert rate_is_stale({"rate_date": "2026-08-13"}) is None
    assert rate_is_stale({}) is None
    assert rate_is_stale({"date": "2026-08-13", "rate_date": None}) is None


# ---- fetch_rate_staleness ------------------------------------------------


@respx.mock
def test_fetch_reports_stale_from_a_carried_forward_response(configured):
    from expense import config as config_module

    respx.get("https://api.example.com/v1/exchange-rates").mock(
        return_value=httpx.Response(
            200,
            json={
                "base": "USD",
                "target": "PEN",
                "date": "2026-08-13",
                "rate_date": "2026-08-11",
                "rate": 3.37,
            },
        )
    )
    assert fetch_rate_staleness(config_module.ensure_loaded(), target="PEN") is True


@respx.mock
def test_no_rate_at_all_counts_as_stale(configured):
    """404 is the same condition at its extreme — nothing on or before today."""
    from expense import config as config_module

    respx.get("https://api.example.com/v1/exchange-rates").mock(
        return_value=httpx.Response(
            404,
            json={"error": {"code": "NOT_FOUND", "message": "no rate", "fields": None}},
        )
    )
    assert fetch_rate_staleness(config_module.ensure_loaded(), target="PEN") is True


@respx.mock
def test_other_engine_errors_are_unknown_not_stale(configured):
    """A 422 is a question about the request, not an answer about the rate."""
    from expense import config as config_module

    respx.get("https://api.example.com/v1/exchange-rates").mock(
        return_value=httpx.Response(
            422,
            json={"error": {"code": "VALIDATION_ERROR", "message": "bad", "fields": {}}},
        )
    )
    assert fetch_rate_staleness(config_module.ensure_loaded(), target="XXX") is None


# ---- rate_alert ----------------------------------------------------------


def test_alert_renders_the_mark_when_stale():
    text = rate_alert(True, PALETTE)
    assert text.plain == RATE_ALERT_MARK


def test_alert_takes_the_pending_style_from_the_palette():
    """Warning, not error: a carried-forward rate is the engine's designed
    fallback, so the figures are roughly right. Palette-sourced, never a literal
    style — the no-literal-color guard in test_tui_theme.py depends on it.

    The emphasis now lives in the palette, not here: pick C (2026-08-19) made the
    pending role `bold` with no colour, so a call site that prepended its own
    "bold " would render "bold bold". Asserted with the REAL palette, since the
    synthetic one above is a colour triple from before that change.
    """
    from expense.tui.theme import FALLBACK

    assert str(rate_alert(True, PALETTE).style) == PALETTE.warning  # palette-sourced
    assert str(rate_alert(True, FALLBACK).style) == "bold"  # ...and it is emphasis


def test_alert_is_empty_when_fresh_or_unknown():
    assert rate_alert(False, PALETTE).plain == ""
    assert rate_alert(None, PALETTE).plain == ""


def test_alert_renders_without_a_palette():
    """Breadcrumb falls back to no palette outside a running app."""
    assert rate_alert(True, None).plain == RATE_ALERT_MARK


# ---- the two header hosts ------------------------------------------------


def test_home_header_shows_the_mark_beside_the_stat_cluster():
    stats = {"net": 480000, "spent": 320000, "owed": 0}
    out = _render(home._build_header(stats, PALETTE, True))
    assert RATE_ALERT_MARK in out
    assert "4,800.00" in out, "the alert must not displace the stats"


def test_home_header_is_unmarked_when_fresh_or_unknown():
    stats = {"net": 480000, "spent": 320000, "owed": 0}
    for state in (False, None):
        out = _render(home._build_header(stats, PALETTE, state))
        assert RATE_ALERT_MARK not in out, state


def test_home_header_shows_the_mark_with_no_stats_yet():
    """The two fetches race; the alert must not need the dashboard to have landed."""
    assert RATE_ALERT_MARK in _render(home._build_header(None, PALETTE, True))


def test_breadcrumb_outside_an_app_renders_the_trail_and_no_mark():
    """`self.app` raises when unmounted, so the widget must degrade to silence
    rather than to a traceback — this is also what lets it be unit-tested."""
    out = _render(Breadcrumb(("System", "Rates")).render())
    assert "System" in out and "Rates" in out
    assert RATE_ALERT_MARK not in out


# ---- the app wiring, end to end ------------------------------------------
#
# The two tests above cover the render given a value; these cover the value
# reaching the render. That wiring is the part that rots silently — a screen
# pushed after the startup fetch reads `app.rate_stale` itself, while one
# already on screen has to be told, and those are two different code paths.


def test_breadcrumb_mounted_in_the_app_follows_rate_stale():
    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            crumb = Breadcrumb(("System", "Rates"))
            await app.screen.mount(crumb)
            await pilot.pause()

            # Unconfigured in tests, so the startup fetch bails and leaves None.
            assert app.rate_stale is None
            assert RATE_ALERT_MARK not in _painted(crumb)

            app._set_rate_stale(True)
            await pilot.pause()
            assert RATE_ALERT_MARK in _painted(crumb)

    asyncio.run(scenario())


def test_home_header_repaints_when_the_rate_status_lands():
    """The `repaint_header` hook. Home builds its own header instead of using
    Breadcrumb, so the app's blanket breadcrumb refresh does not reach it — and
    home is the first screen you see, so missing this means the `!` only ever
    appears after navigating somewhere else."""

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            brand = app.query_one("#brand", Static)
            assert RATE_ALERT_MARK not in _painted(brand)

            app._set_rate_stale(True)
            await pilot.pause()
            assert RATE_ALERT_MARK in _painted(brand)

    asyncio.run(scenario())


def test_startup_fetch_is_silent_without_config():
    """The TUI must stay usable offline / unconfigured — the indicator is not
    allowed to be the thing that makes launching fail or hang."""

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.rate_stale is None

    asyncio.run(scenario())
