"""The LOG bar — phase 3, staging only (docs/todo.md item 1).

Pure builders first (the staged table and its summary render through a Rich
console with no app), then one pilot test per mockup state
(docs/mockups/expense-world-quickadd-batch.html, panes 1-6 and 9).

The phase boundary is tested too: staging writes nothing, because `ctrl+s` does
not exist until phase 4.
"""

import asyncio
import io
from datetime import date

from rich.console import Console
from textual.widgets import Input, Label

from expense.commands._resource import QuickAddRefs
from expense.quickadd.parse import parse
from expense.quickadd.route import route
from expense.tui.app import ExpenseApp
from expense.tui.screens.log_bar import (
    LogBarScreen,
    Staged,
    format_date_cell,
    span_style,
    staged_summary,
    staged_table,
)
from expense.tui.screens.modals import DiscardStagedModal
from expense.tui.theme import ACCENT, PALETTE
from tests.unit.helpers import wait_for

ACCOUNTS = [
    {"id": "acc1", "name": "BCP Signature PEN", "currency_code": "PEN", "is_person": False},
    {"id": "acc2", "name": "BCP Signature USD", "currency_code": "USD", "is_person": False},
    {"id": "acc3", "name": "BCP PEN", "currency_code": "PEN", "is_person": False},
]
CATEGORIES = {
    "items": [
        {"id": "cat1", "name": "KORAKUEN", "is_system": False},
        {"id": "cat2", "name": "TRANSPORTE", "is_system": False},
    ]
}
HASHTAGS = {"items": [{"id": "h1", "name": "CAJA CHICA"}, {"id": "h2", "name": "TAXI"}]}

REFS = QuickAddRefs(
    accounts=[
        ("acc1", "BCP Signature PEN", "PEN"),
        ("acc2", "BCP Signature USD", "USD"),
        ("acc3", "BCP PEN", "PEN"),
    ],
    categories=[("cat1", "KORAKUEN"), ("cat2", "TRANSPORTE")],
    hashtags=[("h1", "CAJA CHICA"), ("h2", "TAXI")],
    account_names={
        "acc1": "BCP Signature PEN",
        "acc2": "BCP Signature USD",
        "acc3": "BCP PEN",
    },
    category_names={"cat1": "KORAKUEN", "cat2": "TRANSPORTE"},
    hashtag_names={"h1": "CAJA CHICA", "h2": "TAXI"},
)

TODAY = date(2026, 8, 20)


def _patch(monkeypatch):
    """Screen-specific patches; the client/config seams come from fake_client."""
    monkeypatch.setattr("expense.commands.accounts_cmd.fetch_accounts", lambda *a, **k: ACCOUNTS)
    monkeypatch.setattr(
        "expense.commands.categories_cmd.fetch_categories", lambda *a, **k: CATEGORIES
    )
    monkeypatch.setattr("expense.commands.hashtags_cmd.fetch_hashtags", lambda *a, **k: HASHTAGS)


def _text(renderable, width: int = 120) -> str:
    con = Console(file=io.StringIO(), width=width)
    con.print(renderable)
    return con.file.getvalue()


def _styled(renderable, width: int = 120) -> str:
    """Rendered *with* its ANSI codes — the only way to see reverse video."""
    con = Console(file=io.StringIO(), width=width, force_terminal=True)
    con.print(renderable)
    return con.file.getvalue()


def _stage(line: str, today: date = TODAY) -> Staged:
    parsed = parse(
        line,
        accounts=REFS.accounts,
        categories=REFS.categories,
        hashtags=REFS.hashtags,
        today=today,
    )
    return Staged(line=line, parsed=parsed, routing=route(parsed, today))


LEDGER_LINE = "tottus porongoche -38.60 $BCP Signature PEN @KORAKUEN #CAJA CHICA"
NO_ACCOUNT_LINE = "apparka mall -3.50 @TRANSPORTE #TAXI 18/08/2026"
AHEAD_LINE = "alquiler -1800 $BCP PEN @KORAKUEN 22/08/2026"
USD_LINE = "shimaya ramen -96.00 $BCP Signature USD @KORAKUEN"


