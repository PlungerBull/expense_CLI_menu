"""The `?` overlay — one curated inventory of what the current screen can do.

Why this exists rather than Textual's own `action_show_help_panel`: that panel
lists every *active* binding, which means everything we never authored (Scroll
Left/Right, Page Left/Right, Focus Next/Previous, Copy selected text), renders
`show=False` aliases as rows with a blank description, groups nothing, and docks
right — squeezing the content to a third of the width. Both are captured side by
side in docs/mockups/expense-world-phase8-discoverability.html §1.2 and §2; this
card is variant C, approved 2026-08-17.

The inventory is **derived, never hand-listed**. It walks the screen's — and the
focused widget's — MRO and keeps only the BINDINGS declared by classes in this
package, so a binding added or removed anywhere shows up here with no edit. The
two hand-written blocks are the ones no walk can produce: `CONVENTIONS` (true
across screens, so no single screen declares them) and `EVERYWHERE` (Textual's
own keys). tests/unit/test_tui_help.py is the guard — it fails if a binding we
declare has no description for this card to show.
"""

from dataclasses import dataclass, field

from rich.console import Group as RichGroup
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.keys import format_key, key_to_character
from textual.screen import ModalScreen
from textual.widgets import Footer, Static

from expense.tui.theme import EXPENSE_DARK

#: Only BINDINGS declared by classes under this package reach the card. Textual's
#: own widget keys are not ours to document — see the module docstring.
PACKAGE = "expense.tui"

#: A `show=False` binding whose action is the inverse of a shown one needs no row
#: of its own: it renders as a dim parenthetical on its partner's row
#: (`j / ↓   Down   (k / ↑ up)`). Textual's panel prints it as a row with a blank
#: description instead — the `↑ k` row in the §1.2 capture. Maps folded action →
#: the action whose row it joins.
FOLD_INTO = {"move(-1)": "move(1)"}

#: Cross-screen rules from docs/tui-plan.md §4.1. No screen declares them, so no
#: walk can find them — and they are the one thing a generated key list can never
#: say. Rendered inline (key immediately before the text), not in a key column.
CONVENTIONS = (
    ("r", "refreshes, everywhere"),
    ("y", "alone confirms"),
    ("⏎", "never changes data"),
)

#: Textual's own keys, and all that is left app-wide since the command palette
#: was removed 2026-08-17 (docs/decisions.md, "The command palette is removed").
EVERYWHERE = (("^q", "Quit"), ("?", "This help"))

#: `?` is declared on every screen root (Textual does not merge BINDINGS from a
#: plain mixin, so `HelpBindingMixin.BINDINGS` has to be splatted in), which means
#: the walk finds it as a screen binding. It belongs in EVERYWHERE, not in the
#: screen's own block — drop it there rather than print it twice.
EXCLUDED_ACTIONS = frozenset({"help"})

#: Widget bindings that only do something when the *screen* handles the message
#: they post. `CursorList`'s `enter` posts `Selected`; on the Manage lists no
#: screen handles it, because the keymap contract makes `enter` a literal no-op
#: there (docs/tui-plan.md §4.1). Advertising `⏎ Open` on those screens would be
#: the card lying — so the row is dropped when the handler is absent.
NEEDS_SCREEN_HANDLER = {"select": "on_cursor_list_selected"}

#: Card geometry. `#modal` is 72 wide with `padding: 1 2` and a border, leaving 66
#: interior columns; the split matches the approved mockup.
LEFT_WIDTH = 34
RIGHT_WIDTH = 32


@dataclass(frozen=True)
class KeyRow:
    """One line of the card: the keys, what they do, and an optional fold."""

    keys: str
    description: str
    note: str = ""


@dataclass(frozen=True)
class HelpGroup:
    """A titled block. `inline` renders the key against the text rather than in
    its own column — used by the conventions block, whose entries read as
    sentences (`r refreshes, everywhere`) instead of key/description pairs."""

    title: str
    rows: tuple[KeyRow, ...] = field(default_factory=tuple)
    inline: bool = False


# ---------------------------------------------------------------------------
# deriving the inventory
# ---------------------------------------------------------------------------


def _is_typed_character(key: str) -> bool:
    """True for keys the user produces by typing a visible character.

    Drives display order — `j / ↓` and `. / pgdn` read better than the reverse,
    because the letter is what you actually press. `escape` is excluded here on
    purpose: it maps to \\x1b, a character but not a visible one.
    """
    char = key_to_character(key)
    return bool(char) and char.isprintable() and not char.isspace()


