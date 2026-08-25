"""The LOG bar — one typed line, a staged batch, one save (phase 3: staging).

The capture surface of the quick-add item (docs/todo.md item 1), drawn in
docs/mockups/expense-world-quickadd-batch.html. You type one line, press `↵`,
and it lands in a list you can read before anything is written; `↑↓` pick a
staged row back up, `ctrl+x` drops one, `esc` confirms a discard.

**Phase 3 ships the staging half only.** `ctrl+s` is not bound and this screen
is not reachable from `+` — `action_log_transaction` still opens the bar-cycle
form, so `main` stays usable. Phase 4 adds the writes and flips that door
(docs/mockups/expense-world-two-doors.html).

The grammar is not here. Every line goes through `expense/quickadd/` — the same
module the flat `expense log "…"` calls — so the two surfaces read a line
identically and neither owns a second copy:

    parse()  what the line says, with a Span per token for colouring
    route()  ledger or Inbox, and the phrases that say why

Routing is decided **at stage time**, not at save time, and frozen onto the
staged row: what the `goes to` column says is what will happen.

Four calls this screen makes, all put to the user 2026-08-25 and recorded in
docs/decisions.md "Four calls for the LOG bar":

* a staged row comes back as **the raw line you typed**, not a re-render;
* the staged table carries the **tags** column (the batch mockup's set);
* the batch totals **per currency** — soles are never added to dollars;
* the Inbox footnote reuses **route.py's own phrases**, so there is one wording.
"""

from dataclasses import dataclass, field

from rich.console import Group, RenderableType
from rich.highlighter import Highlighter
from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Footer, Input, Label, Static

from expense.commands._resource import (
    QuickAddRefs,
    currency_of,
    format_cents,
    load_quickadd_refs,
    resolve_name,
)
from expense.dates import today_local
from expense.errors import format_error
from expense.quickadd.parse import ParsedLine, Span, Unresolved, parse
from expense.quickadd.route import Routing, describe, route
from expense.quickadd.when import format_date_words
from expense.tui.screens._base import EngineWriteMixin, screen_fetch_kwargs
from expense.tui.screens.modals import DiscardStagedModal
from expense.tui.theme import ACCENT, AMOUNT_RULE, PALETTE, Palette
from expense.tui.widgets.cells import amount_cell
from expense.tui.widgets.header import Breadcrumb

#: Sigil per reference kind — the character a completion writes back into the
#: line. Same table the grammar reads with; kept here because this module goes
#: the other way, from a resolved name to the text that names it.
SIGIL = {"account": "$", "category": "@", "hashtag": "#"}

#: Reference kinds a completion picker can open on.
PICKABLE = frozenset(SIGIL)

#: How many candidates the picker shows at once (the existing form's window).
PICKER_WINDOW = 8

#: The marker and the row number share one cell (`• 1`) — two columns of
#: Rich padding for three characters is width this table does not have.
HEADERS = ("", "date", "title", "amount", "account", "category", "tags", "goes to")

EMPTY_LINES = (
    "Nothing staged. Type a line and press ↵ — nothing reaches the engine",
    "until you press ctrl+s.",
)
EXAMPLE = "e.g.  tottus -38.60 $signature @korakuen #caja hoy"

GRAMMAR_HINT = "what · ±amount · $account · @category · #tag · when"
STAGE_HINT = "↵ stages the line"
STAGED_HINT = "↵ stages · ↑↓ picks a staged row when the bar is empty"
PICKER_HINT = "↑↓ moves, ↵ writes the full name into the line"
COMPLETED_HINT = "↵ completed the token in place — the line always says what will be saved"
EDIT_HINT = "the row came back as the line that made it · ↵ puts it back · esc leaves it alone"
SIGN_HINT = "a sign is what makes a number an amount"
LOADING_HINT = "loading accounts, categories and tags…"


@dataclass
class Staged:
    """One row waiting in the list.

    `line` is the **raw text as typed** — it is what `↵` puts back in the bar,
    so a round trip through the staged list can never lose or reword anything
    (decided 2026-08-25). `parsed` and `routing` are computed once, at stage
    time, and never recomputed on render: the `goes to` column is a promise.
    """

    line: str
    parsed: ParsedLine
    routing: Routing


