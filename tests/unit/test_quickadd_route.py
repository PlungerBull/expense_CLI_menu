"""Where a parsed line goes — the rule both quick-add surfaces share.

The routing table, not the grammar: `test_quickadd_parse.py` owns what a line
*says*, this file owns what happens to it. Pure — no HTTP, no config.
"""

from datetime import date

from expense.quickadd.parse import parse
from expense.quickadd.route import INBOX, LEDGER, route

ACCOUNTS = [
    ("a-pen", "BCP Signature PEN", "PEN"),
    ("a-usd", "BCP Signature USD", "USD"),
    ("a-bcp", "BCP PEN", "PEN"),
]
CATEGORIES = [("c-kor", "KORAKUEN"), ("c-tra", "TRANSPORTE")]
HASHTAGS = [("h-caja", "CAJA CHICA"), ("h-taxi", "TAXI")]
TODAY = date(2026, 8, 20)


def _route(line, *, today=TODAY):
    parsed = parse(line, accounts=ACCOUNTS, categories=CATEGORIES, hashtags=HASHTAGS, today=today)
    return route(parsed, today)


def test_complete_and_dated_today_reaches_the_ledger():
    result = _route("tottus -38.60 $BCP Signature PEN @korakuen #caja hoy")
    assert result.target == LEDGER
    assert result.reasons == ()
    assert not result.to_inbox


def test_a_past_date_is_still_the_ledger():
    assert _route("tottus -38.60 $BCP PEN @korakuen 18/8/2026").target == LEDGER


def test_dated_ahead_is_a_draft_even_when_complete():
    result = _route("alquiler -1800 $BCP PEN @hogar manana")
    assert result.target == INBOX
    assert "it is dated ahead" in result.reasons


def test_each_missing_required_field_is_its_own_reason():
    result = _route("-3.50")
    assert result.target == INBOX
    assert result.reasons == (
        "the line has no title",
        "the line names no account",
        "the line names no category",
    )


def test_a_number_without_a_sign_is_not_an_amount():
    """The sign is what makes a number money — 'gasté 38' is a title."""
    result = _route("gaste 38 $BCP PEN @korakuen")
    assert "the line has no amount — a number needs a sign to be one" in result.reasons


def test_an_ambiguous_name_says_how_many_it_matched():
    result = _route("tottus -38.60 $signature @korakuen")
    assert result.reasons == ('"$signature" matches 2 accounts',)


def test_a_name_that_matched_nothing_reads_differently():
    """A typo and a too-short name are different problems with different fixes."""
    result = _route("tottus -38.60 $nowhere @korakuen")
    assert result.reasons == ('"$nowhere" matches no accounts',)


def test_an_unresolved_name_is_not_also_reported_as_missing():
    """`missing` and `unresolved` both name the account; the reader sees one."""
    result = _route("tottus -38.60 $signature")
    assert result.reasons == (
        "the line names no category",
        '"$signature" matches 2 accounts',
    )


def test_an_unmatched_hashtag_drafts_the_row():
    """Optional, but never invented — a typo would otherwise become a tag."""
    result = _route("tottus -38.60 $BCP PEN @korakuen #nope")
    assert result.target == INBOX
    assert result.reasons == ('"#nope" matches no hashtags',)


def test_the_plural_of_category_reads_as_english():
    """ "2 categorys" would be the giveaway that a machine wrote the sentence."""
    result = _route("tottus -38.60 $BCP PEN @o")
    assert result.reasons == ('"@o" matches 2 categories',)


def test_an_impossible_date_drafts_rather_than_sliding_into_the_title():
    result = _route("tottus -38.60 $BCP PEN @korakuen 32/13/2026")
    assert result.target == INBOX
    assert '"32/13/2026" is not a real date' in result.reasons


def test_several_problems_are_all_reported():
    result = _route("-3.50 $signature manana")
    assert result.target == INBOX
    assert len(result.reasons) == 4