# ---- pure: the staged table -------------------------------------------------
def test_ledger_row_is_marked_and_routed_to_the_ledger():
    out = _text(staged_table([_stage(LEDGER_LINE)], REFS, today=TODAY.isoformat()))
    assert "•" in out and "ledger" in out
    assert "TOTTUS" not in out  # the title is shown verbatim, never upper-cased
    assert "tottus porongoche" in out
    assert "-38.60" in out and "BCP Signature PEN" in out and "#CAJA CHICA" in out


def test_row_with_no_account_is_flagged_and_routed_to_the_inbox():
    out = _text(staged_table([_stage(NO_ACCOUNT_LINE)], REFS, today=TODAY.isoformat()))
    assert "!" in out
    assert "— account?" in out
    assert "inbox" in out


def test_row_dated_ahead_goes_to_the_inbox_though_it_is_complete():
    entry = _stage(AHEAD_LINE)
    assert entry.parsed.is_complete  # nothing is missing — only the date is
    assert entry.routing.to_inbox
    assert "it is dated ahead" in entry.routing.reasons


def test_row_without_tags_shows_a_dim_dash():
    out = _text(staged_table([_stage(AHEAD_LINE)], REFS, today=TODAY.isoformat()))
    assert "—" in out


def test_empty_list_is_the_invitation_not_a_table():
    out = _text(staged_table([], REFS))
    assert "Nothing staged" in out
    assert "tottus -38.60 $signature @korakuen #caja hoy" in out
    assert "date" not in out  # no header row when there is nothing to head


def test_picked_row_renders_differently_from_its_neighbours():
    entries = [_stage(LEDGER_LINE), _stage(USD_LINE)]
    plain = _styled(staged_table(entries, REFS, palette=PALETTE, today=TODAY.isoformat()))
    picked = _styled(
        staged_table(entries, REFS, palette=PALETTE, picked=1, today=TODAY.isoformat())
    )
    assert plain != picked
    # reverse video, the app-wide cursor — applied as a Rich style, never CSS
    assert "\x1b[7m" in picked and "\x1b[7m" not in plain


# ---- pure: the date cell ----------------------------------------------------
def test_date_cell_hides_the_current_year_and_shows_any_other():
    assert format_date_cell("2026-08-18", "2026-08-20") == "18 Aug"
    # a two-digit year is only safe to accept because a misread stays visible
    assert format_date_cell("2024-08-18", "2026-08-20") == "18 Aug 2024"


# ---- pure: the summary ------------------------------------------------------
def test_summary_with_one_currency_reads_as_the_mockup_drew_it():
    entries = [_stage(LEDGER_LINE), _stage("shimaya ramen -96.00 $BCP PEN @KORAKUEN")]
    out = _text(staged_summary(entries, REFS))
    assert "2 staged" in out  # everything is going to the ledger
    assert "-134.60 PEN" in out


def test_summary_totals_per_currency_never_adds_soles_to_dollars():
    out = _text(staged_summary([_stage(LEDGER_LINE), _stage(USD_LINE)], REFS))
    assert "-38.60 PEN" in out
    assert "-96.00 USD" in out
    assert "-134.60" not in out


def test_summary_names_the_inbox_rows_with_routes_own_phrases():
    entries = [_stage(LEDGER_LINE), _stage(NO_ACCOUNT_LINE), _stage(AHEAD_LINE)]
    out = _text(staged_summary(entries, REFS), width=160)
    assert "1 to the ledger" in out
    assert "2 to the Inbox" in out
    assert "row 2: the line names no account" in out
    assert "row 3: it is dated ahead" in out


def test_summary_of_an_empty_list_is_silent():
    assert _text(staged_summary([], REFS)).strip() == ""


# ---- pure: colouring --------------------------------------------------------
def test_span_styles_come_from_the_theme_not_from_literals():
    parsed = _stage(LEDGER_LINE).parsed
    by_kind = {s.kind: span_style(s, parsed, PALETTE) for s in parsed.spans}
    assert by_kind["amount"] == PALETTE.error  # negative
    assert by_kind["account"] == ACCENT
    assert by_kind["category"] == ACCENT
    assert by_kind["title"] == "bold"

    income = _stage("sueldo +2450 $BCP PEN @KORAKUEN").parsed
    amount = next(s for s in income.spans if s.kind == "amount")
    assert span_style(amount, income, PALETTE) == PALETTE.success