# ---------------------------------------------------------------------------
# colouring
# ---------------------------------------------------------------------------
def span_style(span: Span, parsed: ParsedLine, palette: Palette | None) -> str:
    """The Rich style for one token of the typed line.

    Colour comes from theme constants only; a literal colour name anywhere
    under `expense/tui/` fails `test_no_literal_color_styles_in_tui` — which is
    blunt enough to read docstrings, so do not name one even in prose. With no
    palette (the pure tests) everything but the structural bold/dim is plain.
    """
    if not span.resolved:
        return palette.error if palette else ""
    if span.kind == "amount":
        if palette is None:
            return ""
        cents = parsed.amount_cents or 0
        return palette.success if cents >= 0 else palette.error
    if span.kind in PICKABLE:
        return ACCENT if palette else ""
    if span.kind in ("date", "note"):
        return "dim"
    return "bold"


class LineHighlighter(Highlighter):
    """Paints the bar from the parse, token by token.

    Textual's `Input` takes a `highlighter=` and applies it in `_value` on every
    render, so live colouring needs no widget subclass: the screen drops the
    latest spans in here after each keystroke and calls `bar.refresh()`.
    """

    def __init__(self) -> None:
        self.parsed: ParsedLine | None = None

    def highlight(self, text: Text) -> None:
        parsed = self.parsed
        if parsed is None:
            return
        limit = len(text)
        for span in parsed.spans:
            if span.start >= limit:
                continue
            style = span_style(span, parsed, PALETTE)
            if style:
                text.stylize(style, span.start, min(span.end, limit))


# ---------------------------------------------------------------------------
# the staged list — pure builders, no app, no event loop
# ---------------------------------------------------------------------------
def format_date_cell(iso: str, today_iso: str) -> str:
    """`18 Aug`, or `18 Aug 2024` when the year is not the current one.

    The year is what makes a two-digit year safe to accept: `18/8/24` is a
    legal date by the grammar, and the staged list is the echo that has to make
    a misread visible (docs/decisions.md "Three quick-add grammar rules"). A
    bare `18 Aug` would hide exactly the digit in question, so the year appears
    the moment it is not this one.
    """
    words = format_date_words(iso)  # "Tue 18 Aug 2026"
    parts = words.split()
    if len(parts) != 4:
        return words
    _weekday, day, month, year = parts
    if year == today_iso[:4]:
        return f"{day} {month}"
    return f"{day} {month} {year}"


def _reference_cell(
    parsed: ParsedLine, kind: str, value: str | None, names: dict, palette: Palette | None
) -> str | Text:
    """A resolved name, or `— account?` in the error colour."""
    if value:
        return resolve_name(value, names)
    return Text(f"— {kind}?", style=palette.error if palette else "")


def _tags_cell(parsed: ParsedLine, refs: QuickAddRefs, palette: Palette | None) -> Text:
    names = [f"#{resolve_name(t, refs.hashtag_names)}" for t in parsed.hashtag_ids]
    if names:
        return Text(" ".join(names), style=ACCENT if palette else "")
    bad = [f"#{u.text}?" for u in parsed.unresolved if u.kind == "hashtag"]
    if bad:
        return Text(" ".join(bad), style=palette.error if palette else "")
    return Text("—", style="dim")


def staged_rows(
    entries: list[Staged], refs: QuickAddRefs, *, palette: Palette | None = None, today: str = ""
) -> list[tuple]:
    """One cell tuple per staged row, in `HEADERS` order.

    Pure and `palette`-parameterised like every other row builder in this
    package, so the table is testable through a Rich console with no app.
    """
    today = today or today_local().isoformat()
    rows: list[tuple] = []
    for number, entry in enumerate(entries, start=1):
        parsed, routing = entry.parsed, entry.routing
        ahead = parsed.date > today
        glyph, glyph_style = (
            ("!", palette.error if palette else "")
            if routing.to_inbox
            else ("•", ACCENT if palette else "")
        )
        marker = Text.assemble((glyph, glyph_style), " ", (str(number), "dim"))
        date = Text(
            format_date_cell(parsed.date, today),
            style=(palette.error if palette else "") if ahead else "dim",
        )
        amount = (
            amount_cell(parsed.amount_cents, palette, AMOUNT_RULE)
            if parsed.amount_cents is not None
            else Text("— no amount", style="dim")
        )
        goes = (
            Text("inbox", style=ACCENT if palette else "")
            if routing.to_inbox
            else Text("ledger", style="dim")
        )
        rows.append(
            (
                marker,
                date,
                Text(parsed.title or "(no title)", style="bold"),
                amount,
                _reference_cell(parsed, "account", parsed.account_id, refs.account_names, palette),
                _reference_cell(
                    parsed, "category", parsed.category_id, refs.category_names, palette
                ),
                _tags_cell(parsed, refs, palette),
                goes,
            )
        )
    return rows


