"""Turn parsed rows into an ImportPlan: distinct resources + deterministic ids.

Transaction ids are uuid5 over stable row content, so re-running the same sheet
yields the same ids — an accidental second --apply can't create duplicates.
Category/hashtag names are deduplicated case-insensitively to match the engine's
case-insensitive uniqueness.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field

from expense.import_ import mapping
from expense.import_.parse import ParsedRow, SkippedRow


@dataclass(frozen=True)
class AccountSpec:
    name: str
    currency: str


@dataclass
class ImportPlan:
    rows: list[ParsedRow]
    tx_ids: dict[int, str]  # row.line -> deterministic uuid
    accounts: list[AccountSpec]  # distinct (name, currency)
    categories: list[str]  # distinct names, first-seen casing
    hashtags: list[str]  # distinct names, first-seen casing
    skipped: list[SkippedRow] = field(default_factory=list)


def stable_row_key(row: ParsedRow) -> str:
    return "|".join(
        [
            row.date_iso,
            row.account.strip().casefold(),
            row.currency,
            str(row.amount_cents),
            row.title,
            str(row.line),
        ]
    )


def tx_id_for(row: ParsedRow) -> str:
    return str(uuid.uuid5(mapping.IMPORT_NAMESPACE, stable_row_key(row)))


def _distinct_ci(names: Iterable[str]) -> list[str]:
    """Case-insensitive distinct, keeping the first-seen original casing."""
    seen: dict[str, str] = {}
    for name in names:
        key = name.strip().casefold()
        if key not in seen:
            seen[key] = name.strip()
    return list(seen.values())


def build_plan(parsed: list[ParsedRow], skipped: list[SkippedRow]) -> ImportPlan:
    skips = list(skipped)
    rows: list[ParsedRow] = []
    tx_ids: dict[int, str] = {}
    seen_ids: set[str] = set()
    for row in parsed:
        tid = tx_id_for(row)
        if tid in seen_ids:
            skips.append(SkippedRow(row.line, "duplicate-row"))
            continue
        seen_ids.add(tid)
        tx_ids[row.line] = tid
        rows.append(row)

    accounts: list[AccountSpec] = []
    acct_seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row.account.strip().casefold(), row.currency)
        if key not in acct_seen:
            acct_seen.add(key)
            accounts.append(AccountSpec(name=row.account.strip(), currency=row.currency))

    return ImportPlan(
        rows=rows,
        tx_ids=tx_ids,
        accounts=accounts,
        categories=_distinct_ci(row.category for row in rows),
        hashtags=_distinct_ci(row.hashtag for row in rows),
        skipped=skips,
    )
