"""Pure grammar tests for expense/quickadd/ — no Textual, no network, no clock.

The checklist is the token table in docs/mockups/expense-world-quickadd-batch.html
plus the sharp-edges list in docs/todo.md item 1. `today` is passed in, so
nothing here depends on the machine's date.
"""

from datetime import date

import pytest

from expense.quickadd.money import amount_to_text, parse_amount
from expense.quickadd.parse import parse
from expense.quickadd.when import parse_date

TODAY = date(2026, 8, 20)

# Two accounts share "Signature" so `$sig` is genuinely ambiguous (mockup pane
# 2); "CAJA" is a prefix of "CAJA CHICA" so exact-beats-contains gets exercised.
ACCOUNTS = [
    ("a1", "BCP Signature USD", "USD"),
    ("a2", "BCP PEN", "PEN"),
    ("a3", "Mi Signature", "PEN"),
    ("a4", "Nico", "PEN"),
    ("a5", "Efectivo", "PEN"),
]
CATEGORIES = [("c1", "KORAKUEN"), ("c2", "TRANSPORTE"), ("c3", "WANTS")]
HASHTAGS = [("t1", "CAJA"), ("t2", "TAXI"), ("t3", "CAJA CHICA"), ("t4", "Viajes")]


def _p(line: str, *, today: date = TODAY):
    return parse(line, accounts=ACCOUNTS, categories=CATEGORIES, hashtags=HASHTAGS, today=today)


# --- money ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [("-99.92", -9992), ("99", 9900), ("+12.5", 1250), ("0", 0), ("abc", None), ("", None)],
)
def test_parse_amount(text, expected):
    """Moved here from test_tui_quick_log.py 2026-08-25 with the function."""
    assert parse_amount(text) == expected


def test_amount_to_text_roundtrips():
    assert amount_to_text(-9992) == "-99.92"
    assert parse_amount(amount_to_text(-123456)) == -123456


# --- the amount token -------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("tottus -38.60", -3860),  # the mockup's own example
        ("bonus +2450", 245000),  # + is income, literally
        ("mercado -1,311.97", -131197),  # thousands separator is part of the charset
        ("alquiler -$1800", -180000),  # $ + digits is decoration, not a currency
        ("coca-cola", None),  # a sign mid-word is a title, not money
        ("T-800", None),
        ("covid-19", None),
        ("recibo 2450", None),  # no sign, no amount
        ("recibo $1800", None),  # ...not even with the money sigil
    ],
)
def test_amount_shapes(line, expected):
    assert _p(line).amount_cents == expected


def test_first_sign_wins():
    """`hoy +30 no -30` is +30; the loser stays in the title (docs/todo.md)."""
    result = _p("hoy +30 no -30")
    assert result.amount_cents == 3000
    assert result.title == "no -30"


def test_unsigned_digits_stay_in_the_title():
    assert _p("ruta 2450 $efectivo @wants").title == "ruta 2450"


# --- the reference tokens ---------------------------------------------------


def test_sigils_resolve_to_ids():
    result = _p("tottus -38.60 $efectivo @korakuen #caja")
    assert (result.account_id, result.category_id, result.hashtag_ids) == (
        "a5",
        "c1",
        ("t1",),
    )


def test_dollar_splits_on_the_next_character():
    """Letters name an account, digits are money — no account starts with one."""
    assert _p("x -1 $nico").account_id == "a4"
    assert _p("x -1 $1800").account_id is None


def test_multi_word_names_need_no_quotes():
    assert _p("pago -5 $bcp pen").account_id == "a2"
    assert _p("pago -5 #caja chica").hashtag_ids == ("t3",)


def test_exact_name_beats_a_longer_one_that_contains_it():
    """`#caja` is CAJA, not CAJA CHICA — equality wins before contains."""
    assert _p("pago -5 #caja").hashtag_ids == ("t1",)


def test_a_name_never_swallows_the_next_token():
    """The lookahead stops at a sigil or an amount, so `$bcp` cannot eat `-5`."""
    result = _p("$bcp pen -5 @wants")
    assert (result.account_id, result.amount_cents, result.category_id) == ("a2", -500, "c3")


def test_hashtags_repeat_and_the_rest_are_first_wins():
    result = _p("x -5 #caja #taxi $nico $efectivo @wants @korakuen")
    assert result.hashtag_ids == ("t1", "t2")
    assert (result.account_id, result.category_id) == ("a4", "c3")
    # The losing tokens are not silently applied — they read as title text.
    assert result.title == "x $efectivo @korakuen"


def test_the_same_tag_twice_is_deduped_not_rejected():
    assert _p("x -5 #caja #caja").hashtag_ids == ("t1",)


@pytest.mark.parametrize(
    ("line", "kind", "text", "candidates"),
    [
        ("x -5 $sig", "account", "sig", 2),  # ambiguous — the picker's case
        ("x -5 $zzz", "account", "zzz", 0),  # nothing matches
        ("x -5 @zzz", "category", "zzz", 0),
        ("x -5 #zzz", "hashtag", "zzz", 0),  # never created behind your back
    ],
)
def test_unresolved_names_are_reported_with_their_candidates(line, kind, text, candidates):
    """2026-08-25: no match and several matches both go unresolved, carrying
    whatever was found, so a caller can open a picker on it."""
    (found,) = _p(line).unresolved
    assert (found.kind, found.text, len(found.candidates)) == (kind, text, candidates)