def test_an_unresolved_token_takes_the_error_colour():
    parsed = _stage("apparka -3.50 $nope @KORAKUEN").parsed
    bad = next(s for s in parsed.spans if not s.resolved)
    assert span_style(bad, parsed, PALETTE) == PALETTE.error


def test_highlighter_paints_the_bar_from_the_parse():
    from rich.text import Text

    from expense.tui.screens.log_bar import LineHighlighter

    hl = LineHighlighter()
    assert hl(Text(LEDGER_LINE)).spans == []  # nothing parsed yet — no colour
    hl.parsed = _stage(LEDGER_LINE).parsed
    assert hl(Text(LEDGER_LINE)).spans  # every token carries a style


# ---- pilot ------------------------------------------------------------------
async def _open(app, pilot):
    screen = LogBarScreen()
    await app.push_screen(screen)
    await wait_for(pilot, lambda: screen._refs is not None, message="refs never loaded")
    return screen


def _bar(screen) -> Input:
    return screen.query_one("#bar", Input)


def _label(screen) -> str:
    return str(screen.query_one("#field", Label).content)


def _type(screen, text, *, caret=None):
    """Drive the bar directly — a focused Input swallows key presses."""
    bar = _bar(screen)
    bar.value = text
    bar.cursor_position = len(text) if caret is None else caret
    screen.on_input_changed(Input.Changed(bar, text))


