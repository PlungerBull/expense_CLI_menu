"""Pure parse/plan unit tests for `expense import` — no network, no xlsx file."""

import pytest

from expense.import_ import plan as plan_mod
from expense.import_.apply import chunked
from expense.import_.parse import (
    ImportFormatError,
    OpeningRow,
    ParsedRow,
    amount_to_cents,
    build_column_index,
    is_opening_title,
    parse_sheet,
    serial_to_iso,
    to_iso_date,
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
    parsed, openings, skipped = parse_sheet(_sheet([_row(2, Notas="Regalo Mama")]))
    assert skipped == []
    (row,) = parsed
    assert isinstance(row, ParsedRow)
    assert row.title == "Groomers"
    assert row.category == "WANTS"
    assert row.hashtag == "Salidas"
    assert row.amount_cents == -4400
    assert row.currency == "PEN"
    assert row.description == "Regalo Mama"
    assert row.date_iso == "2022-12-01"


@pytest.mark.parametrize("tc", [3.68, "None", "garbage", -3.629])
def test_parse_usd_row_ignores_tc_column(tc):
    """The T.C. cell — present, absent, or garbage — is ignored: the engine
    converts at read time and rejects per-row rates (2026-08-05 rework)."""
    parsed, openings, skipped = parse_sheet(
        _sheet([_row(2, Moneda="USD", Monto=-100, **{"T.C.": tc})])
    )
    assert skipped == []
    (row,) = parsed
    assert row.currency == "USD"


def test_sheet_without_tc_column_imports():
    headers = [h for h in HEADERS if h != "T.C."]
    raw = _row(2)
    cells = [c for h, c in zip(HEADERS, raw.cells, strict=True) if h != "T.C."]
    parsed, openings, skipped = parse_sheet(
        SheetData(headers=list(headers), rows=[RawRow(line=2, cells=cells)])
    )
    assert skipped == []
    assert len(parsed) == 1


def test_text_iso_date_cell_imports_not_skipped():
    """A date column typed as text (not an Excel serial) must import (backlog 6.4)."""
    parsed, openings, skipped = parse_sheet(_sheet([_row(2, Fecha="2022-12-01")]))
    assert skipped == []
    assert parsed[0].date_iso == "2022-12-01"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2022-12-01", "2022-12-01"),  # ISO text date
        ("2022-12-01 10:30:00", "2022-12-01"),  # ISO text datetime → date part
        ("46170", "2026-05-28"),  # numeric-string serial still handled
        (44896, "2022-12-01"),  # int serial
        ("not-a-date", None),  # genuinely unparseable
        ("2022/12/01", None),  # non-ISO separator is not silently accepted
    ],
)
def test_to_iso_date_shapes(value, expected):
    assert to_iso_date(value) == expected


def test_literal_none_notas_is_empty_description():
    (parsed, _, _) = parse_sheet(_sheet([_row(2, Notas="None")]))
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
    ],
)
def test_skip_reasons(over, reason):
    _, _, skipped = parse_sheet(_sheet([_row(2, **over)]))
    assert [s.reason for s in skipped] == [reason]


def test_fully_empty_row_ignored_not_reported():
    empty = RawRow(line=2, cells=[None] * len(HEADERS))
    parsed, openings, skipped = parse_sheet(_sheet([empty]))
    assert parsed == []
    assert skipped == []


# --- plan ------------------------------------------------------------------


def test_mixed_currency_account_splits():
    rows = [
        _row(2, Cuenta="BCP Oro", Moneda="PEN"),
        _row(3, Cuenta="BCP Oro", Moneda="USD", Monto=-100, **{"T.C.": 3.68}),
    ]
    parsed, openings, skipped = parse_sheet(_sheet(rows))
    plan = plan_mod.build_plan(parsed, openings, skipped)
    specs = {(a.name, a.currency) for a in plan.accounts}
    assert specs == {("BCP Oro", "PEN"), ("BCP Oro", "USD")}


def test_category_and_hashtag_dedup_case_insensitive():
    rows = [
        _row(2, CATEGORY="WANTS", HASHTAG="Gastos Hogar"),
        _row(3, CATEGORY="wants", HASHTAG="Gastos hogar"),
    ]
    parsed, openings, skipped = parse_sheet(_sheet(rows))
    plan = plan_mod.build_plan(parsed, openings, skipped)
    assert len(plan.categories) == 1
    assert len(plan.hashtags) == 1


def test_tx_id_deterministic_and_line_sensitive():
    a = ParsedRow(2, "t", "c", "h", "2022-12-01", -100, "PEN", "BCP PEN", None)
    again = ParsedRow(2, "t", "c", "h", "2022-12-01", -100, "PEN", "BCP PEN", None)
    other_line = ParsedRow(3, "t", "c", "h", "2022-12-01", -100, "PEN", "BCP PEN", None)
    assert plan_mod.tx_id_for(a) == plan_mod.tx_id_for(again)
    assert plan_mod.tx_id_for(a) != plan_mod.tx_id_for(other_line)


