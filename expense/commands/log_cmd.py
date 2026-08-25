"""`expense log` — a ledger entry, from four flags or from one typed line.

Two forms, one command, never mixed:

    expense log --title Lunch --amount -1500 --account-id <id> --category-id <id>
    expense log "tottus -38.60 $signature @korakuen #caja hoy"

The flag form is the original and is unchanged — explicit, scriptable, no
parsing. The line form runs the shared quick-add grammar (expense/quickadd/),
so it and the TUI bar read a line exactly alike.

Two behaviours are specific to the line form, decided 2026-08-25
(docs/decisions.md "Two calls for the one-line `expense log`"):

* **An incomplete or ambiguous line becomes an Inbox draft**, not an error —
  the routing rule `expense/quickadd/route.py` holds for both surfaces.
* **It always asks before writing**, unless `--yes`. The grammar is forgiving
  on purpose (`18/8/26`, `$sig`, `hoy`); the TUI earns that back with its
  staged list, and this prompt is the flat equivalent.
"""

import json
from dataclasses import asdict
from uuid import uuid4

import typer

from expense import config as config_module
from expense.commands._resource import (
    JSON_OPT,
    QuickAddRefs,
    currency_of,
    format_cents,
    load_quickadd_refs,
    parse_hashtag_ids,
    render_record,
    require_yes,
    resolve_name,
    truncate,
)
from expense.context import get_verbose
from expense.dates import now_local_iso, to_canonical_aware, today_local
from expense.errors import EngineError, handle_errors
from expense.http import ExpenseClient
from expense.quickadd.parse import ParsedLine, parse
from expense.quickadd.payload import inbox_payload, transaction_payload
from expense.quickadd.route import Routing, route
from expense.quickadd.when import format_date_words

# The flag form's content flags. Passing any of these alongside a line is a
# mistake rather than a merge — the line already says all of it.
_CONTENT_FLAGS = (
    ("--title", "title"),
    ("--amount", "amount"),
    ("--account-id", "account_id"),
    ("--category-id", "category_id"),
    ("--date", "date"),
    ("--description", "description"),
    ("--hashtag-ids", "hashtag_ids"),
)
_REQUIRED_FLAGS = ("--title", "--amount", "--account-id", "--category-id")

# Width of the row block: title left, amount right, as picked 2026-08-25
# (docs/mockups/expense-world-log-oneline.html, option A).
_ROW_WIDTH = 62
_PLURAL = {"account": "accounts", "category": "categories", "hashtag": "hashtags"}


def _fail(message: str) -> None:
    """Client-side refusal: stderr, exit 1.

    Deliberately not `typer.BadParameter`, whose exit 2 collides with click's
    own usage code (docs/decisions.md, the exit-code entry).
    """
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code=1)


def _reference_cell(parsed: ParsedLine, kind: str, value: str | None, names: dict) -> str:
    """One reference as the facts line shows it: the resolved name, or why not."""
    if value:
        return resolve_name(value, names)
    token = next((u for u in parsed.unresolved if u.kind == kind), None)
    if token is None:
        return f"no {kind}"
    sigil = "$" if kind == "account" else "@"
    if not token.candidates:
        return f"{sigil}{token.text} — no match"
    return f"{sigil}{token.text} — {len(token.candidates)} {_PLURAL[kind]}"


def _hashtag_cell(parsed: ParsedLine, refs: QuickAddRefs) -> str:
    cells = [f"#{resolve_name(t, refs.hashtag_names)}" for t in parsed.hashtag_ids]
    cells += [f"#{u.text} — no match" for u in parsed.unresolved if u.kind == "hashtag"]
    return " ".join(cells)


def render_row(parsed: ParsedLine, refs: QuickAddRefs) -> list[str]:
    """The two-line echo of what the grammar read — the thing you say y to.

    Line one is what and how much, the amount right-aligned so it lands in the
    same column every time. Line two is everything else, dot-separated, with
    the date spelled out in words — the check that makes a two-digit year safe
    to accept (docs/decisions.md).
    """
    amount = format_cents(parsed.amount_cents) if parsed.amount_cents is not None else "no amount"
    currency = currency_of(refs, parsed.account_id)
    if currency:
        amount = f"{amount} {currency}"

    title = parsed.title or "(no title)"
    room = _ROW_WIDTH - len(amount) - 2
    title = truncate(title, room)

    facts = [
        _reference_cell(parsed, "account", parsed.account_id, refs.account_names),
        _reference_cell(parsed, "category", parsed.category_id, refs.category_names),
    ]
    tags = _hashtag_cell(parsed, refs)
    if tags:
        facts.append(tags)
    facts.append(format_date_words(parsed.date))
    if parsed.note:
        facts.append(f"“{parsed.note}”")

    return [f"  {title.ljust(room + 2)}{amount}", f"  {' · '.join(facts)}"]


