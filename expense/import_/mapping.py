"""Column mapping + constants for the spreadsheet import.

Single source of truth for the sheet layout. Columns are matched by HEADER
NAME (case/space-insensitive), not position, so the importer survives column
reordering — which has already happened in this file's history. Each field
accepts a tuple of labels, so a sheet re-exported with a renamed column keeps
importing; to support a differently-shaped sheet, add its label here and the
pipeline needs no other change.
"""

import uuid

from expense.currencies import SUPPORTED_CURRENCIES

#: Worksheet that holds the transaction rows. Matched case-insensitively —
#: see ``reader.read_workbook``.
SHEET_NAME = "Data"

#: Canonical field -> the normalized header labels it accepts, best first.
#: The first entry is the canonical spelling and is what the missing-column
#: error names. No two fields may share a label: `title` takes `description`
#: while the `description` field is fed by `notas`, and both can coexist on
#: one sheet.
FIELD_HEADERS = {
    "title": ("descripcion", "description", "titulo"),
    "category": ("category", "categoria"),
    "hashtag": ("hashtag",),
    "date": ("fecha",),
    "amount": ("monto",),
    "account": ("cuenta",),
    "currency": ("moneda",),
    "description": ("notas",),
}

#: Every field except ``description`` must be present in the header row.
REQUIRED_FIELDS = frozenset(FIELD_HEADERS) - {"description"}

#: Currencies the engine accepts — see expense/currencies.py for the
#: schema-lock provenance.
VALID_CURRENCIES = frozenset(SUPPORTED_CURRENCIES)

#: Deterministic-id namespace. DO NOT CHANGE — changing it breaks re-run dedup
#: (the same sheet must always produce the same transaction ids).
IMPORT_NAMESPACE = uuid.UUID("6f8a1e2c-3b4d-5e6f-7a8b-9c0d1e2f3a4b")

#: Colors assigned (cycled) to NEW categories. Hashtags need no color.
CATEGORY_PALETTE = [
    "#E57373",
    "#F06292",
    "#BA68C8",
    "#9575CD",
    "#7986CB",
    "#64B5F6",
    "#4FC3F7",
    "#4DD0E1",
    "#4DB6AC",
    "#81C784",
    "#AED581",
    "#DCE775",
    "#FFD54F",
    "#FFB74D",
    "#FF8A65",
    "#A1887F",
]


def normalize_header(label: object) -> str:
    """Lower-case + strip a header cell for tolerant matching."""
    return str(label).strip().casefold() if label is not None else ""
