"""Shared, importable helpers for tests/unit — the non-fixture half of the
test infrastructure (fixtures live in conftest.py).

Import style: `from tests.unit.helpers import FakeClient, wait_for, ...`.
Keep this module free of Textual imports at module level so CLI command test
files pay no TUI import cost.
"""

import json
from collections.abc import Callable
from typing import Any

import pytest
import typer

from expense.context import AppContext
from expense.errors import EngineError

ENGINE_URL = "https://api.example.com"


# ---------------------------------------------------------------------------
# Typer root wiring
# ---------------------------------------------------------------------------


def make_cli_app(
    sub_app: typer.Typer | None = None,
    name: str | None = None,
    *,
    commands: dict[str, Callable] | None = None,
) -> typer.Typer:
    """Root Typer app wired like expense/__main__.py (minus --verbose).

    The callback sets ctx.obj = AppContext with --no-cache (EXPENSE_STATELESS)
    and --no-sync-after (EXPENSE_NO_SYNC_AFTER), so tests drive cache modes
    exactly like production. Two mount styles:

        make_cli_app(accounts_app, "accounts")            # add_typer group
        make_cli_app(commands={"dashboard": dashboard})   # bare command(s)
    """
    cli_app = typer.Typer()

    @cli_app.callback()
    def _root(
        ctx: typer.Context,
        no_cache: bool = typer.Option(False, "--no-cache", envvar="EXPENSE_STATELESS"),
        no_sync_after: bool = typer.Option(
            False, "--no-sync-after", envvar="EXPENSE_NO_SYNC_AFTER"
        ),
    ) -> None:
        ctx.obj = AppContext(no_cache=no_cache, no_sync_after=no_sync_after)

    if sub_app is not None:
        cli_app.add_typer(sub_app, name=name)
    for command_name, callback in (commands or {}).items():
        cli_app.command(command_name)(callback)
    return cli_app


# ---------------------------------------------------------------------------
# Engine payload builders
# ---------------------------------------------------------------------------


def sync_payload(**overrides) -> dict:
    """Full /v1/sync envelope with empty entity lists; kwargs replace top-level
    keys: sync_payload(accounts=[row]) or sync_payload(settings={...})."""
    payload: dict[str, Any] = {
        "sync_token": "tok-1",
        "accounts": [],
        "categories": [],
        "hashtags": [],
        "inbox": [],
        "transactions": [],
        "reconciliations": [],
        "settings": {"user_id": "u1", "main_currency": "PEN", "version": 1},
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Replica row inserts (schema mirrors expense/cache/db.py)
# ---------------------------------------------------------------------------


def insert_account(conn, row: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO accounts "
        "(id, user_id, is_archived, is_person, deleted_at, sort_order, version, body) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            row["id"],
            row.get("user_id"),
            1 if row.get("is_archived") else 0,
            1 if row.get("is_person") else 0,
            row.get("deleted_at"),
            row.get("sort_order"),
            row.get("version"),
            json.dumps(row),
        ),
    )


def insert_category(conn, row: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO categories "
        "(id, user_id, is_archived, is_system, deleted_at, sort_order, version, body) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            row["id"],
            row.get("user_id"),
            1 if row.get("is_archived") else 0,
            1 if row.get("is_system") else 0,
            row.get("deleted_at"),
            row.get("sort_order"),
            row.get("version"),
            json.dumps(row),
        ),
    )


def insert_hashtag(conn, row: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO hashtags "
        "(id, user_id, is_archived, deleted_at, sort_order, version, body) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            row["id"],
            row.get("user_id"),
            1 if row.get("is_archived") else 0,
            row.get("deleted_at"),
            row.get("sort_order"),
            row.get("version"),
            json.dumps(row),
        ),
    )


def insert_inbox(conn, row: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO inbox "
        "(id, user_id, account_id, category_id, status, date, deleted_at, version, body) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            row["id"],
            row.get("user_id"),
            row.get("account_id"),
            row.get("category_id"),
            row.get("status"),
            row.get("date"),
            row.get("deleted_at"),
            row.get("version"),
            json.dumps(row),
        ),
    )