def staged_table(
    entries: list[Staged],
    refs: QuickAddRefs,
    *,
    palette: Palette | None = None,
    picked: int | None = None,
    today: str = "",
) -> RenderableType:
    """The staged list. The picked row is reverse video, like every cursor in
    this app — a Rich style, never CSS (docs/tui.md §3)."""
    if not entries:
        lines = [Text("  " + line, style="dim") for line in EMPTY_LINES]
        lines.append(Text(""))
        lines.append(Text("  " + EXAMPLE, style="dim"))
        return Group(*lines)
    table = Table(box=None, pad_edge=False, expand=False, show_header=True)
    for index, header in enumerate(HEADERS):
        table.add_column(
            Text(header, style="dim"), justify="right" if index == 3 else "left", no_wrap=True
        )
    for index, cells in enumerate(staged_rows(entries, refs, palette=palette, today=today)):
        table.add_row(*cells, style="reverse" if index == picked else "")
    return table


def staged_summary(
    entries: list[Staged], refs: QuickAddRefs, *, palette: Palette | None = None
) -> RenderableType:
    """`3 to the ledger · -45.20 PEN · -96.00 USD` and the Inbox footnote.

    **One figure per currency** (decided 2026-08-25): a batch can hold a PEN row
    and a USD row, and one number covering both would be a lie. With a single
    currency staged — the normal case — it reads exactly as the mockup drew it.

    **The Inbox reasons are route.py's own phrases**, prefixed with the row
    number. The flat `expense log` prints the same strings, which is the point:
    one wording, in one place, for both surfaces.
    """
    if not entries:
        return Text("")
    ledger = [e for e in entries if not e.routing.to_inbox]
    drafts = [(n, e) for n, e in enumerate(entries, start=1) if e.routing.to_inbox]

    lines: list[Text] = []
    if ledger:
        totals: dict[str, int] = {}
        for entry in ledger:
            code = currency_of(refs, entry.parsed.account_id)
            totals[code] = totals.get(code, 0) + (entry.parsed.amount_cents or 0)
        # every row staged is going to the ledger — say it the short way
        head = f"{len(ledger)} staged" if not drafts else f"{len(ledger)} to the ledger"
        line = Text("  " + head, style="dim")
        for code, cents in totals.items():
            line.append(" · ", style="dim")
            figure = amount_cell(cents, palette, AMOUNT_RULE)
            line.append_text(figure if isinstance(figure, Text) else Text(str(figure)))
            if code:
                line.append(f" {code}", style="dim")
        lines.append(line)

    if drafts:
        line = Text("  ", style="dim")
        line.append(f"{len(drafts)} to the Inbox", style=ACCENT if palette else "")
        whys = [f"row {n}: {', '.join(e.routing.reasons)}" for n, e in drafts if e.routing.reasons]
        if whys:
            line.append(" — " + " · ".join(whys), style="dim")
        lines.append(line)

    return Group(*lines)


# ---------------------------------------------------------------------------
# the screen
# ---------------------------------------------------------------------------
@dataclass
class _Picker:
    """The open completion picker: which token, and what it could become."""

    span: Span
    kind: str
    token: Unresolved
    candidates: list[tuple[str, str]] = field(default_factory=list)