def _display(key: str) -> str:
    """Textual's own key formatting, with `ctrl+x` shortened to `^x`."""
    return format_key(key).replace("ctrl+", "^")


def declared_bindings(klass: type) -> list[Binding]:
    """Every Binding declared by `klass` or a base of it **in this package**.

    Walks the MRO rather than reading `_bindings`, because the merged runtime
    table cannot say which class declared what — and that distinction is the
    whole filter: it is how Textual's `home`/`end`/`tab` bindings stay out
    without a suppression list that would rot.

    Bindings arrive already split per key (`"down,j"` → two Bindings), which is
    what `_grouped_rows` re-joins into one row.
    """
    seen: set[tuple[str, str]] = set()
    found: list[Binding] = []
    for base in klass.__mro__:
        if not base.__module__.startswith(PACKAGE):
            continue
        for item in base.__dict__.get("BINDINGS", ()):
            for binding in Binding.make_bindings([item]):
                ident = (binding.key, binding.action)
                if ident in seen:
                    continue
                seen.add(ident)
                found.append(binding)
    return found


def _tail_rank(action: str) -> int:
    """Refresh, then Back, sort to the end of a screen's own block — they are
    the two every screen has, so leading with them would bury what is specific
    to this one."""
    if action == "reload":
        return 1
    if action in ("app.pop_screen", "back"):
        return 2
    return 0


def key_rows(bindings: list[Binding], drop: frozenset[str] = frozenset()) -> list[KeyRow]:
    """Bindings → card rows: keys re-joined, inverses folded, tail keys last."""
    order: list[str] = []
    keys_by_action: dict[str, list[str]] = {}
    described: dict[str, str] = {}
    for binding in bindings:
        if binding.action not in keys_by_action:
            keys_by_action[binding.action] = []
            order.append(binding.action)
        keys_by_action[binding.action].append(binding.key)
        # `tooltip` wins over `description`: the description is the FOOTER label
        # and is terse because footer width is scarce ("New", "Prev"), while this
        # card has room to say what the key actually does ("Next page",
        # "Archive / unarchive"). Setting a tooltip never changes the footer, so
        # the two stay independently tunable from one declaration.
        text = binding.tooltip or binding.description
        if text:
            described[binding.action] = text

    def joined(action: str) -> str:
        keys = keys_by_action[action]
        typed = [k for k in keys if _is_typed_character(k)]
        rest = [k for k in keys if k not in typed]
        return " / ".join(_display(k) for k in (*typed, *rest))

    rows: list[KeyRow] = []
    for action in sorted(order, key=_tail_rank):
        if action in EXCLUDED_ACTIONS or action in drop:
            continue
        folded_into = FOLD_INTO.get(action)
        if folded_into and folded_into in keys_by_action:
            continue  # rendered as a parenthetical on its partner's row
        note = ""
        for other, target in FOLD_INTO.items():
            if target == action and other in keys_by_action:
                note = f"({joined(other)} {described.get(other, '').lower()})".replace(" )", ")")
        rows.append(KeyRow(joined(action), described.get(action, ""), note))
    return rows


def screen_inventory(screen) -> tuple[str, list[HelpGroup]]:
    """`(title, groups)` for the screen the user is looking at.

    Called on the screen *before* `HelpModal` is pushed — once the modal is up it
    owns the focus, and the focused widget is half the answer.
    """
    crumb = getattr(screen, "crumb", ()) or ()
    # Home builds its own header instead of a Breadcrumb, so it has no crumb —
    # fall back to the class name, which reads correctly for any future
    # crumbless screen too.
    name = crumb[-1] if crumb else type(screen).__name__.removesuffix("Screen")
    title = f"Keys — {name}"

    groups = [HelpGroup("This screen", tuple(key_rows(declared_bindings(type(screen)))))]

    focused = getattr(screen, "focused", None)
    if focused is not None and focused is not screen:
        inert = frozenset(
            action
            for action, handler in NEEDS_SCREEN_HANDLER.items()
            if not hasattr(screen, handler)
        )
        widget_rows = key_rows(declared_bindings(type(focused)), drop=inert)
        if widget_rows:
            groups.append(HelpGroup("Moving around", tuple(widget_rows)))

    groups.append(
        HelpGroup(
            "Always true",
            tuple(KeyRow(key, text) for key, text in CONVENTIONS),
            inline=True,
        )
    )
    groups.append(HelpGroup("Everywhere", tuple(KeyRow(key, text) for key, text in EVERYWHERE)))
    return title, groups


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def _accent(app) -> str:
    """The running theme's accent, for a Rich style. Same reasoning as
    `resolve_palette`: read the authored Theme field, not the HSL-roundtripped
    `theme_variables` shade. Falls back to our own theme's, never to a literal."""
    theme = getattr(app, "current_theme", None)
    return getattr(theme, "accent", None) or EXPENSE_DARK.accent


