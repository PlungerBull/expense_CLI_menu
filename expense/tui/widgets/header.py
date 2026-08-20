"""Shared header widgets."""

from rich.console import RenderableType
from rich.text import Text
from textual.widgets import Static

from expense.tui.theme import PALETTE, Palette

#: The whole indicator. Deliberately one character: it reports that a number
#: elsewhere may be slightly off, which does not deserve a sentence in a header
#: that is otherwise navigation. `Rates` on the home menu is where you go to
#: see what is actually stored.
RATE_ALERT_MARK = "!"

#: Gap between the header's own content and the mark. Both hosts use it so the
#: indicator sits in the same place on every screen. Kept narrow deliberately:
#: the home header truncates rather than wraps (`no_wrap`), and on an 80-column
#: terminal with a full stat cluster every column spent here comes out of the
#: wordmark.
RATE_ALERT_GAP = "  "


def rate_alert(stale: bool | None, palette: Palette | None = None) -> Text:
    """The exchange-rate staleness marker, or empty text.

    `stale` is `App.rate_stale`: True when today has no exchange rate of its own
    and every home-currency figure is being priced at an older day's rate.
    False (fresh) and None (not yet known — pre-fetch, offline, unconfigured)
    both render nothing. **None must stay silent**: an indicator that fires when
    it cannot reach the engine is reporting on the connection, not on the rate,
    and one that cries wolf gets ignored on the day it is right.

    Warning-colored, not error-colored: carried-forward rates are the engine's
    designed fallback and the figures stay roughly right, so this is "look at
    this when convenient", not "something is broken".

    Pure so both header hosts can share it — the breadcrumb trail on section
    screens and the home screen's Rich header grid, which are built too
    differently to share a widget.
    """
    if not stale:
        return Text("")
    return Text(RATE_ALERT_MARK, style=palette.warning if palette else "bold")


class Breadcrumb(Static):
    """`◈ EXPENSE WORLD ▸ Group ▸ Section` trail shown atop every section screen.

    The last crumb is the current screen (emphasized). Colors come from the
    `#crumb` CSS rule so a theme swap restyles it.

    The rate alert is appended at the end of the trail. It reads `app.rate_stale`
    at render time rather than being passed in, so a screen pushed after the
    app's one startup fetch shows the right thing with no wiring of its own; the
    app refreshes mounted breadcrumbs when the value lands.
    """

    def __init__(self, trail: tuple[str, ...] = (), *, id: str | None = None) -> None:
        super().__init__("", id=id)
        self._trail = tuple(trail)

    def set_trail(self, trail: tuple[str, ...]) -> None:
        self._trail = tuple(trail)
        self.refresh()

    def render(self) -> RenderableType:
        text = Text("◈ EXPENSE WORLD", style="bold")
        last = len(self._trail) - 1
        for i, part in enumerate(self._trail):
            text.append("  ▸  ")
            text.append(part, style="bold" if i == last else "")

        app = _app(self)
        alert = rate_alert(getattr(app, "rate_stale", None), PALETTE)
        if alert.plain:
            text.append(RATE_ALERT_GAP)
            text.append_text(alert)
        return text


def _app(widget):
    """The running app, or None when there isn't one.

    `Widget.app` raises `NoActiveAppError` rather than returning None, so a
    plain `getattr(..., default)` does not cover it — the default only catches
    `AttributeError`. Unmounted rendering is a real case (the unit tests do
    exactly this), and a header must degrade to silence, never to a traceback.
    """
    try:
        return widget.app
    except Exception:
        return None
