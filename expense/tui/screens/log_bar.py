"""The LOG bar — one typed line, a staged batch, one save.

The capture surface of the quick-add bar, drawn in
docs/mockups/expense-world-quickadd-batch.html. You type one line, press `↵`,
and it lands in a list you can read before anything is written; `↑↓` pick a
staged row back up, `ctrl+x` drops one, `esc` confirms a discard.

**This is what `+` opens** (quick-add phase 4, 2026-08-25). The bar-cycle form
it replaced kept its *edit* door — `⏎` on an existing row — and lost only its
create one (docs/mockups/expense-world-two-doors.html): an existing row has an
id, a version and possibly a reconciliation freezing four of its fields, so
correcting one is a PUT of what changed, not a line retyped from scratch.

**The save** is `ctrl+s`: one `POST /transactions/batch` for the complete rows,
then one `POST /inbox` per draft, through `expense/batch_write.py` — the same
chunk-then-row-by-row pattern `expense import` uses, because the engine refuses
an atomic batch without saying which row. What that means when only half of it
lands is four owner calls, recorded in docs/decisions.md "What a half-written
batch means": the screen stays and the ticks are the receipt, a retry re-sends
only the rows without one, an unstaged line in the bar is never written, and
the discard card's `ctrl+s save first` leaves only if the save succeeds.

**The account peek** (2026-08-29, docs/mockups/expense-world-log-account-peek.html):
the moment the line names an account, that account's posted ledger fills the
room under the staged list — `AccountPeek`, elastic, read-only. The account is
always the **bar's**, never a staged row's, and it is sticky: `↵` clears the bar
but the panel stays on the last account named, so a run of lines against one
account keeps its window open (picks A and i).

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
from uuid import uuid4

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

from expense.batch_write import BatchOutcome, RowResult, post_transaction_batch
from expense.commands import transactions_cmd
from expense.commands._resource import (
    QuickAddRefs,
    currency_of,
    format_cents,
    format_hashtag_cell,
    format_short_date,
    items_of,
    load_quickadd_refs,
    resolve_name,
    truncate,
)
from expense.dates import now_local_iso, to_canonical_aware, today_local
from expense.errors import EngineConnectionError, EngineError, format_error
from expense.quickadd.parse import ParsedLine, Span, Unresolved, parse
from expense.quickadd.payload import inbox_payload, transaction_payload
from expense.quickadd.route import Routing, describe, route
from expense.quickadd.when import format_date_words
from expense.tui.screens._base import screen_fetch_kwargs
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

#: The peek's columns. No account column — every row in it names the same one —
#: and no description: the panel is narrow and the ledger screen has both.
PEEK_HEADERS = ("date", "title", "amount", "category", "tags")

#: How many of the account's rows are fetched. The panel draws as many as fit
#: (it is `1fr`); this is the ceiling on a very tall terminal, one page.
PEEK_LIMIT = 40

#: Seconds between the account resolving and the fetch. Arrowing through the
#: picker resolves a different account per keystroke, and each one would
#: otherwise be a request; only the account you stop on is worth fetching.
PEEK_DEBOUNCE = 0.25

PEEK_LOADING = "loading…"

#: The marker a written row carries. A saved row is done — it is never re-sent.
SAVED_GLYPH = "✓"
EXAMPLE = "e.g.  tottus -38.60 $signature @korakuen #caja hoy"

STAGE_HINT = "↵ stages the line"

#: The legend — the whole grammar in one fixed row under the bar, with what
#: `↵` does on the same line (pick A, 2026-08-29,
#: docs/mockups/expense-world-log-legend-and-picker.html). It never changes:
#: it describes the grammar, not the moment, and the moment is the `#hint` row
#: above it. Constant width, so nothing below it ever moves.
LEGEND = "$account · @category · #tag · ±amount · //note · when"
LEGEND_LINE = f"{LEGEND}     {STAGE_HINT}"
STAGED_HINT = "↵ stages · ctrl+s saves all · ↑↓ picks a staged row when the bar is empty"
SAVING_HINT = "writing…"
PICKER_HINT = "↑↓ moves, ↵ writes the full name into the line"
COMPLETED_HINT = "↵ completed the token in place — the line always says what will be saved"
EDIT_HINT = "the row came back as the line that made it · ↵ puts it back · esc leaves it alone"
SIGN_HINT = "a sign is what makes a number an amount"
LOADING_HINT = "loading accounts, categories and tags…"


def wire_date(parsed: ParsedLine) -> str:
    """The `date` a payload builder wants: canonical RFC 3339 with an offset.

    Same rule the flat `expense log` applies (`log_cmd._log_from_line`) — a line
    that named no date is written as *now*, not as local midnight, so a row
    logged this afternoon sorts after one logged this morning.
    """
    if not parsed.date_given:
        return now_local_iso()
    return to_canonical_aware(parsed.date)


@dataclass
class Staged:
    """One row waiting in the list.

    `line` is the **raw text as typed** — it is what `↵` puts back in the bar,
    so a round trip through the staged list can never lose or reword anything
    (decided 2026-08-25). `parsed` and `routing` are computed once, at stage
    time, and never recomputed on render: the `goes to` column is a promise.

    `saved` is the phase-4 half. A saved row is done: it keeps a `✓`, it is
    never re-sent, and `ctrl+s` only ever covers the rows without one.

    **`row_id` and `date` are frozen at stage time too**, for the same reason
    the routing is. The id makes a retry safe: a row whose response was lost
    replays under the id it already had, so the engine answers 409 and the row
    ticks instead of landing twice — a fresh id per attempt would double-write.
    The date is frozen because the `date` column is a promise as much as
    `goes to` is: a batch typed at 23:59 and saved at 00:01 must not silently
    change day between what you read and what you wrote.
    """

    line: str
    parsed: ParsedLine
    routing: Routing
    row_id: str = field(default_factory=lambda: str(uuid4()))
    date: str = ""
    saved: bool = False
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.date:
            self.date = wire_date(self.parsed)


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
        if entry.saved:
            glyph, glyph_style = SAVED_GLYPH, (palette.success if palette else "")
        elif routing.to_inbox:
            glyph, glyph_style = "!", (palette.error if palette else "")
        else:
            glyph, glyph_style = "•", (ACCENT if palette else "")
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
    last_save: str = "",
) -> RenderableType:
    """The staged list. The picked row is reverse video, like every cursor in
    this app — a Rich style, never CSS (docs/tui.md §3).

    `last_save` is the receipt from a save whose rows have since been cleared —
    the list only ever shows pending rows, so what a finished batch leaves
    behind is one sentence, not a table (decided 2026-08-25).
    """
    if not entries:
        if last_save:
            return Group(
                Text(f"  Nothing staged. {last_save} a moment ago.", style="dim"),
                Text("  Type a line and press ↵.", style="dim"),
                Text(""),
                Text("  " + EXAMPLE, style="dim"),
            )
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


def save_receipt(entries: list[Staged]) -> str:
    """`2 logged · 1 draft in the Inbox` — what a save actually wrote.

    Counted from `saved`, never from the routing alone, so a partial save says
    what landed rather than what was hoped for. Empty string when nothing has
    been written yet, which is what keeps it out of the at-rest screen.
    """
    logged = sum(1 for e in entries if e.saved and not e.routing.to_inbox)
    drafts = sum(1 for e in entries if e.saved and e.routing.to_inbox)
    parts = []
    if logged:
        parts.append(f"{logged} logged")
    if drafts:
        parts.append(f"{drafts} draft{'' if drafts == 1 else 's'} in the Inbox")
    return " · ".join(parts)


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

    **Saved rows are counted, not totalled** (phase 4). Once a row is written it
    stops being something you are about to do, so it leaves the per-currency
    totals and joins the receipt line — otherwise the figure under a half-saved
    list would describe a batch that no longer exists.
    """
    if not entries:
        return Text("")
    pending = [e for e in entries if not e.saved]
    ledger = [e for e in pending if not e.routing.to_inbox]
    drafts = [(n, e) for n, e in enumerate(entries, start=1) if e.routing.to_inbox and not e.saved]

    lines: list[Text] = []
    receipt = save_receipt(entries)
    if receipt:
        line = Text("  ", style="dim")
        line.append(receipt, style=palette.success if palette else "")
        if not pending:
            line.append(" · ctrl+s again does nothing — the list is done", style="dim")
        lines.append(line)

    if ledger:
        totals: dict[str, int] = {}
        for entry in ledger:
            code = currency_of(refs, entry.parsed.account_id)
            totals[code] = totals.get(code, 0) + (entry.parsed.amount_cents or 0)
        # every row still pending is going to the ledger — say it the short way
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

    return Group(*lines) if lines else Text("")