def test_state1_opens_on_an_empty_bar_with_the_invitation(fake_client, monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = await _open(app, pilot)
            assert _bar(screen).has_focus
            assert _label(screen) == "LOG"
            assert "↵ stages the line" in screen._hint()
            assert "Nothing staged" in _text(screen._staged_renderable())

    asyncio.run(scenario())


def test_state2_an_ambiguous_account_opens_the_picker(fake_client, monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = await _open(app, pilot)
            _type(screen, "tottus porongoche -38.60 $sig")
            assert [name for _, name in screen._picker.candidates] == [
                "BCP Signature PEN",
                "BCP Signature USD",
            ]
            assert '"$sig" matches 2 accounts' in screen._hint()
            assert screen._suggest_idx == 0
            screen.action_move(1)
            assert screen._suggest_idx == 1

    asyncio.run(scenario())


def test_state3_enter_completes_the_token_inside_the_line(fake_client, monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = await _open(app, pilot)
            _type(screen, "tottus porongoche -38.60 $sig")
            screen.action_move(1)  # the USD one
            screen.on_input_submitted()
            assert _bar(screen).value == "tottus porongoche -38.60 $BCP Signature USD"
            assert screen._picker is None  # it resolves now, so the picker closes
            assert screen._staged == []  # completing is not staging
            assert "completed the token in place" in screen._hint()

    asyncio.run(scenario())


def test_state4_enter_stages_the_line_and_clears_the_bar(fake_client, monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = await _open(app, pilot)
            _type(screen, LEDGER_LINE)
            screen.on_input_submitted()
            assert _bar(screen).value == ""
            assert [e.line for e in screen._staged] == [LEDGER_LINE]
            assert not screen._staged[0].routing.to_inbox
            out = _text(screen._staged_renderable())
            assert "1 staged" in out and "-38.60 PEN" in out

    asyncio.run(scenario())


def test_state5_an_incomplete_line_stages_as_an_inbox_draft(fake_client, monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = await _open(app, pilot)
            _type(screen, LEDGER_LINE)
            screen.on_input_submitted()
            _type(screen, NO_ACCOUNT_LINE)
            screen.on_input_submitted()
            assert screen._staged[1].routing.to_inbox
            out = _text(screen._staged_renderable(), width=160)
            assert "1 to the ledger" in out
            assert "1 to the Inbox" in out
            assert "the line names no account" in out

    asyncio.run(scenario())


def test_state6_arrows_pick_a_staged_row_and_enter_lifts_the_typed_line(fake_client, monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = await _open(app, pilot)
            for line in (LEDGER_LINE, NO_ACCOUNT_LINE):
                _type(screen, line)
                screen.on_input_submitted()

            screen.action_move(1)  # bar is empty, so the arrows drive the list
            assert screen._picked == 0
            screen.action_move(1)
            assert screen._picked == 1

            screen.on_input_submitted()  # lift it
            assert _bar(screen).value == NO_ACCOUNT_LINE  # the raw line, verbatim
            assert screen._editing == 1
            assert _label(screen) == "EDIT 2"
            assert "the line that made it" in screen._hint()

    asyncio.run(scenario())


def test_a_lifted_row_is_replaced_in_place_not_appended(fake_client, monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = await _open(app, pilot)
            for line in (LEDGER_LINE, NO_ACCOUNT_LINE):
                _type(screen, line)
                screen.on_input_submitted()
            screen.action_move(1)
            screen.action_move(1)
            screen.on_input_submitted()  # lift row 2

            fixed = NO_ACCOUNT_LINE + " $BCP PEN"
            _type(screen, fixed)
            screen.on_input_submitted()

            assert len(screen._staged) == 2
            assert screen._staged[1].line == fixed
            assert not screen._staged[1].routing.to_inbox  # it has an account now
            assert screen._editing is None
            assert _label(screen) == "LOG"

    asyncio.run(scenario())


def test_ctrl_x_drops_the_picked_row(fake_client, monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = await _open(app, pilot)
            for line in (LEDGER_LINE, NO_ACCOUNT_LINE):
                _type(screen, line)
                screen.on_input_submitted()
            screen.action_move(1)
            screen.action_drop_row()
            assert [e.line for e in screen._staged] == [NO_ACCOUNT_LINE]

    asyncio.run(scenario())


def test_ctrl_x_beats_the_inputs_own_cut_binding(fake_client, monkeypatch):
    """Textual's Input binds ctrl+x to `cut`; ours must win, or the key would
    edit the line instead of dropping the row."""
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = await _open(app, pilot)
            _type(screen, LEDGER_LINE)
            screen.on_input_submitted()
            screen.action_move(1)
            await pilot.press("ctrl+x")
            await wait_for(pilot, lambda: not screen._staged, message="ctrl+x never dropped it")

    asyncio.run(scenario())


def test_state9_escape_with_rows_staged_asks_before_leaving(fake_client, monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = await _open(app, pilot)
            _type(screen, LEDGER_LINE)
            screen.on_input_submitted()

            screen.action_back()
            await wait_for(pilot, lambda: isinstance(app.screen, DiscardStagedModal))
            await pilot.press("enter")  # keep editing
            await wait_for(pilot, lambda: app.screen is screen)
            assert screen._staged  # nothing was thrown away

            screen.action_back()
            await wait_for(pilot, lambda: isinstance(app.screen, DiscardStagedModal))
            await pilot.press("d")  # discard
            await wait_for(pilot, lambda: app.screen is not screen)

    asyncio.run(scenario())


def test_escape_unpicks_before_it_offers_to_leave(fake_client, monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = await _open(app, pilot)
            _type(screen, LEDGER_LINE)
            screen.on_input_submitted()
            screen.action_move(1)
            assert screen._picked == 0

            screen.action_back()
            assert screen._picked is None
            assert app.screen is screen  # no modal yet

    asyncio.run(scenario())


def test_escape_on_an_empty_screen_just_leaves(fake_client, monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = await _open(app, pilot)
            screen.action_back()
            await wait_for(pilot, lambda: app.screen is not screen)

    asyncio.run(scenario())


def test_staging_writes_nothing_phase_3_has_no_save(fake_client, monkeypatch):
    _patch(monkeypatch)

    async def scenario():
        app = ExpenseApp()
        async with app.run_test() as pilot:
            screen = await _open(app, pilot)
            for line in (LEDGER_LINE, NO_ACCOUNT_LINE, AHEAD_LINE):
                _type(screen, line)
                screen.on_input_submitted()
            await pilot.press("ctrl+s")
            await pilot.pause()  # let the (unbound) chord settle, then assert a non-event
            assert len(screen._staged) == 3
            assert fake_client.calls == []

    asyncio.run(scenario())


def test_the_plus_key_still_opens_the_old_form(fake_client, monkeypatch):
    """Phase 3 is unreachable by design — phase 4 flips this door."""
    import inspect

    from expense.tui.screens._base import LogTransactionMixin
    from expense.tui.screens.quick_log import QuickAddLogScreen

    source = inspect.getsource(LogTransactionMixin.action_log_transaction)
    assert QuickAddLogScreen.__name__ in source
    assert LogBarScreen.__name__ not in source