def render_reasons(parsed: ParsedLine, routing: Routing, refs: QuickAddRefs) -> list[str]:
    """Why this row is a draft, plus the candidates behind an ambiguous name.

    Listing the candidates on a row that is *going* to the Inbox is the point:
    an ambiguous name counts as no name (decided 2026-08-25), so the way out is
    to answer n and type more of it — which you cannot do without seeing them.
    """
    if not routing.to_inbox:
        return []
    lines = [f"  ! Goes to the Inbox — {', '.join(routing.reasons)}."]
    ambiguous = False
    for token in parsed.unresolved:
        if not token.candidates:
            continue
        ambiguous = True
        for ident, name in token.candidates:
            currency = currency_of(refs, ident)
            lines.append(f"        {name}{'    ' + currency if currency else ''}")
    if ambiguous:
        lines.append("    Answer n and type more of the name to send it to the ledger instead.")
    return lines


def _dry_run_json(line: str, parsed: ParsedLine, routing: Routing, body: dict) -> str:
    """The parse as JSON — a *client-composed* `--json`, not an engine body.

    The third sanctioned exception in the CLI (with `accounts update
    --currency-code` and `import --json`); see docs/cli-spec.md. It is the only
    way to see what the grammar did without writing, so its shape is the
    contract a future consumer reads: the resolved fields, what did not
    resolve and its candidates, and a span per token.
    """
    return json.dumps(
        {
            "line": line,
            "target": routing.target,
            "reasons": list(routing.reasons),
            "payload": body,
            "parsed": {
                "title": parsed.title,
                "amount_cents": parsed.amount_cents,
                "account_id": parsed.account_id,
                "category_id": parsed.category_id,
                "hashtag_ids": list(parsed.hashtag_ids),
                "note": parsed.note,
                "date": parsed.date,
                "date_given": parsed.date_given,
                "missing": list(parsed.missing),
                "unresolved": [asdict(u) for u in parsed.unresolved],
                "spans": [asdict(s) for s in parsed.spans],
            },
        },
        indent=2,
    )


@handle_errors
def log(
    ctx: typer.Context,
    line: str | None = typer.Argument(
        None,
        metavar="[LINE]",
        help='One typed line: "what ±amount $account @category #tag when". '
        "A sign is what makes a number an amount; `//` opens a note. "
        "Mutually exclusive with the flags below.",
    ),
    title: str | None = typer.Option(None, "--title", help="Short label for the transaction."),
    amount: int | None = typer.Option(
        None,
        "--amount",
        help="Signed cents. Negative = expense, positive = income. Sign is mandatory.",
    ),
    account_id: str | None = typer.Option(None, "--account-id", help="Account UUID."),
    category_id: str | None = typer.Option(None, "--category-id", help="Category UUID."),
    date: str | None = typer.Option(
        None,
        "--date",
        help="YYYY-MM-DD, 'YYYY-MM-DD HH:MM[:SS]', or RFC 3339 with offset. "
        "Naive forms get the local timezone attached. Defaults to now.",
    ),
    description: str | None = typer.Option(None, "--description"),
    hashtag_ids: str | None = typer.Option(
        None,
        "--hashtag-ids",
        help="Comma-separated hashtag UUIDs to attach at creation. "
        "Engine rejects archived ids with 422.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Line form only: show what the grammar read and write nothing.",
    ),
    yes: bool = typer.Option(False, "--yes", help="Line form only: skip the confirmation."),
    json_output: bool = JSON_OPT,
) -> None:
    """POST /v1/transactions — or /v1/inbox when a typed line is incomplete.

    Two forms. Four flags, or one line in the quick-add grammar; never both.
    A line that is missing something, names something ambiguously, or is dated
    ahead becomes an Inbox draft instead — the command says so and asks first.

    Example: expense log --title Lunch --amount -1500 --account-id <id> --category-id <id>

    Example: expense log "tottus -38.60 $signature @korakuen #caja hoy" --dry-run
    """
    cfg = config_module.ensure_loaded()
    verbose = get_verbose(ctx)
    flags = {
        "title": title,
        "amount": amount,
        "account_id": account_id,
        "category_id": category_id,
        "date": date,
        "description": description,
        "hashtag_ids": hashtag_ids,
    }
    given = [flag for flag, key in _CONTENT_FLAGS if flags[key] is not None]

    if line is not None and given:
        _fail(
            f"a line and {given[0]} are two different forms of this command — pass one or "
            "the other. The line already carries what the flags say."
        )
    if line is None:
        if dry_run:
            _fail("--dry-run needs a line; with flags there is nothing to preview.")
        if not given:
            _fail(
                'nothing to log. Pass a line — expense log "lunch -1500 $bcp @food hoy" — '
                f"or the flags {', '.join(_REQUIRED_FLAGS)}."
            )
        missing = [flag for flag in _REQUIRED_FLAGS if flag not in given]
        if missing:
            _fail(f"the flag form needs {', '.join(missing)}.")
        _log_from_flags(cfg, verbose=verbose, json_output=json_output, **flags)
        return

    if not line.strip():
        _fail("the line is empty.")
    if json_output and not (yes or dry_run):
        _fail("--json cannot prompt. Pass --yes to write, or --dry-run to look first.")

    _log_from_line(
        cfg,
        line,
        verbose=verbose,
        json_output=json_output,
        dry_run=dry_run,
        yes=yes,
    )


