"""Shared helpers for resource sub-apps (accounts, categories, hashtags)."""

import json
import os
import re
import sys
from collections.abc import Callable
from typing import Any

import typer

from expense import config as config_module
from expense.cache import ensure_synced, refresh_after_write
from expense.config import Config
from expense.context import get_no_cache, get_no_sync_after, get_verbose
from expense.errors import EngineError
from expense.http import ExpenseClient

# Shared option declarations — one wording for flags repeated across command
# modules. Never mutate these; a command whose flag means something different
# declares it inline (e.g. `reconcile reorder --json` skips the editor).
JSON_OPT = typer.Option(False, "--json", help="Output the raw engine response as JSON.")
LIMIT_OPT = typer.Option(None, "--limit", help="Max rows to return (engine default applies).")
OFFSET_OPT = typer.Option(None, "--offset", help="Rows to skip (pagination).")
INCLUDE_DELETED_OPT = typer.Option(
    False, "--include-deleted", help="Include soft-deleted rows (always reads from the engine)."
)
INCLUDE_ARCHIVED_OPT = typer.Option(False, "--include-archived", help="Include archived rows.")
YES_OPT = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt.")

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def visible_len(text: str) -> int:
    """Length of `text` ignoring ANSI escape sequences."""
    return len(_ANSI_RE.sub("", text))


def pad_left(text: str, width: int) -> str:
    """Left-align `text` (pad spaces on the right) to `width` visible cols."""
    return text + " " * max(width - visible_len(text), 0)


def pad_right(text: str, width: int) -> str:
    """Right-align `text` (pad spaces on the left) to `width` visible cols."""
    return " " * max(width - visible_len(text), 0) + text


def color_supported() -> bool:
    """True iff stdout is a TTY and NO_COLOR env var is unset.

    Honors the de-facto NO_COLOR convention (https://no-color.org/).
    """
    return sys.stdout.isatty() and os.environ.get("NO_COLOR", "") == ""


def color_swatch(hex_value: object, *, color: bool) -> str:
    """Render a 2-char ANSI swatch for `#RRGGBB`, or fall back to the hex.

    Returns `(none)` when the input is None. Invalid hex falls through to
    the raw string. Set `color=False` to always render the hex literally
    (e.g. when piping to a file).
    """
    if hex_value is None:
        return "(none)"
    if not isinstance(hex_value, str):
        return str(hex_value)
    if not color:
        return hex_value
    if len(hex_value) != 7 or not hex_value.startswith("#"):
        return hex_value
    try:
        r = int(hex_value[1:3], 16)
        g = int(hex_value[3:5], 16)
        b = int(hex_value[5:7], 16)
    except ValueError:
        return hex_value
    return f"\x1b[38;2;{r};{g};{b}m██\x1b[0m"


def truncate(text: object, max_width: int) -> str:
    """Truncate `text` to `max_width` visible chars, appending `…` if cut."""
    if text is None:
        return ""
    s = str(text)
    if visible_len(s) <= max_width:
        return s
    if max_width <= 1:
        return s[:max_width]
    return s[: max_width - 1] + "…"


def format_short_date(iso_value: object) -> str:
    """`2026-04-24T12:00:00Z` → `2026-04-24`. None / non-string → `—`."""
    if not isinstance(iso_value, str) or len(iso_value) < 10:
        return "—"
    return iso_value[:10]


def format_cents(value: object) -> str:
    """Render an integer-cents amount as grouped major units with 2 decimals.

    `651900` → `6,519.00`; `-418797` → `-4,187.97`; `0` → `0.00`; None → `(null)`.

    Integer arithmetic throughout — no float division — so large amounts never
    drift. This is a human-display convenience only; `--json` output stays the
    raw engine integer. Non-int, non-None values fall back to `str()`.
    """
    if value is None:
        return "(null)"
    if not isinstance(value, int) or isinstance(value, bool):
        return str(value)
    negative = value < 0
    cents = -value if negative else value
    major, minor = divmod(cents, 100)
    body = f"{major:,}.{minor:02d}"
    return f"-{body}" if negative else body