def test_matching_is_contains_anywhere_and_case_insensitive():
    """Picked 2026-08-25 over whole-name and starts-with, matching every
    existing TUI picker."""
    assert _p("x -5 $ECTIV").account_id == "a5"


# --- the note ---------------------------------------------------------------


def test_note_runs_to_the_end_of_the_line():
    result = _p("cena -5 // pagué yo, dividir después")
    assert result.note == "pagué yo, dividir después"
    assert result.title == "cena"


def test_a_pasted_url_survives():
    """`//` only opens a note after a space — that is what protects https://."""
    result = _p("mira https://x.com/y -12")
    assert result.note is None
    assert result.title == "mira https://x.com/y"


def test_note_at_the_start_of_the_line():
    assert _p("// solo una nota").note == "solo una nota"


# --- the date ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("hoy", "2026-08-20"),
        ("today", "2026-08-20"),
        ("ayer", "2026-08-19"),
        ("yesterday", "2026-08-19"),
        ("mañana", "2026-08-21"),
        ("manana", "2026-08-21"),  # unaccented spelling accepted
        ("tomorrow", "2026-08-21"),
        ("HOY", "2026-08-20"),  # case-insensitive
        ("18/08/2026", "2026-08-18"),  # dd/mm/yyyy
        ("2026/08/18", "2026-08-18"),  # yyyy/mm/dd — 4-digit-first disambiguates
        ("2026-08-18", "2026-08-18"),  # the dashed form --date takes (2026-08-25)
        ("18/08/26", "2026-08-18"),  # yy -> 20yy
        ("32/13/2026", None),  # date-shaped but impossible
        ("18-08-2026", None),  # dashes are ISO-only, so this is not a date
        ("tottus", None),  # ordinary word
    ],
)
def test_date_words_and_shapes(word, expected):
    found, _ = parse_date(word, TODAY)
    assert found == expected


def test_omitted_date_is_today_and_says_so():
    result = _p("tottus -5")
    assert (result.date, result.date_given) == ("2026-08-20", False)


def test_first_date_wins():
    assert _p("x -5 ayer mañana").date == "2026-08-19"


def test_an_impossible_date_is_reported_not_swallowed():
    """It neither becomes a title word nor silently defaults to today."""
    result = _p("x -5 32/13/2026")
    assert result.date_given is False
    assert [(u.kind, u.text) for u in result.unresolved] == [("date", "32/13/2026")]
    assert result.title == "x"


# --- the title, and what is left --------------------------------------------


def test_the_rest_is_the_title_in_order():
    assert _p("tottus porongoche -5 $efectivo hoy").title == "tottus porongoche"


def test_missing_lists_only_the_required_fields():
    assert _p("").missing == ("title", "amount", "account", "category")
    assert _p("tottus -5 $efectivo @wants").missing == ()


def test_is_complete_needs_every_name_resolved_too():
    """A row with all four fields but an ambiguous account is not complete —
    routing (docs/todo.md item 1) is still the screen's call."""
    assert _p("tottus -5 $efectivo @wants").is_complete is True
    assert _p("tottus -5 $sig @wants").is_complete is False


def test_hashtags_and_note_are_optional():
    assert _p("tottus -5 $efectivo @wants").is_complete is True


# --- spans ------------------------------------------------------------------


def test_spans_cover_every_token_in_source_order():
    """A caller colours the line off these without parsing it again."""
    line = "tottus -38.60 $sig @korakuen #caja hoy // nota"
    spans = [(s.kind, line[s.start : s.end], s.resolved) for s in _p(line).spans]
    assert spans == [
        ("title", "tottus", True),
        ("amount", "-38.60", True),
        ("account", "$sig", False),  # ambiguous -> the error slot
        ("category", "@korakuen", True),
        ("hashtag", "#caja", True),
        ("date", "hoy", True),
        ("note", "// nota", True),
    ]


def test_a_multi_word_span_covers_every_word_it_took():
    (span,) = [s for s in _p("pago -5 $bcp pen").spans if s.kind == "account"]
    assert (span.start, span.end, span.text) == (8, 16, "$bcp pen")


# --- shape of the reference arguments ---------------------------------------


def test_extra_columns_on_a_reference_row_are_ignored():
    """account_choices() hands back (id, name, currency) — it passes straight
    through, unconverted (docs/todo.md item 1 phase 1)."""
    assert _p("x -5 $bcp pen").account_id == "a2"


def test_malformed_reference_rows_are_skipped_not_crashed_on():
    result = parse(
        "x -5 $ok",
        accounts=[("a1",), (None, "Bad"), ("a2", None), ("a3", "  "), ("a4", "OK")],
        categories=[],
        hashtags=[],
        today=TODAY,
    )
    assert result.account_id == "a4"


def test_an_empty_line_parses_to_nothing():
    result = _p("   ")
    assert (result.title, result.amount_cents, result.spans) == ("", None, ())
