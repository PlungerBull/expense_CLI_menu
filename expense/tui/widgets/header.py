"""Shared header widgets."""

from rich.console import RenderableType
from rich.text import Text
from textual.widgets import Static


class Breadcrumb(Static):
    """`◈ EXPENSE WORLD ▸ Group ▸ Section` trail shown atop every section screen.

    The last crumb is the current screen (emphasized). Colors come from the
    `#crumb` CSS rule so a theme swap restyles it.
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
        return text