def insert_transaction(conn, row: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO transactions "
        "(id, user_id, account_id, category_id, reconciliation_id, parent_transaction_id, "
        "transfer_transaction_id, inbox_id, date, deleted_at, version, updated_at, body) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            row["id"],
            row.get("user_id"),
            row.get("account_id"),
            row.get("category_id"),
            row.get("reconciliation_id"),
            row.get("parent_transaction_id"),
            row.get("transfer_transaction_id"),
            row.get("inbox_id"),
            row.get("date"),
            row.get("deleted_at"),
            row.get("version"),
            row.get("updated_at"),
            json.dumps(row),
        ),
    )


def insert_reconciliation(conn, row: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO reconciliations "
        "(id, user_id, account_id, status, sort_order, date_end, deleted_at, version, body) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            row["id"],
            row.get("user_id"),
            row.get("account_id"),
            row.get("status"),
            row.get("sort_order"),
            row.get("date_end"),
            row.get("deleted_at"),
            row.get("version"),
            json.dumps(row),
        ),
    )


# ---------------------------------------------------------------------------
# TUI fakes and waits
# ---------------------------------------------------------------------------


class FakeClient:
    """Instance-level recorder standing in for expense.http.ExpenseClient.

    Only intercepts LAZY imports (`from expense.http import ExpenseClient`
    inside a function) — all TUI write/read sites qualify. CLI command modules
    bind ExpenseClient at module top; keep respx for those.

    Every request is recorded as (METHOD, path, body) in `calls`; the
    `requests`/`posts`/`puts`/`deletes` properties are filtered views. GETs
    answer from `get_responses` (miss → EngineError 404, matching the engine's
    not-provisioned behavior). Set `errors["POST"] = exc` to make a verb raise.
    `refreshes` counts refresh_after_write calls (wired by the fake_client
    fixture in conftest.py).
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.get_responses: dict[str, Any] = {}
        self.errors: dict[str, Exception] = {}
        self.refreshes = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def _record(self, method: str, path: str, body: Any = None) -> None:
        self.calls.append((method, path, body))
        err = self.errors.get(method)
        if err is not None:
            raise err

    def get(self, path: str, *, auth: bool = True, params: dict | None = None) -> dict:
        self._record("GET", path, params)
        if path in self.get_responses:
            return self.get_responses[path]
        raise EngineError("NOT_FOUND", f"no fake response for GET {path}", None, 404, {})

    def post(self, path: str, json_body: dict | None = None) -> dict:
        self._record("POST", path, json_body)
        return {}

    def put(self, path: str, json_body: dict | None = None) -> dict:
        self._record("PUT", path, json_body)
        return {}

    def delete(self, path: str) -> dict:
        self._record("DELETE", path)
        return {}

    @property
    def requests(self) -> list[tuple[str, str]]:
        return [(method, path) for method, path, _ in self.calls]

    @property
    def posts(self) -> list[tuple[str, Any]]:
        return [(path, body) for method, path, body in self.calls if method == "POST"]

    @property
    def puts(self) -> list[tuple[str, Any]]:
        return [(path, body) for method, path, body in self.calls if method == "PUT"]

    @property
    def deletes(self) -> list[str]:
        return [path for method, path, _ in self.calls if method == "DELETE"]


async def wait_for(
    pilot,
    predicate: Callable[[], object],
    *,
    timeout: float = 2.0,
    interval: float = 0.02,
    message: str | None = None,
) -> None:
    """Pause the pilot until predicate() is truthy.

    Fails the test on timeout — a timed-out wait should point at the wait
    site, not surface as a confusing assert a few lines later.
    """
    for _ in range(max(1, round(timeout / interval))):
        await pilot.pause(interval)
        if predicate():
            return
    pytest.fail(message or f"wait_for: condition still false after {timeout}s")


async def wait_for_loaded(pilot, app) -> None:
    """Until the active SectionScreen resolved — #card (data) or .error mounted."""
    await wait_for(
        pilot,
        lambda: bool(app.screen.query("#card")) or bool(app.screen.query(".error")),
        message="SectionScreen never finished loading (no #card or .error mounted)",
    )
