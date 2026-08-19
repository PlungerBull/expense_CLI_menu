"""Shared, importable helpers for tests/unit — the non-fixture half of the
test infrastructure (fixtures live in conftest.py).

Import style: `from tests.unit.helpers import FakeClient, wait_for, ...`.
Keep this module free of Textual imports at module level so CLI command test
files pay no TUI import cost.
"""

import re
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

    Two mount styles:

        make_cli_app(accounts_app, "accounts")            # add_typer group
        make_cli_app(commands={"dashboard": dashboard})   # bare command(s)
    """
    cli_app = typer.Typer()

    @cli_app.callback()
    def _root(ctx: typer.Context) -> None:
        ctx.obj = AppContext()

    if sub_app is not None:
        cli_app.add_typer(sub_app, name=name)
    for command_name, callback in (commands or {}).items():
        cli_app.command(command_name)(callback)
    return cli_app


# ---------------------------------------------------------------------------
# CLI output normalisation
# ---------------------------------------------------------------------------


_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[mGKH]")


def strip_panel(output: str) -> str:
    """Flatten Typer/Rich error output to one plain, searchable line.

    Rich decides whether to colour by sniffing the environment, so the *same*
    error prints differently in CI than it does locally: GitHub Actions is
    treated as a terminal, which wraps usage errors in a box AND highlights the
    offending flag — splicing escape codes *inside* the token, so a plain
    ``"No such option: --include-deleted" in result.output`` finds nothing
    (`--include-deleted` arrives as `-` + `-include` + `-deleted`). CI was red
    from 2026-08-17 to 2026-08-19 for exactly that reason.

    Assert against this, never raw ``result.output``, whenever the expected text
    contains a flag name or could wrap at the panel edge.
    """
    no_ansi = _ANSI_ESCAPE_RE.sub("", output)
    no_box = "".join(c for c in no_ansi if c not in "│╭╮╰╯─\n\t")
    return " ".join(no_box.split())


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
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.get_responses: dict[str, Any] = {}
        self.errors: dict[str, Exception] = {}

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


def list_ready(app) -> bool:
    """The active SectionScreen's CursorList is mounted and its loader is gone.

    Exposed as a plain predicate, not only as the waiter below, so call sites
    that need an *extra* condition (a row count, a filtered legend) can write
    `list_ready(app) and ...` instead of re-open-coding the pair.
    """
    from expense.tui.widgets.cursor_list import CursorList  # local: see module docstring

    return bool(app.screen.query(CursorList)) and not app.screen.query("#content LoadingIndicator")


async def wait_for_list(pilot, app) -> None:
    """Until the active SectionScreen's list is mounted and done loading."""
    await wait_for(
        pilot,
        lambda: list_ready(app),
        message="list never finished loading (no CursorList, or LoadingIndicator still up)",
    )