def format_field_value(key: object, value: object) -> str:
    """Render one `key: value` line for the single-resource `get` dumps.

    Money fields (keys ending in `_cents`) render as grouped major units via
    `format_cents` so a raw dump is as readable as the list tables; every other
    field is its literal value, or `(null)` when None.
    """
    if isinstance(key, str) and key.endswith("_cents"):
        return format_cents(value)
    return "(null)" if value is None else str(value)


def render_record(body: dict, *, json_mode: bool, skip: tuple[str, ...] = ()) -> None:
    """Dump one resource record: raw JSON in json_mode, else `  key: value` lines.

    The canonical renderer behind every `<resource> get` command. `skip` hides
    keys from the human dump only — `--json` stays the verbatim engine body.
    """
    if json_mode:
        typer.echo(json.dumps(body, indent=2))
        return
    for key, value in body.items():
        if key in skip:
            continue
        typer.echo(f"  {key}: {format_field_value(key, value)}")


def format_bool(value: object) -> str:
    """Human cell for booleans (and truthy markers like `deleted_at`)."""
    return "yes" if bool(value) else "no"


def format_month(month: dict | None) -> str:
    """Render the engine's `{year, month}` object as `YYYY-MM`."""
    if isinstance(month, dict):
        year = month.get("year")
        m = month.get("month")
        if isinstance(year, int) and isinstance(m, int):
            return f"{year:04d}-{m:02d}"
    return "(unknown)"


def redact_token(token: str) -> str:
    """8-prefix + 4-suffix mask for PATs; `****` when too short to mask safely.

    Callers own the empty/None policy (CLI shows None, TUI shows `(none)`).
    """
    if len(token) <= 8:
        return "****"
    return f"{token[:8]}****{token[-4:]}"


def items_of(body: object) -> list:
    """Rows of a paginated dict (`{"items": [...]}`) or a bare list; [] for anything else.

    The engine's list endpoints return the paginated shape; a few replica/live
    paths return flat lists. Strict list-or-empty — never hands a dict or None
    to a row-builder.
    """
    if isinstance(body, dict):
        items = body.get("items")
        return items if isinstance(items, list) else []
    return body if isinstance(body, list) else []


ENGINE_PAGE_CAP = 200  # the engine's hard cap on `limit` — the one copy (backlog 6.4a)


def fetch_all_pages(
    fetch_page: Callable[[int, int], Any], *, page_size: int = ENGINE_PAGE_CAP
) -> list[dict]:
    """Exhaust a paginated resource. `fetch_page(limit, offset)` returns one raw body.

    A flat-list body (unpaginated endpoint, e.g. /accounts) is returned whole.
    Stops on an empty page, a short page, or having collected >= body["total"]
    (when the engine sends an int total). One copy of the loop — the previous
    three hand-rolled variants each had their own termination rule.
    """
    out: list[dict] = []
    offset = 0
    while True:
        body = fetch_page(page_size, offset)
        if isinstance(body, list):  # flat, unpaginated endpoint
            out.extend(body)
            return out
        page = items_of(body)
        out.extend(page)
        total = body.get("total") if isinstance(body, dict) else None
        if not page or len(page) < page_size or (isinstance(total, int) and len(out) >= total):
            return out
        offset += len(page)


def load_account_name_map() -> dict[str, str]:
    """Cache-backed account id → name map. Empty on any cache failure.

    Includes archived + people accounts so transaction/inbox rows can resolve
    references to retired accounts. Soft-deleted excluded.
    """
    try:
        from expense.cache import queries  # local import to keep _resource cheap to load
    except Exception:
        return {}
    try:
        items = queries.list_accounts(include_archived=True, include_people=True)
    except Exception:
        return {}
    out: dict[str, str] = {}
    for item in items or []:
        aid = item.get("id")
        name = item.get("name")
        if isinstance(aid, str) and isinstance(name, str):
            out[aid] = name
    return out