class LogBarScreen(EngineWriteMixin, Screen):
    """The LOG bar and its staged list.

    Not a `FormScreen`: that class is built around cycling a *sequence* of
    fields, and this screen has one field and a list. It reuses the form's
    widget ids (`#inputbar`/`#field`/`#bar`/`#hint`/`#suggest`) so `app.tcss`
    styles it with no new rules beyond `#staged`.

    The bar always holds focus — which is why no bare letter is a command here,
    and why there is no `?` key (a focused `Input` swallows printable keys).
    """

    BINDINGS = [
        ("escape", "back", "Cancel"),
        # `priority` is load-bearing: Textual's own `Input` binds ctrl+x to
        # `cut`, and with `select_on_focus` a focused bar can hold a selection —
        # so without it this key would cut the line instead of dropping the row.
        Binding("ctrl+x", "drop_row", "Drop row", priority=True, show=False),
        Binding("up", "move(-1)", "Up", show=False),
        Binding("down", "move(1)", "Down", show=False),
    ]

    crumb = ("Capture & ledger", "Log")

    def __init__(self) -> None:
        super().__init__()
        self._staged: list[Staged] = []
        self._picked: int | None = None
        self._editing: int | None = None
        self._refs: QuickAddRefs | None = None
        self._parsed: ParsedLine | None = None
        self._picker: _Picker | None = None
        self._suggest_idx = 0
        self._completed = False
        self._echo = False  # the bar was set by us, not typed into
        self._hl = LineHighlighter()

    # ---- layout ------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Breadcrumb(self.crumb, id="crumb")
        yield Horizontal(
            Label("LOG", id="field"), Input(id="bar", highlighter=self._hl), id="inputbar"
        )
        yield Static("", id="hint")
        yield Static("", id="suggest")
        yield Static("", id="staged")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#bar", Input).focus()
        self._refresh_view()
        self._load_entities()

    @work(thread=True, exclusive=True)
    def _load_entities(self) -> None:
        # function-local imports: the test fixtures patch these module
        # attributes, and only a lazy lookup sees the patch.
        from expense import config as config_module

        try:
            cfg = config_module.ensure_loaded()
            refs = load_quickadd_refs(cfg, **screen_fetch_kwargs(self.app))
        except Exception as exc:  # surface engine/config errors in-app, don't crash
            self.app.call_from_thread(self.notify, format_error(exc), severity="error")
            return
        self.app.call_from_thread(self._set_refs, refs)

    def _set_refs(self, refs: QuickAddRefs) -> None:
        self._refs = refs
        self._reparse(self.query_one("#bar", Input).value)
        self._refresh_view()

    # ---- parsing -----------------------------------------------------------
    def _reparse(self, text: str) -> None:
        """Re-read the bar and recompute what the picker would offer."""
        refs = self._refs
        if refs is None or not text.strip():
            self._parsed = None
            self._picker = None
        else:
            self._parsed = parse(
                text,
                accounts=refs.accounts,
                categories=refs.categories,
                hashtags=refs.hashtags,
                today=today_local(),
            )
            self._picker = self._picker_at(self.query_one("#bar", Input).cursor_position)
        self._hl.parsed = self._parsed
        self._suggest_idx = min(self._suggest_idx, max(0, len(self._candidates()) - 1))

    def _picker_at(self, caret: int) -> _Picker | None:
        """The unresolved reference token the caret sits in, if any."""
        parsed = self._parsed
        if parsed is None:
            return None
        for token in parsed.unresolved:
            span = token.span
            if span.kind in PICKABLE and span.start <= caret <= span.end:
                return _Picker(
                    span=span, kind=span.kind, token=token, candidates=list(token.candidates)
                )
        return None

    def _candidates(self) -> list[tuple[str, str]]:
        return self._picker.candidates if self._picker else []

    # ---- input -------------------------------------------------------------
    def on_input_changed(self, event: Input.Changed) -> None:
        if not self._echo:
            self._completed = False
        self._echo = False
        self._reparse(event.value)
        self._refresh_view()

    def _set_bar(self, text: str, *, caret: int | None = None) -> None:
        """Write the bar ourselves, without it reading as a keystroke."""
        bar = self.query_one("#bar", Input)
        self._echo = True
        bar.value = text
        bar.cursor_position = len(text) if caret is None else caret
        self._reparse(text)

    # ---- keys --------------------------------------------------------------
    def on_input_submitted(self, event: Input.Submitted | None = None) -> None:
        """`↵`: complete the open token · stage the line · lift a picked row."""
        bar = self.query_one("#bar", Input)
        if self._picker is not None and self._candidates():
            self._complete_token()
        elif bar.value.strip():
            self._stage(bar.value)
        elif self._picked is not None:
            self._lift(self._picked)
        self._refresh_view()

    def action_move(self, delta: int) -> None:
        """`↑↓`: the picker while a token is open, the staged rows when not."""
        if self._picker is not None and self._candidates():
            self._suggest_idx = max(0, min(len(self._candidates()) - 1, self._suggest_idx + delta))
        elif not self.query_one("#bar", Input).value and self._staged:
            if self._picked is None:
                self._picked = 0 if delta > 0 else len(self._staged) - 1
            else:
                self._picked = max(0, min(len(self._staged) - 1, self._picked + delta))
        else:
            return
        self._refresh_view()

    def action_drop_row(self) -> None:
        """`ctrl+x`: drop the picked row."""
        if self._picked is None:
            return
        del self._staged[self._picked]
        if self._editing == self._picked:
            self._cancel_edit()
        self._picked = min(self._picked, len(self._staged) - 1) if self._staged else None
        self._refresh_view()

    def action_back(self) -> None:
        """`esc`: cancel an edit · unpick a row · confirm a discard · leave."""
        if self._editing is not None:
            self._cancel_edit()
        elif self._picked is not None:
            self._picked = None
        elif self._staged:
            self.app.push_screen(DiscardStagedModal(len(self._staged)), self._after_discard)
            return
        else:
            self.dismiss()
            return
        self._refresh_view()

    def _after_discard(self, discard: bool | None) -> None:
        if discard:
            self.dismiss()

    # ---- the three things ↵ does ------------------------------------------
    def _complete_token(self) -> None:
        """Rewrite the open token as the highlighted name, in the line itself.

        The text *is* the storage format — a staged row comes back as the line
        that made it — so a completion that left stale text with a hidden id
        behind it would lose the pick on the round trip.
        """
        picker = self._picker
        if picker is None:
            return
        candidates = picker.candidates
        if not candidates:
            return
        _ident, name = candidates[min(self._suggest_idx, len(candidates) - 1)]
        line = self.query_one("#bar", Input).value
        token = SIGIL[picker.kind] + name
        self._set_bar(
            line[: picker.span.start] + token + line[picker.span.end :],
            caret=picker.span.start + len(token),
        )
        self._completed = True
        self._suggest_idx = 0

    def _stage(self, line: str) -> None:
        """Freeze the line into a row — this is where routing is decided."""
        if self._refs is None:
            self.notify("Still loading accounts and categories.", severity="warning")
            return
        parsed = self._parsed
        if parsed is None:
            return
        entry = Staged(line=line, parsed=parsed, routing=route(parsed, today_local()))
        if self._editing is not None:
            self._staged[self._editing] = entry
            self._picked = self._editing
        else:
            self._staged.append(entry)
            self._picked = None
        self._editing = None
        self._set_bar("")
        self._completed = False

    def _lift(self, index: int) -> None:
        """Put a staged row back in the bar as the raw line that made it."""
        self._editing = index
        self._set_bar(self._staged[index].line)

    def _cancel_edit(self) -> None:
        self._editing = None
        self._set_bar("")

    # ---- render ------------------------------------------------------------
    def _refresh_view(self) -> None:
        label = "LOG" if self._editing is None else f"EDIT {self._editing + 1}"
        self.query_one("#field", Label).update(label)
        self.query_one("#bar", Input).refresh()
        self.query_one("#hint", Static).update(Text(self._hint(), style="dim"))
        self.query_one("#suggest", Static).update(self._suggest_renderable())
        self.query_one("#staged", Static).update(self._staged_renderable())

    def _hint(self) -> str:
        if self._refs is None:
            return LOADING_HINT
        if self._editing is not None:
            return EDIT_HINT
        if self._picker is not None:
            return f"{describe(self._picker.token)} — {PICKER_HINT}"
        if self._completed:
            return COMPLETED_HINT
        parsed = self._parsed
        if parsed is not None:
            caret = self.query_one("#bar", Input).cursor_position
            for span in parsed.spans:
                if span.kind == "amount" and span.start <= caret <= span.end:
                    return f"{format_cents(parsed.amount_cents)} — {SIGN_HINT}."
            if parsed.date_given:
                return f"{format_date_words(parsed.date)} · {STAGE_HINT}"
            return STAGE_HINT
        if self._staged:
            return STAGED_HINT
        return f"{GRAMMAR_HINT}     {STAGE_HINT}"

    def _suggest_renderable(self) -> RenderableType:
        picker = self._picker
        if picker is None:
            return Text("")
        candidates = picker.candidates
        if not candidates:
            return Text("  no matches — pick something that exists", style="dim")
        total = len(candidates)
        start = 0
        if total > PICKER_WINDOW:
            start = max(0, min(self._suggest_idx - PICKER_WINDOW // 2, total - PICKER_WINDOW))
        rows: list[Text] = []
        if start > 0:
            rows.append(Text(f"  ↑ {start} more", style="dim"))
        for index in range(start, min(start + PICKER_WINDOW, total)):
            ident, name = candidates[index]
            extra = currency_of(self._refs, ident) if self._refs else ""
            line = Text(f"  {name}{'    ' + extra if extra else ''}")
            if index == self._suggest_idx:
                line.stylize("reverse")
            rows.append(line)
        remaining = total - min(start + PICKER_WINDOW, total)
        if remaining > 0:
            rows.append(Text(f"  ↓ {remaining} more", style="dim"))
        return Group(*rows)

    def _staged_renderable(self) -> RenderableType:
        refs = self._refs
        if refs is None:
            return Text("")
        return Group(
            staged_table(self._staged, refs, palette=PALETTE, picked=self._picked),
            Text(""),
            staged_summary(self._staged, refs, palette=PALETTE),
        )