def save_errors(entries: list[Staged], *, palette: Palette | None = None) -> RenderableType:
    """What the engine refused, row by row, under the table.

    The engine's own message is passed through `format_error` upstream and
    printed verbatim — the "engine errors surface cleanly" rule; this only adds
    the row number, so the sentence can be matched to a line in the list.
    """
    failed = [(n, e) for n, e in enumerate(entries, start=1) if e.error]
    if not failed:
        return Text("")
    lines: list[Text] = []
    for number, entry in failed:
        line = Text("  ", style="dim")
        line.append(f"row {number}: ", style="dim")
        line.append(entry.error or "", style=palette.error if palette else "")
        lines.append(line)
    lines.append(Text("  ctrl+s retries just the rows without a ✓.", style="dim"))
    return Group(*lines)


# ---------------------------------------------------------------------------
# the account peek — the ledger of the account the line names
# ---------------------------------------------------------------------------
def peek_rows(
    items: list[dict], refs: QuickAddRefs, *, palette: Palette | None = None, today: str = ""
) -> list[tuple]:
    """One cell tuple per posted row, in `PEEK_HEADERS` order.

    The same shape `transactions.py` builds, minus the two columns the panel
    has no room for — pure and `palette`-parameterised like every other row
    builder here, so it renders through a Rich console with no app.

    Names come from `refs`, which the screen has already loaded for the
    grammar: the peek costs one transactions fetch, never a second name fetch.

    Dates read as the staged list's do — `20 Aug`, with the year the moment it
    is not this one — because the two tables sit one above the other and a row
    should not change shape as it crosses from one to the other.
    """
    today = today or today_local().isoformat()
    rows: list[tuple] = []
    for item in items:
        rows.append(
            (
                Text(format_date_cell(format_short_date(item.get("date")), today), style="dim"),
                Text(truncate(item.get("title") or "—", 28), style="bold"),
                amount_cell(item.get("amount_cents"), palette, AMOUNT_RULE),
                Text(resolve_name(item.get("category_id"), refs.category_names), style="dim"),
                Text(
                    format_hashtag_cell(
                        item.get("hashtag_ids"), refs.hashtag_names, max_width=18, prefix="#"
                    ),
                    style=ACCENT if palette else "",
                ),
            )
        )
    return rows