def load_category_name_map() -> dict[str, str]:
    """Cache-backed category id → name map. Empty on any cache failure."""
    try:
        from expense.cache import queries
    except Exception:
        return {}
    try:
        page = queries.list_categories(include_archived=True)
    except Exception:
        return {}
    out: dict[str, str] = {}
    for item in items_of(page):
        cid = item.get("id")
        name = item.get("name")
        if isinstance(cid, str) and isinstance(name, str):
            out[cid] = name
    return out


def load_hashtag_name_map() -> dict[str, str]:
    """Cache-backed hashtag id → name map. Empty on any cache failure.

    The engine returns hashtag UUIDs in `hashtag_breakdown` rows and
    `hashtag_ids` columns; renderers join against this map to display human
    names like `Food + Club`. Empty map is safe — callers fall back to raw ids.
    """
    try:
        from expense.cache import queries
    except Exception:
        return {}
    try:
        page = queries.list_hashtags(include_archived=True)
    except Exception:
        return {}
    out: dict[str, str] = {}
    for item in items_of(page):
        hid = item.get("id")
        name = item.get("name")
        if isinstance(hid, str) and isinstance(name, str):
            out[hid] = name
    return out


def resolve_name(uuid_value: object, name_map: dict[str, str]) -> str:
    """Resolve `uuid_value` via `name_map`, falling back to a short-id form.

    None / non-string → `—`. Unresolvable UUID → first 8 chars (e.g. `de37af15`).
    """
    if uuid_value is None:
        return "—"
    if not isinstance(uuid_value, str):
        return str(uuid_value)
    return name_map.get(uuid_value, uuid_value[:8])


def format_hashtag_cell(ids: object, name_map: dict[str, str], *, max_width: int) -> str:
    """Joined hashtag names for one table cell; unresolved ids show `xxxxxxxx…`.

    Empty / non-list → `—`. Shared by the CLI transactions table (width 24)
    and the TUI Transactions screen (width 20) — widths stay per-surface.
    """
    if not isinstance(ids, list) or not ids:
        return "—"
    names = [name_map.get(hid, hid[:8] + "…") if isinstance(hid, str) else "?" for hid in ids]
    return truncate(", ".join(names), max_width)


def render_table(
    headers: dict[str, str],
    rows: list[dict[str, str]],
    *,
    align_right: set[str] | frozenset[str] = frozenset(),
    sep: str = "  ",
) -> None:
    """Render an ASCII table. Cells must be pre-formatted strings.

    `headers` is an ordered dict of {column-key: column-label}.
    Each `row` is a dict keyed by the same column keys.
    Cells listed in `align_right` are right-padded; the rest are left-padded.
    Width per column = max(header label, max(visible_len(cell) for cell in column)).
    """
    if not rows:
        return
    widths = {
        key: max([len(headers[key])] + [visible_len(row.get(key, "")) for row in rows])
        for key in headers
    }

    def fmt(text: str, key: str) -> str:
        return pad_right(text, widths[key]) if key in align_right else pad_left(text, widths[key])

    typer.echo(sep.join(fmt(headers[key], key) for key in headers))
    typer.echo(sep.join("-" * widths[key] for key in headers))
    for row in rows:
        typer.echo(sep.join(fmt(row.get(key, ""), key) for key in headers))


def fetch_body(
    cfg: Config,
    *,
    path: str,
    params: dict | None,
    cache_read: Callable[[], Any],
    no_cache: bool,
    verbose: bool,
    force_live: bool = False,
    cold_start_notice: bool = True,
    notice_stream=None,
) -> Any:
    """One cache-vs-live resource read — the skeleton behind every `fetch_*`/`get`.

    `no_cache` → live GET against the engine; otherwise warm the replica
    (`ensure_synced`) and run `cache_read`, a thunk over the matching
    `expense.cache.queries` call. Param building stays with the caller.
    `force_live` routes a single read to the engine even in cache mode —
    used by `--include-deleted`, whose rows can never be in the replica
    (tombstones are purged at sync).
    """
    if no_cache or force_live:
        with ExpenseClient(cfg, verbose=verbose) as client:
            return client.get(path, params=params or None)
    with ExpenseClient(cfg, verbose=verbose, cold_start_notice=cold_start_notice) as client:
        ensure_synced(client, cfg, notice_stream=notice_stream)
    return cache_read()


