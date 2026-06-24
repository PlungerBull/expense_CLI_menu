"""Column mapping + constants for the spreadsheet import.

Single source of truth for the sheet layout. Columns are matched by HEADER
NAME (case/space-insensitive), not position, so the importer survives column
reordering — which has already happened in this file's history. To support a
differently-shaped sheet later, add its labels here; the pipeline is otherwise
layout-agnostic.
"""

import uuid

#: Worksheet that holds the transaction rows.
SHEET_NAME = "Data"

#: Canonical field -> the normalized header label it maps to.
FIELD_HEADERS = {
    "title": "descripcion",
    "category": "category",
    "hashtag": "hashtag",
    "date": "fecha",
    "amount": "monto",
    "account": "cuenta",
    "rate": "t.c.",
    "currency": "moneda",
    "description": "notas",
}

#: Every field except ``description`` must be present in the header row.
REQUIRED_FIELDS = frozenset(FIELD_HEADERS) - {"description"}

#: Currencies the engine accepts (schema-locked to USD/PEN).
VALID_CURRENCIES = frozenset({"PEN", "USD"})

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
