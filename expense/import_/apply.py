"""Write path: resolve-or-create resources, then POST transactions in batches.

Accounts/categories/hashtags are created FIRST (so they have ids); transactions
then reference those ids. The batch endpoint is atomic: a chunk-level 409 only
means "at least one id pre-exists", so the chunk is retried row-by-row (singleton
batches) — pre-existing rows are skipped, new rows still land. Re-runs after a
partial run or with appended sheet rows converge instead of silently dropping.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from uuid import uuid4

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


@dataclass
class ApplyResult:
    resolve: ResolveResult
    tx_created: int = 0
    tx_skipped_existing: int = 0  # rows whose singleton retry 409'd (id already imported)
    tx_failed: int = 0
    failures: list[tuple[int, str]] = field(default_factory=list)  # (chunk_index, message)


_PAGE = 200  # engine caps `limit` at 200


def _list_all(client: ExpenseClient, resource: str) -> list[dict]:
    """GET every existing row for a resource (flat list, or paged at the engine cap)."""
    out: list[dict] = []
    offset = 0
    while True:
        body = client.get(
            f"/{resource}",
            params={"include_archived": "true", "limit": _PAGE, "offset": offset},
        )
        if isinstance(body, list):  # accounts: flat, unpaginated
            return body
        if not isinstance(body, dict):
            return out
        items = body.get("items") or []
        out.extend(items)
        total = body.get("total")
        if not items or len(items) < _PAGE or total is None or len(out) >= total:
            return out
        offset += _PAGE


def resolve_or_create(client: ExpenseClient, plan: ImportPlan) -> ResolveResult:
    res = ResolveResult(account_ids={}, category_ids={}, hashtag_ids={})

    # --- accounts: keyed by (name, currency) ---
    amap: dict[tuple[str, str], str] = {}
    for acc in _list_all(client, "accounts"):
        name, cur, aid = acc.get("name"), acc.get("currency_code"), acc.get("id")
        if name and cur and aid:
            amap[(str(name).strip().casefold(), str(cur).upper())] = aid
    for spec in plan.accounts:
        key = (spec.name.strip().casefold(), spec.currency)
        if key in amap:
            res.account_ids[key] = amap[key]
            res.accounts_reused += 1
        else:
            nid = str(uuid4())
            client.post(
                "/accounts",
                json_body={"id": nid, "name": spec.name, "currency_code": spec.currency},
            )
            amap[key] = nid
            res.account_ids[key] = nid
            res.accounts_created += 1

    # --- categories: case-insensitive, require a color ---
    cmap: dict[str, str] = {}
    for cat in _list_all(client, "categories"):
        name, cid = cat.get("name"), cat.get("id")
        if name and cid:
            cmap[str(name).strip().casefold()] = cid
    for i, name in enumerate(plan.categories):
        key = name.strip().casefold()
        if key in cmap:
            res.category_ids[key] = cmap[key]
            res.categories_reused += 1
        else:
            nid = str(uuid4())
            color = mapping.CATEGORY_PALETTE[i % len(mapping.CATEGORY_PALETTE)]
            client.post("/categories", json_body={"id": nid, "name": name, "color": color})
            cmap[key] = nid
            res.category_ids[key] = nid
            res.categories_created += 1

    # --- hashtags: case-insensitive, no color ---
    hmap: dict[str, str] = {}
    for tag in _list_all(client, "hashtags"):
        name, hid = tag.get("name"), tag.get("id")
        if name and hid:
            hmap[str(name).strip().casefold()] = hid
    for name in plan.hashtags:
        key = name.strip().casefold()
        if key in hmap:
            res.hashtag_ids[key] = hmap[key]
            res.hashtags_reused += 1
        else:
            nid = str(uuid4())
            client.post("/hashtags", json_body={"id": nid, "name": name})
            hmap[key] = nid
            res.hashtag_ids[key] = nid
            res.hashtags_created += 1

    return res


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
        payload["exchange_rate"] = row.exchange_rate
    return payload


def chunked(items: list, size: int) -> Iterator[list]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _apply_singletons(
    client: ExpenseClient, chunk: list[dict], chunk_index: int, result: ApplyResult
) -> bool:
    """Retry a 409'd chunk row-by-row via singleton batches.

    A batch 409 only says "≥1 id pre-exists"; posting one row per batch keeps
    the endpoint's semantics ("this row exists") while letting new rows land.
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
                result.failures.append(
                    (chunk_index, f"{err.code}: {err.message} (id {item['id']})")
                )
        except EngineConnectionError as err:
            result.tx_failed += len(chunk) - pos
            result.failures.append(
                (
                    chunk_index,
                    f"CONNECTION_ERROR: {format_error(err)} — this and later rows were not sent",
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
    items = [build_tx_payload(row, plan.tx_ids[row.line], res) for row in plan.rows]
    for chunk_index, chunk in enumerate(chunked(items, chunk_size)):
        try:
            client.post("/transactions/batch", json_body={"transactions": chunk})
            result.tx_created += len(chunk)
        except EngineError as err:
            if err.status == 409:
                if not _apply_singletons(client, chunk, chunk_index, result):
                    # Fallback hit a connection error: its chunk tail is counted;
                    # add the never-sent later chunks, mirroring the branch below.
                    result.tx_failed += len(items) - (chunk_index * chunk_size + len(chunk))
                    break
            else:
                result.tx_failed += len(chunk)
                result.failures.append((chunk_index, f"{err.code}: {err.message}"))
        except EngineConnectionError as err:
            # Stop sending, but return normally so the caller still renders the
            # summary of committed chunks (cache_after_write is already best-effort).
            remaining = len(items) - chunk_index * chunk_size
            result.tx_failed += remaining
            result.failures.append(
                (
                    chunk_index,
                    f"CONNECTION_ERROR: {format_error(err)} — this and later chunks were not sent",
                )
            )
            break
    return result