def peek_status(shown: int, total: int) -> str:
    """The panel's border subtitle — how much of the account you are seeing.

    `shown` is what the panel had room for, so on a screen with a long staged
    list it can be nothing at all: the panel says so rather than pretending the
    account is empty.
    """
    if not total:
        return "nothing in this account yet"
    if not shown:
        return f"{total} in this account · no room to show them"
    if shown >= total:
        return f"{total} in this account · newest first"
    return f"{shown} of {total} in this account · newest first"


class AccountPeek(Static):
    """The named account's posted ledger, under the staged list.

    **Elastic** (mockup pick A, 2026-08-29, docs/mockups/expense-world-log-account-peek.html):
    the widget is `1fr`, so Textual hands it whatever rows the staged list is
    not using and it draws exactly that many — twelve on an empty screen,
    fewer as the batch grows, none at all once the list fills the terminal. It
    re-renders on its own `Resize`, which is what makes "as many as fit" a fact
    rather than an estimate.

    **Read-only.** No cursor, no keys: `↑↓` belong to the staged list and the
    panel is a window, not a table you work in.
    """

    def __init__(self) -> None:
        super().__init__("", id="peek")
        self._rows: list[tuple] = []
        self._total = 0
        self._note = ""
        self._content: RenderableType = Text("")

    def show(self, account: str, rows: list[tuple], total: int, *, note: str = "") -> None:
        self.border_title = account
        self._rows, self._total, self._note = rows, total, note
        self._rebuild()

    def on_resize(self) -> None:
        self._rebuild()

    @property
    def capacity(self) -> int:
        """Rows this panel can draw right now: its height, less the header."""
        return max(0, self.content_size.height - 1)

    @property
    def content(self) -> RenderableType:
        """What the panel is drawing right now — the table, or a note."""
        return self._content

    def _rebuild(self) -> None:
        self._content = self._build()
        self.update(self._content)

    def _build(self) -> RenderableType:
        if self._note:
            self.border_subtitle = ""
            return Text("  " + self._note, style="dim")
        shown = min(len(self._rows), self.capacity)
        self.border_subtitle = peek_status(shown, self._total)
        # `expand=False`, like the staged table above it: the columns pack to
        # their content instead of spreading to the panel edge, so a row reads
        # the same in both tables.
        table = Table(box=None, pad_edge=False, expand=False, show_header=True)
        for index, header in enumerate(PEEK_HEADERS):
            table.add_column(
                Text(header, style="dim"), justify="right" if index == 2 else "left", no_wrap=True
            )
        for cells in self._rows[:shown]:
            table.add_row(*cells)
        return table


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