def cache_after_write(ctx: typer.Context, client: ExpenseClient, cfg: Config) -> None:
    """Post-write cache refresh — reads --no-cache / --no-sync-after off ctx."""
    refresh_after_write(
        client,
        cfg,
        no_cache=get_no_cache(ctx),
        no_sync_after=get_no_sync_after(ctx),
    )


def require_yes(yes: bool, prompt_text: str) -> None:
    """Enforce explicit confirmation for destructive operations.

    Mirrors the pattern from `auth settings`: in non-TTY mode, --yes is mandatory;
    in TTY mode, prompt the user unless --yes was already passed.
    """
    if yes:
        return
    if not sys.stdin.isatty():
        typer.echo(
            "Error: --yes is required for this operation in non-interactive mode.",
            err=True,
        )
        raise typer.Exit(code=1)
    if not typer.confirm(prompt_text):
        typer.echo("Aborted.")
        raise typer.Exit(code=1)


def build_update_payload(items: dict[str, Any]) -> dict[str, Any]:
    """Drop None values; exit if nothing is left to update."""
    payload = {key: value for key, value in items.items() if value is not None}
    if not payload:
        typer.echo("Error: No fields to update; pass at least one flag.", err=True)
        raise typer.Exit(code=1)
    return payload


def render_totals(totals: dict | None) -> None:
    """Render the canonical inflow/outflow/net block.

    Shared by `dashboard` and `reports monthly` (single-month view) — both
    surface the same `{inflow, outflow, net}_cents` + `_home_cents` shape.
    Empty/missing totals print '(no totals)'.
    """
    typer.echo("Totals:")
    if not isinstance(totals, dict):
        typer.echo("  (no totals)")
        return
    for key in ("inflow_cents", "outflow_cents", "net_cents"):
        home_key = key.replace("_cents", "_home_cents")
        native_s = format_cents(totals.get(key))
        home_s = format_cents(totals.get(home_key))
        label = key.replace("_cents", "")
        typer.echo(f"  {label}: {native_s} (home: {home_s})")


def render_pagination_hint(body: Any, items: list[Any]) -> None:
    """Print a `(showing N of M; pass --offset ... --limit ... for more)` hint.

    No-op when the body isn't paginated, items fit on one page, or required
    metadata is missing. Used by every paginated `list` renderer.
    """
    if not isinstance(body, dict):
        return
    total = body.get("total")
    limit = body.get("limit")
    offset = body.get("offset")
    if not (isinstance(total, int) and isinstance(limit, int) and isinstance(offset, int)):
        return
    if offset + len(items) >= total:
        return
    next_offset = offset + len(items)
    typer.echo(
        f"\n(showing {len(items)} of {total}; pass --offset {next_offset} --limit {limit} for more)"
    )


def run_toggle(
    ctx: typer.Context,
    *,
    resource: str,
    id_: str,
    verb: str,
    json_output: bool,
    render_human: Callable[[dict], None],
    hints: dict[int, str] | None = None,
) -> None:
    """Execute one of the {archive, unarchive, restore} toggle verbs.

    All three are POST /{resource}/{id}/{verb} with no body and an identical
    response shape (the resource row).

    `hints` maps HTTP status code → stderr hint string. When the engine
    raises an EngineError whose `.status` matches a key, the hint is
    printed before the error envelope renders. This lets archive/restore
    on resources with domain-specific 403/409 conditions (e.g. system
    categories, name conflicts) keep their friendly recovery prompts
    without forking the call site.
    """
    cfg: Config = config_module.ensure_loaded()
    verbose = get_verbose(ctx)

    with ExpenseClient(cfg, verbose=verbose) as client:
        try:
            body = client.post(f"/{resource}/{id_}/{verb}")
        except EngineError as err:
            if hints and err.status in hints:
                typer.echo(hints[err.status], err=True)
            raise
        cache_after_write(ctx, client, cfg)

    if json_output:
        typer.echo(json.dumps(body, indent=2))
    else:
        render_human(body)