def _log_from_flags(
    cfg,
    *,
    verbose: bool,
    json_output: bool,
    title: str,
    amount: int,
    account_id: str,
    category_id: str,
    date: str | None,
    description: str | None,
    hashtag_ids: str | None,
) -> None:
    """The original command, unchanged: no parse, no prompt, no routing."""
    new_id = str(uuid4())
    payload: dict = {
        "id": new_id,
        "title": title,
        "amount_cents": amount,
        "account_id": account_id,
        "category_id": category_id,
        "date": to_canonical_aware(date) if date is not None else now_local_iso(),
    }
    if description is not None:
        payload["description"] = description
    if hashtag_ids is not None:
        payload["hashtag_ids"] = parse_hashtag_ids(hashtag_ids)

    body = _post(cfg, "/transactions", payload, verbose=verbose)
    if not json_output:
        typer.echo(f"Created: {new_id}")
    render_record(body, json_mode=json_output)


def _log_from_line(
    cfg, line: str, *, verbose: bool, json_output: bool, dry_run: bool, yes: bool
) -> None:
    today = today_local()
    refs = load_quickadd_refs(cfg, verbose=verbose)
    parsed = parse(
        line,
        accounts=refs.accounts,
        categories=refs.categories,
        hashtags=refs.hashtags,
        today=today,
    )
    routing = route(parsed, today)

    # A line with no date keeps the flag form's "defaults to now"; a line that
    # names one means that day, so it lands at local midnight.
    wire_date = to_canonical_aware(parsed.date) if parsed.date_given else now_local_iso()
    new_id = str(uuid4())
    body = (
        inbox_payload(parsed, row_id=new_id, date=wire_date)
        if routing.to_inbox
        else transaction_payload(parsed, row_id=new_id, date=wire_date)
    )

    if dry_run:
        if json_output:
            typer.echo(_dry_run_json(line, parsed, routing, body))
            return
        _echo_block(parsed, routing, refs)
        where = "the Inbox" if routing.to_inbox else "the ledger"
        typer.echo(f"  → {where}. Nothing written (--dry-run).")
        return

    if not json_output:
        _echo_block(parsed, routing, refs)
    prompt = "  File it as a draft?" if routing.to_inbox else "  Log this to the ledger?"
    require_yes(yes, prompt, aborted_text="Nothing written.")

    path = "/inbox" if routing.to_inbox else "/transactions"
    response = _post(cfg, path, body, verbose=verbose)
    if not json_output:
        typer.echo(f"{'Drafted' if routing.to_inbox else 'Created'}: {new_id}")
    render_record(response, json_mode=json_output)


def _echo_block(parsed: ParsedLine, routing: Routing, refs: QuickAddRefs) -> None:
    typer.echo("")
    for row in render_row(parsed, refs):
        typer.echo(row)
    reasons = render_reasons(parsed, routing, refs)
    if reasons:
        typer.echo("")
        for row in reasons:
            typer.echo(row)
    typer.echo("")


def _post(cfg, path: str, payload: dict, *, verbose: bool) -> dict:
    with ExpenseClient(cfg, verbose=verbose) as client:
        try:
            return client.post(path, json_body=payload)
        except EngineError as err:
            if err.code == "SETTINGS_MISSING":
                typer.echo(
                    "Hint: Your user_settings row is missing. "
                    "Run 'expense auth bootstrap' to provision it.",
                    err=True,
                )
            raise
