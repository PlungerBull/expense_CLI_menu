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
) -> object:
    if not items:
        _empty_hint(resource_plural)
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


def pick_account(
    *,
    include_archived: bool = False,
    include_people: bool = False,
    prompt: str = "Account",
) -> object:
    items = queries.list_accounts(
        include_archived=include_archived,
        include_deleted=False,
        include_people=include_people,
    )
    return _select_id(items, prompt=prompt, resource_plural="accounts")


def pick_category(
    *,
    include_archived: bool = False,
    prompt: str = "Category",
) -> object:
    page = queries.list_categories(include_archived=include_archived, include_deleted=False)
    return _select_id(page.get("items", []), prompt=prompt, resource_plural="categories")


def pick_hashtag(
    *,
    multi: bool = False,
    include_archived: bool = False,
    prompt: str = "Hashtag",
) -> object:
    page = queries.list_hashtags(include_archived=include_archived, include_deleted=False)
    items = page.get("items", [])
    if not items:
        _empty_hint("hashtags")
        return BACK
    choices = [
        questionary.Choice(
            title=_format_choice(item.get("name") or "(unnamed)", item["id"]),
            value=item["id"],
        )
        for item in items
    ]
    if multi:
        answer = questionary.checkbox(prompt, choices=choices).ask()
    else:
        answer = questionary.select(prompt, choices=choices).ask()
    if answer is None:
        return BACK
    return answer


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
        default="No",
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
