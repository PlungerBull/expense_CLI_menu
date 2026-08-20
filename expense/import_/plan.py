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
from expense.import_.parse import OpeningRow, ParsedRow, SkippedRow


@dataclass(frozen=True)
class AccountSpec:
    """One account to ensure.

    ``name`` is what the engine is told; ``source_name`` is the raw sheet cell.
    They differ only when a sheet name spans several currencies — the engine
    gives every account exactly one currency, so such a name becomes several
    accounts and each needs its own display name (see ``_split_account_name``).
    Rows always resolve by ``source_name``, never by the derived one.
    """

    name: str
    currency: str
    source_name: str


@dataclass
class ImportPlan:
    rows: list[ParsedRow]
    tx_ids: dict[int, str]  # row.line -> deterministic uuid
    accounts: list[AccountSpec]  # distinct (name, currency)
    categories: list[str]  # distinct names, first-seen casing
    hashtags: list[str]  # distinct names, first-seen casing
    openings: list[OpeningRow] = field(default_factory=list)
    opening_ids: dict[int, str] = field(default_factory=dict)  # row.line -> uuid
    skipped: list[SkippedRow] = field(default_factory=list)


def stable_row_key(row: ParsedRow | OpeningRow) -> str:
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


def tx_id_for(row: ParsedRow | OpeningRow) -> str:
    return str(uuid.uuid5(mapping.IMPORT_NAMESPACE, stable_row_key(row)))


def _split_account_name(name: str, currency: str, currencies: set[str]) -> str:
    """Display name for one currency-leg of a sheet account.

    A name used under a single currency is passed through verbatim. A name that
    spans several gets each leg suffixed with its currency — "BCP Oro" holding
    both PEN and USD rows becomes "BCP Oro PEN" and "BCP Oro USD", so neither
    leg is ambiguous in a picker. Suffixing *both* rather than only the foreign
    one keeps the pair symmetric and matches how such accounts are usually
    named by hand. A name that already ends in its own currency is left alone
    rather than doubled.
    """
    if len(currencies) < 2:
        return name
    if name.casefold().endswith(f" {currency.casefold()}"):
        return name
    return f"{name} {currency}"


def _distinct_ci(names: Iterable[str]) -> list[str]:
    """Case-insensitive distinct, keeping the first-seen original casing."""
    seen: dict[str, str] = {}
    for name in names:
        key = name.strip().casefold()
        if key not in seen:
            seen[key] = name.strip()
    return list(seen.values())


def build_plan(
    parsed: list[ParsedRow],
    openings: list[OpeningRow],
    skipped: list[SkippedRow],
) -> ImportPlan:
    skips = list(skipped)
    rows: list[ParsedRow] = []
    tx_ids: dict[int, str] = {}
    # No content-dedup here, deliberately: stable_row_key embeds row.line, so
    # ids are line-keyed and always unique — identical content on two lines
    # imports twice (the old `tid in seen_ids` skip was unreachable, 6.4e).
    for row in parsed:
        tx_ids[row.line] = tx_id_for(row)
        rows.append(row)

    # Opening balances: the engine enforces one active opening per account, so
    # a sheet with two SALDO INICIAL rows for the same (account, currency)
    # keeps only the first (lowest line) and reports the rest — deterministic
    # and visible in the dry-run rather than a surprise 409 at apply time.
    kept_openings: list[OpeningRow] = []
    opening_ids: dict[int, str] = {}
    first_by_account: dict[tuple[str, str], int] = {}
    for row in openings:
        key = (row.account.strip().casefold(), row.currency)
        if key in first_by_account:
            skips.append(
                SkippedRow(
                    row.line,
                    "duplicate-opening",
                    f"first at line {first_by_account[key]}",
                )
            )
            continue
        first_by_account[key] = row.line
        opening_ids[row.line] = tx_id_for(row)
        kept_openings.append(row)

    pairs: list[tuple[str, str]] = []
    acct_seen: set[tuple[str, str]] = set()
    # Openings can reference accounts that appear in no ordinary row — an
    # account whose only sheet entry is its SALDO INICIAL still gets created.
    for row in [*rows, *kept_openings]:
        key = (row.account.strip().casefold(), row.currency)
        if key not in acct_seen:
            acct_seen.add(key)
            pairs.append((row.account.strip(), row.currency))

    spanning: dict[str, set[str]] = {}
    for name, currency in pairs:
        spanning.setdefault(name.casefold(), set()).add(currency)
    accounts = [
        AccountSpec(
            name=_split_account_name(name, currency, spanning[name.casefold()]),
            currency=currency,
            source_name=name,
        )
        for name, currency in pairs
    ]

    return ImportPlan(
        rows=rows,
        tx_ids=tx_ids,
        accounts=accounts,
        categories=_distinct_ci(row.category for row in rows),
        hashtags=_distinct_ci(row.hashtag for row in rows),
        openings=kept_openings,
        opening_ids=opening_ids,
        skipped=skips,
    )
