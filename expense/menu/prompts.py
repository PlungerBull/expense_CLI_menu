"""Shared menu helpers — pickers, confirmations, the BACK sentinel.

Used by every group menu phase (9.5.2 onward). No HTTP calls here; pickers
read from the local SQLite replica via `expense.cache.queries`. Empty-cache
hints point at `expense sync --full` because cold-start population is the
caller's responsibility (auto-cold-start hooks in Step 7b.2.1 cover the
flat command path, not menu pickers).
"""

import questionary
import typer

from expense.cache import queries

BACK = object()
SKIP = object()


def _format_choice(name: str, resource_id: str) -> str:
    return f"{name}  · {resource_id[:8]}…"


def _empty_hint(resource_plural: str) -> None:
    typer.echo(
        f"No {resource_plural} found. Run `expense sync --full` first, "
        f"or create one via `expense {resource_plural} create`.",
        err=True,
    )


def _select_id(
    items: list[dict],
    *,
    prompt: str,
    resource_plural: str,
    allow_skip: bool = False,
) -> object:
    if not items:
        _empty_hint(resource_plural)
        return BACK
    choices: list = []
    if allow_skip:
        choices.append(questionary.Choice(title="(skip — leave blank)", value=SKIP))
    choices.extend(
        questionary.Choice(
            title=_format_choice(item.get("name") or "(unnamed)", item["id"]),
            value=item["id"],
        )
        for item in items
    )
    answer = questionary.select(prompt, choices=choices).ask()
    if answer is None:
        return BACK
    return answer


def pick_account(
    *,
    include_archived: bool = False,
    include_people: bool = False,
    only_archived: bool = False,
    only_deleted: bool = False,
    allow_skip: bool = False,
    prompt: str = "Account",
) -> object:
    if only_archived and only_deleted:
        raise ValueError("only_archived and only_deleted are mutually exclusive.")
    if only_archived:
        items = [
            item
            for item in queries.list_accounts(
                include_archived=True,
                include_deleted=False,
                include_people=include_people,
            )
            if item.get("is_archived")
        ]
    elif only_deleted:
        items = [
            item
            for item in queries.list_accounts(
                include_archived=True,
                include_deleted=True,
                include_people=include_people,
            )
            if item.get("deleted_at") is not None
        ]
    else:
        items = queries.list_accounts(
            include_archived=include_archived,
            include_deleted=False,
            include_people=include_people,
        )
    return _select_id(items, prompt=prompt, resource_plural="accounts", allow_skip=allow_skip)


def pick_category(
    *,
    include_archived: bool = False,
    only_archived: bool = False,
    only_deleted: bool = False,
    exclude_system: bool = False,
    allow_skip: bool = False,
    prompt: str = "Category",
) -> object:
    if only_archived and only_deleted:
        raise ValueError("only_archived and only_deleted are mutually exclusive.")
    if only_archived:
        page = queries.list_categories(include_archived=True, include_deleted=False)
        items = [item for item in page.get("items", []) if item.get("is_archived")]
    elif only_deleted:
        page = queries.list_categories(include_archived=True, include_deleted=True)
        items = [item for item in page.get("items", []) if item.get("deleted_at") is not None]
    else:
        page = queries.list_categories(include_archived=include_archived, include_deleted=False)
        items = list(page.get("items", []))
    if exclude_system:
        items = [item for item in items if not item.get("is_system")]
    return _select_id(
        items,
        prompt=prompt,
        resource_plural="categories",
        allow_skip=allow_skip,
    )


def pick_hashtag(
    *,
    multi: bool = False,
    include_archived: bool = False,
    allow_skip: bool = False,
    prompt: str = "Hashtag",
) -> object:
    """Pick one or many hashtags from the local cache.

    `allow_skip=True` (single-select only) prepends a `(skip)` choice that
    returns SKIP. Ignored when `multi=True` — empty checkbox selection
    represents "no hashtags" naturally.
    """
    page = queries.list_hashtags(include_archived=include_archived, include_deleted=False)
    items = page.get("items", [])
    if not items:
        _empty_hint("hashtags")
        return BACK
    choices: list = []
    if allow_skip and not multi:
        choices.append(questionary.Choice(title="(skip — leave blank)", value=SKIP))
    choices.extend(
        questionary.Choice(
            title=_format_choice(item.get("name") or "(unnamed)", item["id"]),
            value=item["id"],
        )
        for item in items
    )
    if multi:
        answer = questionary.checkbox(prompt, choices=choices).ask()
    else:
        answer = questionary.select(prompt, choices=choices).ask()
    if answer is None:
        return BACK
    return answer


def _format_inbox_choice(item: dict) -> str:
    title = item.get("title") or "(no title)"
    amount = item.get("amount_cents")
    amount_s = "(no amount)" if amount is None else f"{amount:+d}"
    date_raw = item.get("date") or ""
    date_short = date_raw[:10] if isinstance(date_raw, str) else ""
    item_id = item.get("id", "")
    return f"{title}  · {amount_s}  · {date_short}  · {item_id[:8]}…"