class LogBarScreen(Screen):
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
        Binding("ctrl+s", "save", "Save"),
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
        self._saving = False
        self._last_save = ""  # the receipt left behind once saved rows clear
        # the peek: which account it shows, and one cached page per account
        self._peek_account: str | None = None
        self._peek_cache: dict[str, tuple[list[dict], int]] = {}
        self._peek_note: dict[str, str] = {}
        self._peek_wanted: str | None = None
        self._peek_timer = None

    # ---- layout ------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Breadcrumb(self.crumb, id="crumb")
        yield Horizontal(
            Label("LOG", id="field"), Input(id="bar", highlighter=self._hl), id="inputbar"
        )
        yield Static("", id="hint")
        yield Static(Text(LEGEND_LINE, style="dim"), id="legend")
        yield Static("", id="suggest")
        yield Static("", id="staged")
        yield AccountPeek()
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
        if self._saving:
            self.notify("Writing — one moment.")
            return
        if self._editing is not None:
            self._cancel_edit()
        elif self._picked is not None:
            self._picked = None
        elif self._pending():
            self.app.push_screen(DiscardStagedModal(len(self._pending())), self._after_discard)
            return
        else:
            self.dismiss()
            return
        self._refresh_view()

    def _after_discard(self, answer: str | None) -> None:
        """`d` leaves the rows behind · `ctrl+s` writes them first, then leaves.

        The save-first arm dismisses only once every row lands — a failed save
        keeps you on the screen, because an error you cannot read is the same
        as no error at all (decided 2026-08-25).
        """
        if answer == "discard":
            self.dismiss()
        elif answer == "save":
            self._begin_save(leave_after=True)

    # ---- the save ----------------------------------------------------------
    def _pending(self) -> list[Staged]:
        """The rows `ctrl+s` covers: everything not already written."""
        return [e for e in self._staged if not e.saved]

    def action_save(self) -> None:
        """`ctrl+s`: write every staged row that is not already saved.

        A half-typed line in the bar is **not** staged and **not** saved
        (decided 2026-08-25) — `↵` is the only thing that stages, so a save can
        never write something you were still in the middle of.
        """
        self._begin_save(leave_after=False)

    def _begin_save(self, *, leave_after: bool) -> None:
        if self._saving or not self._pending():
            return
        self._saving = True
        for entry in self._pending():
            entry.error = None  # a retry starts clean; only the ticks persist
        self._refresh_view()
        self._save(leave_after)

    @work(thread=True, group="engine-write")
    def _save(self, leave_after: bool) -> None:
        """One `POST /transactions/batch` for the ledger rows, then one
        `POST /inbox` per draft.

        Not `EngineWriteMixin.run_write`: that is one request per queued item,
        it drops the response, and it clears the queue on the first error —
        none of which fits a batch with a per-row fallback. The worker still
        runs in run_write's `engine-write` group, so it cannot race one.
        """
        # lazy, like every other write site: the test fixture patches
        # `expense.http.ExpenseClient` and only an in-function lookup sees it
        from expense import config as config_module
        from expense.http import ExpenseClient

        ledger = [e for e in self._pending() if not e.routing.to_inbox]
        drafts = [e for e in self._pending() if e.routing.to_inbox]
        try:
            cfg = config_module.ensure_loaded()
            with ExpenseClient(cfg, verbose=self.app._verbose) as client:
                if ledger:
                    items = [
                        transaction_payload(e.parsed, row_id=e.row_id, date=e.date) for e in ledger
                    ]
                    outcome = post_transaction_batch(client, items)
                    self.app.call_from_thread(self._apply_outcome, ledger, outcome)
                for entry in drafts:
                    body = inbox_payload(entry.parsed, row_id=entry.row_id, date=entry.date)
                    try:
                        client.post("/inbox", json_body=body)
                    except EngineError as err:
                        # 409 = this id is already a draft: the row IS in
                        ok = err.status == 409
                        note = None if ok else format_error(err)
                        self.app.call_from_thread(self._mark, entry, ok, note)
                    else:
                        self.app.call_from_thread(self._mark, entry, True, None)
        except EngineConnectionError as err:
            message = format_error(err)
            self.app.call_from_thread(self._stop_save, message)
        except Exception as err:  # noqa: BLE001 - a worker crash must not be silent
            self.app.call_from_thread(self._stop_save, str(err))
        else:
            self.app.call_from_thread(self._save_finished, leave_after)
            return
        self.app.call_from_thread(self._save_finished, False)

    def _apply_outcome(self, rows: list[Staged], outcome: BatchOutcome) -> None:
        """Fold the shared batch result onto the staged rows it came from.

        `CREATED` and `EXISTED` both mean the engine holds the row — the second
        is a replay of an id we already minted, which is exactly what a retry
        after a half-written save produces.
        """
        errors = outcome.errors
        for index, result in enumerate(outcome.results):
            entry = rows[index]
            if result in (RowResult.CREATED, RowResult.EXISTED):
                self._mark(entry, True, None)
            elif result is RowResult.FAILED:
                self._mark(entry, False, errors.get(index))
            elif outcome.stopped:
                self._mark(entry, False, outcome.stop_error)

    def _mark(self, entry: Staged, saved: bool, error: str | None) -> None:
        entry.saved = saved
        entry.error = error
        self._refresh_view()

    def _stop_save(self, message: str) -> None:
        for entry in self._pending():
            entry.error = message
        self._refresh_view()

    def _save_finished(self, leave_after: bool) -> None:
        self._saving = False
        self._invalidate_peek([e for e in self._staged if e.saved])
        written = save_receipt(self._staged)
        if written:
            self._last_save = written
        if leave_after and not self._pending():
            self.dismiss()
            return
        if self._pending():
            self.notify("Some rows were not written.", title="Failed", severity="error")
        elif written:
            self.notify(written)
        self._refresh_view()

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
        # A finished batch clears the moment the next one starts: the list only
        # ever shows rows you are about to write, and what the save wrote lives
        # on as `_last_save` (decided 2026-08-25).
        if self._staged and not self._pending():
            self._staged.clear()
            self._picked = None
            self._editing = None
        entry = Staged(line=line, parsed=parsed, routing=route(parsed, today_local()))
        # A written row is never replaced: it has an id the engine already holds,
        # and overwriting it here would drop the tick and write the row twice.
        editing = self._editing
        if editing is not None and self._staged[editing].saved:
            editing = None
            self.notify("That row is already written — this stages a new one.")
        if editing is not None:
            self._staged[editing] = entry
            self._picked = editing
        else:
            self._staged.append(entry)
            self._picked = None
        self._editing = None
        self._set_bar("")
        self._completed = False

    def _lift(self, index: int) -> None:
        """Put a staged row back in the bar as the raw line that made it.

        A written row cannot be lifted: editing it would suggest the change
        reaches the ledger, and it does not — this screen only ever creates.
        Correcting a written row is the edit form's job (`⏎` on it in
        Transactions), which is exactly why that door stayed open.
        """
        if self._staged[index].saved:
            self.notify(f"Row {index + 1} is written. Edit it from Transactions.")
            return
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
        staged = self.query_one("#staged", Static)
        content = self._staged_renderable()
        # `None` = nothing to draw: the widget goes away rather than holding
        # empty rows the peek below it could be using (mockup pane A).
        staged.display = content is not None
        if content is not None:
            staged.update(content)
        self._sync_peek()

    # ---- the account peek --------------------------------------------------
    def _peek_target(self) -> str | None:
        """Which account the peek shows — always the bar's, never a staged row's.

        Four cases, decided 2026-08-29 with the mockup:

        * a **picker open on an account** — the highlighted candidate, so the
          peek swaps as you arrow and the disambiguation answers itself;
        * a **resolved `$account`** — that one;
        * an **account token that resolves to nothing** — none: the row is
          bound for the Inbox and there is no ledger to show;
        * **no account token at all**, including the empty bar `↵` leaves
          behind — the last one the bar named (pick i). Staging a line must not
          blink the panel off between the lines of a run against one account.
        """
        picker = self._picker
        if picker is not None and picker.kind == "account" and picker.candidates:
            index = min(self._suggest_idx, len(picker.candidates) - 1)
            return picker.candidates[index][0]
        parsed = self._parsed
        if parsed is None:
            return self._peek_account
        if parsed.account_id:
            return str(parsed.account_id)
        if any(token.kind == "account" for token in parsed.unresolved):
            return None
        return self._peek_account

    def _sync_peek(self) -> None:
        """Point the panel at that account, fetching its page once."""
        peek = self.query_one("#peek", AccountPeek)
        refs = self._refs
        target = self._peek_target()
        self._peek_account = target
        if target is None or refs is None:
            peek.display = False
            return
        peek.display = True
        name = resolve_name(target, refs.account_names)
        note = self._peek_note.get(target)
        cached = self._peek_cache.get(target)
        if cached is not None:
            items, total = cached
            peek.show(name, peek_rows(items, refs, palette=PALETTE), total)
            return
        peek.show(name, [], 0, note=note or PEEK_LOADING)
        if note is None:
            self._request_peek(target)

    def _request_peek(self, account_id: str) -> None:
        """Fetch after `PEEK_DEBOUNCE`, and only what you stopped on.

        One slot, one timer: retargeting replaces both, so arrowing through
        five candidates costs one request, not five. An account already
        cached — or already refused — never asks again.
        """
        self._peek_wanted = account_id
        if self._peek_timer is not None:
            self._peek_timer.stop()
        self._peek_timer = self.set_timer(PEEK_DEBOUNCE, self._fire_peek)

    def _fire_peek(self) -> None:
        self._peek_timer = None
        account_id = self._peek_wanted
        if account_id and account_id == self._peek_account and account_id not in self._peek_cache:
            self._load_peek(account_id)

    @work(thread=True, group="peek")
    def _load_peek(self, account_id: str) -> None:
        """`GET /transactions?account_id=…` — the read the ledger screen makes."""
        from expense import config as config_module

        try:
            cfg = config_module.ensure_loaded()
            body = transactions_cmd.fetch_transactions(
                cfg, account=account_id, limit=PEEK_LIMIT, **screen_fetch_kwargs(self.app)
            )
        except Exception as exc:  # a peek is a courtesy: it reports, never raises
            self.app.call_from_thread(self._peek_failed, account_id, format_error(exc))
            return
        self.app.call_from_thread(self._peek_loaded, account_id, body)

    def _peek_loaded(self, account_id: str, body: object) -> None:
        items = items_of(body)
        total = body.get("total") if isinstance(body, dict) else None
        self._peek_cache[account_id] = (items, total if isinstance(total, int) else len(items))
        self._peek_note.pop(account_id, None)
        self._refresh_view()

    def _peek_failed(self, account_id: str, message: str) -> None:
        self._peek_note[account_id] = message
        self._refresh_view()

    def _invalidate_peek(self, entries: list[Staged]) -> None:
        """Drop the cached page of every account a save just wrote to.

        The rows you just logged belong in the panel — it is the same ledger.
        """
        for entry in entries:
            account_id = entry.parsed.account_id
            if isinstance(account_id, str):
                self._peek_cache.pop(account_id, None)
        if self._peek_account and self._peek_account not in self._peek_cache:
            self._request_peek(self._peek_account)

    def _hint(self) -> str:
        """What the parser makes of the line *right now* — never the grammar.

        The grammar is the legend row below this one, permanently; this row
        carries only what changes: the amount echo, the resolved date, how
        many names a token matches, and the three modal states.
        """
        if self._saving:
            return SAVING_HINT
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
                return format_date_words(parsed.date)
            return ""
        if self._staged:
            return STAGED_HINT
        return ""

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

    def _staged_renderable(self) -> RenderableType | None:
        """The staged list, or `None` when there is nothing to show.

        The invitation ("Nothing staged…", and the example line) is what an
        empty screen says — but the moment the line names an account, the peek
        is the better use of those rows and the invitation stands down, exactly
        as pane A of the mockup drew it. The hint line above still says what
        `↵` does, so nothing is lost but the repetition.
        """
        refs = self._refs
        if refs is None:
            return None
        if not self._staged and not self._last_save and self._peek_target() is not None:
            return None
        parts: list[RenderableType] = [
            staged_table(
                self._staged,
                refs,
                palette=PALETTE,
                picked=self._picked,
                last_save=self._last_save,
            ),
            Text(""),
            staged_summary(self._staged, refs, palette=PALETTE),
        ]
        errors = save_errors(self._staged, palette=PALETTE)
        if isinstance(errors, Group):
            parts.extend((Text(""), errors))
        return Group(*parts)
