"""Real-workbook tests for expense/import_/reader.py — openpyxl actually runs
(backlog 6.5); the rest of the import suite mocks read_workbook.
"""

import sys

import pytest

openpyxl = pytest.importorskip("openpyxl")

from expense.import_.parse import parse_sheet  # noqa: E402
from expense.import_.reader import (  # noqa: E402
    ImportDependencyError,
    ImportFileError,
    read_workbook,
)

_HEADERS = [
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
# Excel serial 44896 == 2022-12-01; amounts are majors in the sheet.
_ROW = ["Groomers", "WANTS", "Salidas", 44896, -44, "BCP PEN", None, "PEN", -44, None, None]


def _write_xlsx(tmp_path, rows, *, sheet="Data", headers=_HEADERS) -> str:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    if headers is not None:
        ws.append(headers)
    for row in rows:
        ws.append(row)
    path = tmp_path / "import.xlsx"
    wb.save(path)
    return str(path)


def test_read_workbook_happy(tmp_path):
    second = list(_ROW)
    second[0] = "Vet"
    sheet = read_workbook(_write_xlsx(tmp_path, [_ROW, second]))
    assert sheet.headers == _HEADERS
    assert len(sheet.rows) == 2
    assert sheet.rows[0].line == 2 and sheet.rows[0].cells == _ROW  # 1-based, data from row 2
    assert sheet.rows[1].line == 3 and sheet.rows[1].cells[0] == "Vet"


def test_read_then_parse_roundtrip(tmp_path):
    """Lock the real reader↔parser contract: serial dates, major amounts, headers."""
    parsed, skipped = parse_sheet(read_workbook(_write_xlsx(tmp_path, [_ROW])))
    assert skipped == []
    assert len(parsed) == 1
    row = parsed[0]
    assert row.line == 2
    assert row.title == "Groomers" and row.account == "BCP PEN"
    assert row.date_iso == "2022-12-01"  # Excel serial resolved
    assert row.amount_cents == -4400  # majors → cents
    assert row.currency == "PEN" and row.exchange_rate is None


def test_missing_file(tmp_path):
    with pytest.raises(ImportFileError, match="File not found"):
        read_workbook(str(tmp_path / "nope.xlsx"))


def test_missing_sheet_lists_present_sheets(tmp_path):
    path = _write_xlsx(tmp_path, [_ROW], sheet="Otra")
    with pytest.raises(ImportFileError, match="Sheet 'Data' not found.*Otra"):
        read_workbook(path)


def test_empty_sheet(tmp_path):
    path = _write_xlsx(tmp_path, [], headers=None)
    with pytest.raises(ImportFileError, match="is empty"):
        read_workbook(path)


def test_unreadable_file(tmp_path):
    path = tmp_path / "garbage.xlsx"
    path.write_text("this is not a zip archive")
    with pytest.raises(ImportFileError, match="Could not open"):
        read_workbook(str(path))


def test_openpyxl_missing_raises_dependency_error(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "openpyxl", None)  # import → ImportError
    with pytest.raises(ImportDependencyError, match="pip install openpyxl"):
        read_workbook(str(tmp_path / "any.xlsx"))
