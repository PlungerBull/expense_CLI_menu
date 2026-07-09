"""Pure parse/plan unit tests for `expense import` — no network, no xlsx file."""

import pytest

from expense.import_ import plan as plan_mod
from expense.import_.apply import chunked
from expense.import_.parse import (
    ImportFormatError,
    ParsedRow,
    amount_to_cents,
    build_column_index,
    parse_sheet,
    serial_to_iso,
)
from expense.import_.reader import RawRow, SheetData

HEADERS = [
    "Descripcion",
    "CATEGORY",
    "HASHTAG",
    "Fecha",
    "Monto",
    "Cuenta",
    "T.C.",
    "Moneda",
    "Solarizado",
    "Estado Cuenta",
    "Notas",
]


def _row(line: int, **over: object) -> RawRow:
    base = {
        "Descripcion": "Groomers",
        "CATEGORY": "WANTS",
        "HASHTAG": "Salidas",
        "Fecha": 44896,
        "Monto": -44,
        "Cuenta": "BCP PEN",
        "T.C.": "None",
        "Moneda": "PEN",
        "Solarizado": -44,
        "Estado Cuenta": "None",
        "Notas": "None",
    }
    base.update(over)
    return RawRow(line=line, cells=[base[h] for h in HEADERS])


def _sheet(rows: list[RawRow]) -> SheetData:
    return SheetData(headers=list(HEADERS), rows=rows)


# --- helpers ---------------------------------------------------------------


def test_serial_to_iso_known_dates():
    assert serial_to_iso(1) == "1899-12-31"  # epoch anchor (1899-12-30 + 1)
    assert serial_to_iso(44896) == "2022-12-01"  # min date in the real sheet
    assert serial_to_iso("46170") == "2026-05-28"  # max date; string input accepted


@pytest.mark.parametrize(
    "value,expected",
    [
        (-132.80000000000001, -13280),
        (-68.2, -6820),
        (3500, 350000),
        ("-4.99", -499),
        (0, 0),
    ],
)
def test_amount_to_cents(value, expected):
    assert amount_to_cents(value) == expected


def test_build_column_index_missing_required():
    with pytest.raises(ImportFormatError):
        build_column_index(["Descripcion", "Monto"])  # missing most columns


# --- row parsing -----------------------------------------------------------


def test_parse_pen_row_no_rate_and_description():
    parsed, skipped = parse_sheet(_sheet([_row(2, Notas="Regalo Mama")]))
    assert skipped == []
    (row,) = parsed
    assert isinstance(row, ParsedRow)
    assert row.title == "Groomers"
    assert row.category == "WANTS"
    assert row.hashtag == "Salidas"
    assert row.amount_cents == -4400
    assert row.currency == "PEN"
    assert row.exchange_rate is None
    assert row.description == "Regalo Mama"
    assert row.date_iso == "2022-12-01"


def test_parse_usd_row_uses_tc_column():
    parsed, skipped = parse_sheet(_sheet([_row(2, Moneda="USD", Monto=-100, **{"T.C.": 3.68})]))
    assert skipped == []
    (row,) = parsed
    assert row.currency == "USD"
    assert row.exchange_rate == 3.68


def test_literal_none_notas_is_empty_description():
    (parsed, _) = parse_sheet(_sheet([_row(2, Notas="None")]))
    assert parsed[0].description is None


@pytest.mark.parametrize(
    "over,reason",
    [
        ({"Descripcion": "None"}, "missing-title"),
        ({"Cuenta": ""}, "missing-account"),
        ({"CATEGORY": "None"}, "missing-category"),
        ({"HASHTAG": ""}, "missing-hashtag"),
        ({"Moneda": "EUR"}, "unknown-currency"),
        ({"Fecha": "not-a-date"}, "bad-date"),
        ({"Monto": 0}, "zero-amount"),
        ({"Monto": "abc"}, "bad-amount"),
        ({"Moneda": "USD", "Monto": -100, "T.C.": "None"}, "usd-no-rate"),
        ({"Moneda": "USD", "Monto": 100, "T.C.": -3.629}, "bad-rate"),
    ],
)
def test_skip_reasons(over, reason):
    _, skipped = parse_sheet(_sheet([_row(2, **over)]))
    assert [s.reason for s in skipped] == [reason]


def test_fully_empty_row_ignored_not_reported():
    empty = RawRow(line=2, cells=[None] * len(HEADERS))
    parsed, skipped = parse_sheet(_sheet([empty]))
    assert parsed == []
    assert skipped == []


# --- plan ------------------------------------------------------------------


def test_mixed_currency_account_splits():
    rows = [
        _row(2, Cuenta="BCP Oro", Moneda="PEN"),
        _row(3, Cuenta="BCP Oro", Moneda="USD", Monto=-100, **{"T.C.": 3.68}),
    ]
    parsed, skipped = parse_sheet(_sheet(rows))
    plan = plan_mod.build_plan(parsed, skipped)
    specs = {(a.name, a.currency) for a in plan.accounts}
    assert specs == {("BCP Oro", "PEN"), ("BCP Oro", "USD")}


def test_category_and_hashtag_dedup_case_insensitive():
    rows = [
        _row(2, CATEGORY="WANTS", HASHTAG="Gastos Hogar"),
        _row(3, CATEGORY="wants", HASHTAG="Gastos hogar"),
    ]
    parsed, skipped = parse_sheet(_sheet(rows))
    plan = plan_mod.build_plan(parsed, skipped)
    assert len(plan.categories) == 1
    assert len(plan.hashtags) == 1


def test_tx_id_deterministic_and_line_sensitive():
    a = ParsedRow(2, "t", "c", "h", "2022-12-01", -100, "PEN", "BCP PEN", None, None)
    again = ParsedRow(2, "t", "c", "h", "2022-12-01", -100, "PEN", "BCP PEN", None, None)
    other_line = ParsedRow(3, "t", "c", "h", "2022-12-01", -100, "PEN", "BCP PEN", None, None)
    assert plan_mod.tx_id_for(a) == plan_mod.tx_id_for(again)
    assert plan_mod.tx_id_for(a) != plan_mod.tx_id_for(other_line)


def test_identical_content_on_two_lines_both_planned():
    """Dedup is line-keyed, not content-based: identical rows on different
    sheet lines both import — the unreachable content-skip that advertised
    otherwise was deleted (backlog 6.4e)."""
    a = ParsedRow(2, "t", "c", "h", "2022-12-01", -100, "PEN", "BCP PEN", None, None)
    b = ParsedRow(3, "t", "c", "h", "2022-12-01", -100, "PEN", "BCP PEN", None, None)
    plan = plan_mod.build_plan([a, b], [])
    assert [r.line for r in plan.rows] == [2, 3]
    assert plan.tx_ids[2] != plan.tx_ids[3]
    assert plan.skipped == []


def test_chunked_sizes():
    sizes = [len(c) for c in chunked(list(range(450)), 200)]
    assert sizes == [200, 200, 50]
