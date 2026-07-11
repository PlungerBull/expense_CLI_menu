"""Write path: resolve-or-create resources, then POST transactions in batches.

Accounts/categories/hashtags are created FIRST (so they have ids); transactions
then reference those ids. The batch endpoint is atomic: a chunk-level 409 ("at
least one id pre-exists") or 422 ("at least one row is invalid") says nothing
about WHICH row, so the chunk is retried row-by-row (singleton batches) —
pre-existing rows are skipped, invalid rows report their sheet line, and the
rest still land. Re-runs after a partial run or with appended sheet rows
converge instead of silently dropping.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from uuid import uuid4

from expense.commands._resource import fetch_all_pages
from expense.dates import to_canonical_aware
from expense.errors import EngineConnectionError, EngineError, format_error
from expense.http import ExpenseClient
from expense.import_ import mapping
from expense.import_.parse import ParsedRow
from expense.import_.plan import ImportPlan


@dataclass
class ResolveResult:
    account_ids: dict[tuple[str, str], str]  # (name.casefold, currency) -> id
    category_ids: dict[str, str]  # name.casefold -> id
    hashtag_ids: dict[str, str]  # name.casefold -> id
    accounts_created: int = 0
    accounts_reused: int = 0
    categories_created: int = 0
    categories_reused: int = 0
    hashtags_created: int = 0
    hashtags_reused: int = 0
    # Per-resource create failures (name + engine error). A failed resource is
    # left out of the *_ids maps, so its dependent transactions are skipped
    # pre-flight rather than crashing on a KeyError.
    resolve_failures: list[str] = field(default_factory=list)


@dataclass
class ApplyResult:
    resolve: ResolveResult
    tx_created: int = 0
    tx_skipped_existing: int = 0  # rows whose singleton retry 409'd (id already imported)
    tx_failed: int = 0
    # (chunk_index, message) — messages carry sheet line numbers so a failed
    # row can be found in the workbook without bisecting.
    failures: list[tuple[int, str]] = field(default_factory=list)


def _list_all(client: ExpenseClient, resource: str) -> list[dict]:
    """GET every existing row for a resource (flat list, or paged at the engine cap)."""
    return fetch_all_pages(
        lambda limit, offset: client.get(
            f"/{resource}",
            params={"include_archived": "true", "limit": limit, "offset": offset},
        )
    )


def _resolve_each(
    client: ExpenseClient,
    resource: str,
    wanted,
    *,
    existing: dict,
    key_of,
    payload_of,
    describe,
) -> tuple[dict, int, int, list[str]]:
    """Resolve each wanted spec against `existing` (reuse) or POST it (create).

    Returns (key → id, created, reused, failures). One copy of the resolve-or-POST
    loop the three resource blocks below used to paste (backlog 6.4d). `existing`
    is mutated so a duplicate spec reuses the row created for the first one;
    `payload_of(spec, i)` gets the enumerate index (categories' palette).

    A per-spec `EngineError` (422/409/5xx-after-retries) is collected via
    `describe(spec)` and the loop continues — one bad resource no longer aborts
    the whole import (backlog 6.4d follow-up). An `EngineConnectionError`
    propagates: the engine is unreachable, so nothing further can succeed and a
    re-run converges once it's back.
    """
    ids: dict = {}
    created = reused = 0
    failures: list[str] = []
    for i, spec in enumerate(wanted):
        key = key_of(spec)
        if key in existing:
            ids[key] = existing[key]
            reused += 1
        else:
            nid = str(uuid4())
            try:
                client.post(f"/{resource}", json_body={"id": nid, **payload_of(spec, i)})
            except EngineError as err:
                failures.append(f"{resource[:-1]} {describe(spec)}: {format_error(err)}")
                continue
            existing[key] = nid
            ids[key] = nid
            created += 1
    return ids, created, reused, failures


def resolve_or_create(client: ExpenseClient, plan: ImportPlan) -> ResolveResult:
    res = ResolveResult(account_ids={}, category_ids={}, hashtag_ids={})

    # --- accounts: keyed by (name, currency) ---
    amap: dict[tuple[str, str], str] = {}
    for acc in _list_all(client, "accounts"):
        name, cur, aid = acc.get("name"), acc.get("currency_code"), acc.get("id")
        if name and cur and aid:
            amap[(str(name).strip().casefold(), str(cur).upper())] = aid
    res.account_ids, res.accounts_created, res.accounts_reused, af = _resolve_each(
        client,
        "accounts",
        plan.accounts,
        existing=amap,
        key_of=lambda s: (s.name.strip().casefold(), s.currency),
        payload_of=lambda s, _i: {"name": s.name, "currency_code": s.currency},
        describe=lambda s: f"{s.name!r} ({s.currency})",
    )
    res.resolve_failures.extend(af)

    # --- categories: case-insensitive, require a color ---
    cmap: dict[str, str] = {}
    for cat in _list_all(client, "categories"):
        name, cid = cat.get("name"), cat.get("id")
        if name and cid:
            cmap[str(name).strip().casefold()] = cid
    res.category_ids, res.categories_created, res.categories_reused, cf = _resolve_each(
        client,
        "categories",
        plan.categories,
        existing=cmap,
        key_of=lambda n: n.strip().casefold(),
        payload_of=lambda n, i: {
            "name": n,
            "color": mapping.CATEGORY_PALETTE[i % len(mapping.CATEGORY_PALETTE)],
        },
        describe=repr,
    )
    res.resolve_failures.extend(cf)

    # --- hashtags: case-insensitive, no color ---
    hmap: dict[str, str] = {}
    for tag in _list_all(client, "hashtags"):
        name, hid = tag.get("name"), tag.get("id")
        if name and hid:
            hmap[str(name).strip().casefold()] = hid
    res.hashtag_ids, res.hashtags_created, res.hashtags_reused, hf = _resolve_each(
        client,
        "hashtags",
        plan.hashtags,
        existing=hmap,
        key_of=lambda n: n.strip().casefold(),
        payload_of=lambda n, _i: {"name": n},
        describe=repr,
    )
    res.resolve_failures.extend(hf)

    return res


def _missing_dep(row: ParsedRow, res: ResolveResult) -> str | None:
    """Name the first resource `row` needs that failed to resolve, else None.

    Guards `build_tx_payload`'s `*_ids[...]` lookups: a resource whose create
    POST failed is absent from the maps, so its dependent rows are skipped
    pre-flight instead of raising `KeyError` mid-batch.
    """
    if (row.account.strip().casefold(), row.currency) not in res.account_ids:
        return f"account {row.account!r} ({row.currency})"
    if row.category.strip().casefold() not in res.category_ids:
        return f"category {row.category!r}"
    if row.hashtag.strip().casefold() not in res.hashtag_ids:
        return f"hashtag {row.hashtag!r}"
    return None


def build_tx_payload(row: ParsedRow, tx_id: str, res: ResolveResult) -> dict:
    payload: dict = {
        "id": tx_id,
        "title": row.title,
        "amount_cents": row.amount_cents,
        "account_id": res.account_ids[(row.account.strip().casefold(), row.currency)],
        "category_id": res.category_ids[row.category.strip().casefold()],
        "hashtag_ids": [res.hashtag_ids[row.hashtag.strip().casefold()]],
        "date": to_canonical_aware(row.date_iso),
    }
    if row.description is not None:
        payload["description"] = row.description
    if row.exchange_rate is not None:
        # Decimal kept the rounding money-correct; the wire field is a JSON
        # number and json.dumps can't emit Decimal, so cast at the boundary.
        # Lossless for a 6-dp value: float -> shortest round-tripping repr.
        payload["exchange_rate"] = float(row.exchange_rate)
    return payload


def chunked(items: list, size: int) -> Iterator[list]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _line_range(items: list[dict], line_by_id: dict[str, int]) -> str:
    lines = sorted(line_by_id[item["id"]] for item in items)
    if lines[0] == lines[-1]:
        return f"sheet line {lines[0]}"
    return f"sheet lines {lines[0]}-{lines[-1]}"


def _apply_singletons(
    client: ExpenseClient,
    chunk: list[dict],
    chunk_index: int,
    line_by_id: dict[str, int],
    result: ApplyResult,
) -> bool:
    """Retry a 409'd/422'd chunk row-by-row via singleton batches.

    An atomic-batch failure doesn't say which row; posting one row per batch
    keeps the endpoint's semantics while letting good rows land — 409s are
    skipped as already-imported, other errors report the row's sheet line.
    Returns False when a connection error stopped the run (this chunk's unsent
    tail is already counted failed).
    """
    for pos, item in enumerate(chunk):
        try:
            client.post("/transactions/batch", json_body={"transactions": [item]})
            result.tx_created += 1
        except EngineError as err:
            if err.status == 409:
                result.tx_skipped_existing += 1
            else:
                result.tx_failed += 1
                # format_error keeps the envelope's fields + hints — sheet-line
                # context is prefixed so it survives multi-line output (6.3a)
                result.failures.append(
                    (
                        chunk_index,
                        f"sheet line {line_by_id[item['id']]}, id {item['id']}: "
                        f"{format_error(err)}",
                    )
                )
        except EngineConnectionError as err:
            result.tx_failed += len(chunk) - pos
            result.failures.append(
                (
                    chunk_index,
                    f"CONNECTION_ERROR: {format_error(err)} — rows from sheet line "
                    f"{line_by_id[item['id']]} on were not sent",
                )
            )
            return False
    return True


def apply_plan(
    client: ExpenseClient,
    plan: ImportPlan,
    res: ResolveResult,
    *,
    chunk_size: int = 200,
) -> ApplyResult:
    result = ApplyResult(resolve=res)
    items: list[dict] = []
    line_by_id: dict[str, int] = {}
    for row in plan.rows:
        missing = _missing_dep(row, res)
        if missing is not None:
            # Its dependency's create POST failed (recorded in resolve_failures);
            # this row can't reference a row that doesn't exist.
            result.tx_failed += 1
            result.failures.append(
                (-1, f"sheet line {row.line}: not sent — {missing} was not created")
            )
            continue
        tx_id = plan.tx_ids[row.line]
        items.append(build_tx_payload(row, tx_id, res))
        line_by_id[tx_id] = row.line
    for chunk_index, chunk in enumerate(chunked(items, chunk_size)):
        try:
            client.post("/transactions/batch", json_body={"transactions": chunk})
            result.tx_created += len(chunk)
        except EngineError as err:
            if err.status in (409, 422):
                if not _apply_singletons(client, chunk, chunk_index, line_by_id, result):
                    # Fallback hit a connection error: its chunk tail is counted;
                    # add the never-sent later chunks, mirroring the branch below.
                    result.tx_failed += len(items) - (chunk_index * chunk_size + len(chunk))
                    break
            else:
                # 401/403/5xx would fail identically per row — don't hammer.
                result.tx_failed += len(chunk)
                result.failures.append(
                    (chunk_index, f"{_line_range(chunk, line_by_id)}: {format_error(err)}")
                )
        except EngineConnectionError as err:
            # Stop sending, but return normally so the caller still renders the
            # summary of committed chunks (cache_after_write is already best-effort).
            remaining = len(items) - chunk_index * chunk_size
            result.tx_failed += remaining
            result.failures.append(
                (
                    chunk_index,
                    f"CONNECTION_ERROR: {format_error(err)} — rows from sheet line "
                    f"{line_by_id[chunk[0]['id']]} on were not sent",
                )
            )
            break
    return result