def pick_inbox(
    *,
    only_deleted: bool = False,
    prompt: str = "Inbox item",
) -> object:
    """Pick an inbox item from the cached replica.

    `only_deleted=True` filters to soft-deleted drafts (for Restore).
    Otherwise returns active drafts only.
    """
    page = queries.list_inbox(include_deleted=only_deleted)
    items = page.get("items", [])
    if only_deleted:
        items = [it for it in items if it.get("deleted_at") is not None]
    if not items:
        if only_deleted:
            typer.echo("No deleted inbox items found.", err=True)
        else:
            _empty_hint("inbox")
        return BACK
    choices = [
        questionary.Choice(title=_format_inbox_choice(item), value=item["id"]) for item in items
    ]
    answer = questionary.select(prompt, choices=choices).ask()
    if answer is None:
        return BACK
    return answer


def _format_transaction_choice(item: dict) -> str:
    """Same shape as `_format_inbox_choice` — title · signed-amount · date · id."""
    title = item.get("title") or "(no title)"
    amount = item.get("amount_cents")
    amount_s = "(no amount)" if amount is None else f"{amount:+d}"
    date_raw = item.get("date") or ""
    date_short = date_raw[:10] if isinstance(date_raw, str) else ""
    item_id = item.get("id", "")
    return f"{title}  · {amount_s}  · {date_short}  · {item_id[:8]}…"


def pick_transaction(
    *,
    only_deleted: bool = False,
    prompt: str = "Transaction",
) -> object:
    """Pick a transaction from the local cached replica.

    Defaults to 100 most recent (cache orders by date DESC, created_at DESC).
    `only_deleted=True` filters to soft-deleted rows (for Restore).
    """
    page = queries.list_transactions(limit=100)
    items = page.get("items", [])
    if only_deleted:
        # list_transactions filters out deleted rows by default; pull a wider
        # include-deleted view via a second call.
        page = _list_transactions_with_deleted()
        items = [it for it in page.get("items", []) if it.get("deleted_at") is not None]
    if not items:
        if only_deleted:
            typer.echo("No deleted transactions found.", err=True)
        else:
            _empty_hint("transactions")
        return BACK
    choices = [
        questionary.Choice(title=_format_transaction_choice(item), value=item["id"])
        for item in items
    ]
    answer = questionary.select(prompt, choices=choices).ask()
    if answer is None:
        return BACK
    return answer


def _list_transactions_with_deleted() -> dict:
    """Bypass list_transactions's default `deleted_at IS NULL` filter.

    list_transactions does not currently expose include_deleted, so we go
    one level deeper for the Restore flow.
    """
    from expense.cache import db

    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT body FROM transactions ORDER BY date DESC, "
            "json_extract(body, '$.created_at') DESC LIMIT 100"
        ).fetchall()
    finally:
        conn.close()
    import json

    return {"items": [json.loads(r["body"]) for r in rows]}


def pick_reconciliation(
    *,
    account_id: str,
    prompt: str = "Reconciliation",
) -> object:
    page = queries.list_reconciliations(account_id=account_id, include_deleted=False)
    items = page.get("items", [])
    if not items:
        _empty_hint("reconciliations")
        return BACK
    choices = [
        questionary.Choice(
            title=_format_choice(item.get("name") or "(unnamed)", item["id"]),
            value=item["id"],
        )
        for item in items
    ]
    answer = questionary.select(prompt, choices=choices).ask()
    if answer is None:
        return BACK
    return answer


def confirm_destructive(message: str, warning: str | None = None) -> bool:
    """Two-step destructive confirm. Default highlight on 'No'.

    Mirrors the intent of `require_yes` in `expense.commands._resource` but for
    the menu UI context — the user is already inside an interactive session, so
    we always prompt (never a silent --yes bypass).
    """
    if warning:
        typer.secho(warning, fg=typer.colors.YELLOW)
    answer = questionary.select(
        message,
        choices=[
            questionary.Choice(title="No", value=False),
            questionary.Choice(title="Yes, do it", value=True),
        ],
        default=False,
    ).ask()
    return bool(answer)


def prompt_signed_amount(prompt: str, *, allow_skip: bool = False) -> int | None:
    """Signed-cents text prompt. Negative = expense, positive = income.

    Sign is literal — there is no default-to-expense convenience. Rejects 0.
    Returns None only if `allow_skip=True` and the user enters an empty string.
    """

    def _validate(raw: str) -> bool | str:
        if raw == "" and allow_skip:
            return True
        try:
            value = int(raw)
        except ValueError:
            return "Must be an integer in signed cents (e.g. -450 for -$4.50)."
        if value == 0:
            return "Amount must be non-zero."
        return True

    answer = questionary.text(prompt, validate=_validate).ask()
    if answer is None:
        return None
    if answer == "" and allow_skip:
        return None
    return int(answer)
