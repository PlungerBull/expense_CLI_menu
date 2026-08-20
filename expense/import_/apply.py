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
from expense.import_.parse import OpeningRow, ParsedRow
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
    opening_created: int = 0
    opening_skipped_existing: int = 0  # 409: id replayed, or account already seeded
    opening_failed: int = 0
    # (chunk_index, message) — messages carry sheet line numbers so a failed
    # row can be found in the workbook without bisecting.
    failures: list[tuple[int, str]] = field(default_factory=list)


def _list_all(
    client: ExpenseClient, resource: str, *, include_archived: bool = False
) -> list[dict]:
    """GET every existing row for a resource (flat list, or paged at the engine cap).

    `include_archived` applies to accounts only — the only archivable resource
    since the 2026-08-06 engine schema slimming.
    """
    params: dict = {}
    if include_archived:
        params["include_archived"] = "true"
    return fetch_all_pages(
        lambda limit, offset: client.get(
            f"/{resource}",
            params={**params, "limit": limit, "offset": offset},
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
    index_of=None,
) -> tuple[dict, int, int, list[str]]:
    """Resolve each wanted spec against `existing` (reuse) or POST it (create).

    Returns (key → id, created, reused, failures). One copy of the resolve-or-POST
    loop the three resource blocks below used to paste (backlog 6.4d). `existing`
    is mutated so a duplicate spec reuses the row created for the first one;
    `payload_of(spec, i)` gets the enumerate index (categories' palette).

    `key_of` identifies the spec *engine-side* — it must match how `existing`
    was keyed, or a row that already exists would be created again. `index_of`
    identifies it *sheet-side* — it is how the returned map is keyed, i.e. what
    callers look a row's resource up by. They coincide for categories and
    hashtags (the sheet cell is the engine name) and diverge for accounts,
    whose engine name may carry a currency suffix the sheet never had.

    A per-spec `EngineError` (422/409/5xx-after-retries) is collected via
    `describe(spec)` and the loop continues — one bad resource no longer aborts
    the whole import (backlog 6.4d follow-up). An `EngineConnectionError`
    propagates: the engine is unreachable, so nothing further can succeed and a
    re-run converges once it's back.
    """
    index_of = index_of or key_of
    ids: dict = {}
    created = reused = 0
    failures: list[str] = []
    for i, spec in enumerate(wanted):
        key = key_of(spec)
        if key in existing:
            ids[index_of(spec)] = existing[key]
            reused += 1
        else:
            nid = str(uuid4())
            try:
                client.post(f"/{resource}", json_body={"id": nid, **payload_of(spec, i)})
            except EngineError as err:
                failures.append(f"{resource[:-1]} {describe(spec)}: {format_error(err)}")
                continue
            existing[key] = nid
            ids[index_of(spec)] = nid
            created += 1
    return ids, created, reused, failures


def resolve_or_create(client: ExpenseClient, plan: ImportPlan) -> ResolveResult:
    res = ResolveResult(account_ids={}, category_ids={}, hashtag_ids={})

    # --- accounts: keyed by (name, currency) ---
    amap: dict[tuple[str, str], str] = {}
    for acc in _list_all(client, "accounts", include_archived=True):
        name, cur, aid = acc.get("name"), acc.get("currency_code"), acc.get("id")
        if name and cur and aid:
            amap[(str(name).strip().casefold(), str(cur).upper())] = aid
    res.account_ids, res.accounts_created, res.accounts_reused, af = _resolve_each(
        client,
        "accounts",
        plan.accounts,
        existing=amap,
        key_of=lambda s: (s.name.strip().casefold(), s.currency),
        index_of=lambda s: (s.source_name.strip().casefold(), s.currency),
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
    return payload


def build_opening_payload(row: OpeningRow, transaction_id: str) -> dict:
    payload: dict = {
        "transaction_id": transaction_id,
        "amount_cents": row.amount_cents,
        "date": to_canonical_aware(row.date_iso),
        "title": row.title,
    }
    return payload


def _apply_openings(client: ExpenseClient, plan: ImportPlan, res, result: ApplyResult) -> bool:
    """POST each opening balance to /accounts/{id}/opening-balance.

    A 409 means the seed already landed (replayed transaction_id, or the
    account already carries an opening balance) — counted as already-present,
    mirroring the singleton-batch semantics. Returns False when a connection
    error stopped the run (remaining openings are counted failed).
    """
    for pos, row in enumerate(plan.openings):
        account_key = (row.account.strip().casefold(), row.currency)
        account_id = res.account_ids.get(account_key)
        if account_id is None:
            result.opening_failed += 1
            result.failures.append(
                (
                    -1,
                    f"sheet line {row.line}: opening balance not sent — "
                    f"account {row.account!r} ({row.currency}) was not created",
                )
            )
            continue
        try:
            client.post(
                f"/accounts/{account_id}/opening-balance",
                json_body=build_opening_payload(row, plan.opening_ids[row.line]),
            )
            result.opening_created += 1
        except EngineError as err:
            if err.status == 409:
                result.opening_skipped_existing += 1
            else:
                result.opening_failed += 1
                result.failures.append(
                    (-1, f"sheet line {row.line} (opening balance): {format_error(err)}")
                )
        except EngineConnectionError as err:
            result.opening_failed += len(plan.openings) - pos
            result.failures.append(
                (
                    -1,
                    f"CONNECTION_ERROR: {format_error(err)} — opening balances from "
                    f"sheet line {row.line} on were not sent",
                )
            )
            return False
    return True


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

    # Opening balances go first: seeds are account-level state, and if the
    # engine is unreachable the ordinary rows would fail identically anyway.
    if not _apply_openings(client, plan, res, result):
        result.tx_failed += len(plan.rows)
        result.failures.append(
            (-1, "transactions not sent — connection lost while seeding opening balances")
        )
        return result

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
            # summary of committed chunks.
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