def _render_group(group: HelpGroup, width: int, accent: str, pad_to: int) -> RichGroup:
    """One titled block, padded to `pad_to` rows so the block beneath it starts
    on the same line as its opposite number in the other column."""
    table = Table(box=None, show_header=False, pad_edge=False, padding=(0, 0), width=width)
    if group.inline:
        table.add_column("line", width=width)
        for row in group.rows:
            line = Text("  ")
            line.append(row.keys, style=accent)
            line.append(f" {row.description}")
            table.add_row(line)
    else:
        # Sized to the widest key string rather than a constant: `. / pgdn` is
        # three cells wider than `esc`, and a fixed column either clipped the
        # page keys or wasted a third of the narrow column on the screen block.
        key_width = max((len(row.keys) for row in group.rows), default=0) + 4
        table.add_column("keys", no_wrap=True, width=key_width)
        table.add_column("what", width=width - key_width)
        for row in group.rows:
            keys = Text("  ")
            keys.append(row.keys, style=accent)
            what = Text(row.description)
            if row.note:
                what.append(f"   {row.note}", style="dim")
            table.add_row(keys, what)
    for _ in range(pad_to - len(group.rows)):
        table.add_row(*([Text("")] * len(table.columns)))
    return RichGroup(Text(f" {group.title}", style=f"bold {accent}"), table, Text(""))


def render_card(groups: list[HelpGroup], accent: str) -> Table:
    """The two-column card. Left stack gets the screen's own keys and the
    conventions; right stack the focused widget's and the app-wide keys — the
    pairing approved as variant C."""
    left = [g for g in groups if g.title in ("This screen", "Always true")]
    right = [g for g in groups if g.title in ("Moving around", "Everywhere")]

    # Blocks are paired by position, so block 2 of each column starts on the same
    # line however many keys block 1 happened to have.
    heights = [
        max(len(stack[i].rows) if i < len(stack) else 0 for stack in (left, right))
        for i in range(max(len(left), len(right)))
    ]

    def stack(groups_: list[HelpGroup], width: int) -> RichGroup:
        return RichGroup(
            *[_render_group(g, width, accent, heights[i]) for i, g in enumerate(groups_)]
        )

    outer = Table(box=None, show_header=False, pad_edge=False, padding=(0, 0))
    outer.add_column("left", width=LEFT_WIDTH)
    outer.add_column("right", width=RIGHT_WIDTH)
    outer.add_row(stack(left, LEFT_WIDTH), stack(right, RIGHT_WIDTH))
    return outer


class HelpModal(ModalScreen):
    """The `?` card. Dismissed by `?` as well as `esc` — the key that opens it
    is the key that closes it, so it works as a peek."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("question_mark", "close", "Close"),
    ]

    def __init__(self, title: str, groups: list[HelpGroup]) -> None:
        super().__init__()
        self._title = title
        self._groups = groups

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(Text(self._title), classes="modal-title"),
            Static(render_card(self._groups, _accent(self.app))),
            Static(Text("[?] or [esc] close", style="dim")),
            id="modal",
        )
        yield Footer()

    def action_close(self) -> None:
        self.dismiss(None)


class HelpBindingMixin:
    """Adds `?` to a screen. Mixed into the three screen roots that are not
    forms or modals — `SectionScreen`, `HomeScreen`, `ReconciliationDetailScreen`.

    Deliberately not bound on the App: letters bubble up from lists, so an
    app-level `?` would fire from inside a ConfirmModal (the same reason there is
    no app-level `q` — see app.py). Deliberately not on `FormScreen` either: a
    focused `Input` swallows printable keys, so `?` there types a question mark,
    which is the wanted behaviour (decided 2026-08-17).
    """

    BINDINGS = [("question_mark", "help", "Keys")]

    def action_help(self) -> None:
        title, groups = screen_inventory(self)
        self.app.push_screen(HelpModal(title, groups))