def test_identical_content_on_two_lines_both_planned():
    """Dedup is line-keyed, not content-based: identical rows on different
    sheet lines both import — the unreachable content-skip that advertised
    otherwise was deleted (backlog 6.4e)."""
    a = ParsedRow(2, "t", "c", "h", "2022-12-01", -100, "PEN", "BCP PEN", None)
    b = ParsedRow(3, "t", "c", "h", "2022-12-01", -100, "PEN", "BCP PEN", None)
    plan = plan_mod.build_plan([a, b], [], [])
    assert [r.line for r in plan.rows] == [2, 3]
    assert plan.tx_ids[2] != plan.tx_ids[3]
    assert plan.skipped == []


def test_chunked_sizes():
    sizes = [len(c) for c in chunked(list(range(450)), 200)]
    assert sizes == [200, 200, 50]


# --- opening balances (SALDO INICIAL) ---------------------------------------


@pytest.mark.parametrize(
    "title,expected",
    [
        ("SALDO INICIAL", True),
        ("saldo inicial", True),
        ("  Saldo   Inicial  ", True),  # whitespace collapsed
        ("SALDO INICIAL 2022", False),  # extra words don't match
        ("Groomers", False),
    ],
)
def test_is_opening_title(title, expected):
    assert is_opening_title(title) is expected


def test_opening_row_detected_without_category_or_hashtag():
    """SALDO INICIAL rows bypass the category/hashtag requirement."""
    raw = _row(2, Descripcion="SALDO INICIAL", CATEGORY="None", HASHTAG="None", Monto=3500)
    parsed, openings, skipped = parse_sheet(_sheet([raw]))
    assert parsed == []
    assert skipped == []
    (row,) = openings
    assert isinstance(row, OpeningRow)
    assert row.title == "SALDO INICIAL"
    assert row.account == "BCP PEN"
    assert row.amount_cents == 350000
    assert row.date_iso == "2022-12-01"


def test_opening_row_still_validates_shared_fields():
    """Account/currency/date/amount rules apply to opening rows too."""
    _, openings, skipped = parse_sheet(
        _sheet([_row(2, Descripcion="SALDO INICIAL", Cuenta="", CATEGORY="None")])
    )
    assert openings == []
    assert [s.reason for s in skipped] == ["missing-account"]

    _, openings, skipped = parse_sheet(
        _sheet([_row(2, Descripcion="SALDO INICIAL", Monto=0, HASHTAG="None")])
    )
    assert openings == []
    assert [s.reason for s in skipped] == ["zero-amount"]


def test_opening_usd_row_needs_no_rate():
    """A USD opening row without a T.C. value imports — rates are engine-side now."""
    _, openings, skipped = parse_sheet(
        _sheet([_row(2, Descripcion="SALDO INICIAL", Moneda="USD", Monto=100, **{"T.C.": "None"})])
    )
    assert skipped == []
    assert [o.currency for o in openings] == ["USD"]


def test_plan_dedups_openings_per_account_keeping_first():
    rows = [
        _row(2, Descripcion="SALDO INICIAL", Monto=3500),
        _row(3, Descripcion="SALDO INICIAL", Monto=9999),  # same account+currency
        _row(4, Descripcion="SALDO INICIAL", Cuenta="Interbank", Monto=100),
    ]
    parsed, openings, skipped = parse_sheet(_sheet(rows))
    plan = plan_mod.build_plan(parsed, openings, skipped)
    assert [o.line for o in plan.openings] == [2, 4]
    (dup,) = [s for s in plan.skipped if s.reason == "duplicate-opening"]
    assert dup.line == 3
    assert "line 2" in dup.detail
    assert set(plan.opening_ids) == {2, 4}


def test_plan_accounts_include_opening_only_accounts():
    """An account whose only sheet row is its SALDO INICIAL still gets created."""
    rows = [
        _row(2),  # ordinary row, BCP PEN
        _row(3, Descripcion="SALDO INICIAL", Cuenta="Solo Cuenta", Monto=500),
    ]
    parsed, openings, skipped = parse_sheet(_sheet(rows))
    plan = plan_mod.build_plan(parsed, openings, skipped)
    assert {(a.name, a.currency) for a in plan.accounts} == {
        ("BCP PEN", "PEN"),
        ("Solo Cuenta", "PEN"),
    }


def test_opening_id_deterministic_and_line_sensitive():
    a = OpeningRow(2, "SALDO INICIAL", "BCP PEN", "PEN", "2022-12-01", 3500)
    again = OpeningRow(2, "SALDO INICIAL", "BCP PEN", "PEN", "2022-12-01", 3500)
    other = OpeningRow(3, "SALDO INICIAL", "BCP PEN", "PEN", "2022-12-01", 3500)
    assert plan_mod.tx_id_for(a) == plan_mod.tx_id_for(again)
    assert plan_mod.tx_id_for(a) != plan_mod.tx_id_for(other)
