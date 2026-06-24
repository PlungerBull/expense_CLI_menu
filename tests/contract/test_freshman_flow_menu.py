"""Step 9.5.16 — freshman flow E2E via the interactive menu (live engine).

Sibling to test_freshman_flow.py. Where that test drives the flat command
surface, this one walks a brand-new user through the *menu* freshman path:

    Config → set engine URL → set token
    → Auth → bootstrap
    → Accounts → create
    → Categories → create
    → Log a transaction
    → Reports → Outstanding Amounts (current month)

Each menu flow delegates to the same flat command the CLI runs, and those
write paths call `cache_after_write`, refreshing the local SQLite replica. So
the account and category created via the menu land in the cache and show up in
the Log flow's `pick_account` / `pick_category` pickers — no manual sync. That
only holds with caching enabled, so this test runs with a cache-backed context
(no EXPENSE_STATELESS).

The walk is driven the same way the menu unit tests drive flows: a
`_PromptScript` answer queue monkeypatched onto each module's `questionary`.
We call each group's entry function in sequence rather than the root menu loop,
so a break is isolated to one leg. Each `run_*_menu` still runs its own select
loop and is exited via "← Back".

Hits the live engine. Gated on PYTEST_LIVE=1 and EXPENSE_PAT. Redirects
EXPENSE_CONFIG / EXPENSE_CACHE to a temp dir so the developer's real install is
untouched, and sets EXPENSE_NO_CLEAR=1 so clear_screen() leaves captured stdout
intact.

Uses a USD account regardless of the user's main_currency — the engine has FX
rates available (USD→PEN at 3.75 as of 2026-05-10), so cross-currency writes
succeed. If RATE_UNAVAILABLE starts firing again, that's an engine regression to
investigate, not a known-broken state to work around.
"""

import os
import re
from uuid import uuid4

import pytest

from expense import config as config_module
from expense.commands import accounts_cmd, categories_cmd, transactions_cmd
from expense.context import AppContext
from expense.menu import prompts
from expense.menu.groups import _common as menu_common
from expense.menu.groups import accounts as menu_accounts
from expense.menu.groups import auth as menu_auth
from expense.menu.groups import categories as menu_categories
from expense.menu.groups import config as menu_config
from expense.menu.groups import log as menu_log
from expense.menu.groups import reports as menu_reports

ENGINE_URL = os.environ.get("EXPENSE_ENGINE_URL", "https://expense-world-engine.onrender.com")
PAT = os.environ.get("EXPENSE_PAT")

pytestmark = pytest.mark.skipif(
    os.environ.get("PYTEST_LIVE") != "1" or not PAT,
    reason="Freshman menu flow requires PYTEST_LIVE=1 and EXPENSE_PAT",
)

_CREATED_ID_RE = re.compile(r"Created:\s*([0-9a-fA-F-]{36})")


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("EXPENSE_CONFIG", str(tmp_path / "config"))
    monkeypatch.setenv("EXPENSE_CACHE", str(tmp_path / "cache.sqlite3"))
    # clear_screen() is a no-op under this flag, so the menu's screen wipes
    # don't shred the stdout we assert on.
    monkeypatch.setenv("EXPENSE_NO_CLEAR", "1")
    return tmp_path


class _FakeAsk:
    """Minimal stand-in for a questionary prompt object."""

    def __init__(self, answer):
        self._answer = answer

    def ask(self):
        if isinstance(self._answer, BaseException):
            raise self._answer
        return self._answer


class _PromptScript:
    """One answer queue, popped per questionary call regardless of prompt type."""

    def __init__(self, answers: list):
        self._queue = list(answers)

    def __call__(self, *_args, **_kwargs):
        if not self._queue:
            raise AssertionError("Prompt script exhausted — unexpected questionary call.")
        return _FakeAsk(self._queue.pop(0))

    @property
    def remaining(self) -> int:
        return len(self._queue)


# Every module the freshman walk touches that does `import questionary`.
# log.py is intentionally absent — it has no direct questionary import; its
# prompts route through _common and prompts, which are patched here.
_PATCH_TARGETS = (
    menu_common,
    prompts,
    menu_config,
    menu_auth,
    menu_accounts,
    menu_categories,
    menu_reports,
)


def _patch_questionary(monkeypatch, script: _PromptScript) -> None:
    for module in _PATCH_TARGETS:
        for attr in ("select", "text", "password", "checkbox"):
            monkeypatch.setattr(module.questionary, attr, script)


def _make_ctx() -> object:
    """A context with caching live — so cache_after_write populates pickers."""

    class _StubCtx:
        obj = AppContext(verbose=False, no_cache=False, no_sync_after=False)

    return _StubCtx()


def _run_leg(monkeypatch, entry_fn, ctx, answers: list) -> None:
    script = _PromptScript(answers)
    _patch_questionary(monkeypatch, script)
    entry_fn(ctx)
    assert script.remaining == 0, (
        f"{entry_fn.__qualname__} left {script.remaining} unused prompt answer(s) — "
        "the flow asked fewer questions than scripted."
    )


def _assert_clean(capsys, label: str) -> str:
    captured = capsys.readouterr()
    lowered = captured.err.lower()
    assert "error" not in lowered and "traceback" not in lowered, (
        f"{label} surfaced an error.\nstdout:\n{captured.out}\nstderr:\n{captured.err}"
    )
    return captured.out


def _captured_created_id(out: str, label: str) -> str:
    match = _CREATED_ID_RE.search(out)
    assert match, f"{label} did not print a 'Created: <id>' line.\nstdout:\n{out}"
    return match.group(1)


def test_freshman_flow_via_menu(isolated_env, monkeypatch, capsys):
    ctx = _make_ctx()
    suffix = uuid4().hex[:8]

    account_id = None
    category_id = None
    transaction_id = None
    try:
        # 1. Config — set engine URL then token, both via the menu.
        _run_leg(
            monkeypatch,
            menu_config.run_config_menu,
            ctx,
            [
                "Set engine URL",
                ENGINE_URL,  # Engine URL text
                True,  # Confirm and save?
                "",  # pause
                "Set token (PAT)",
                PAT,  # Token password
                True,  # Save token?
                "",  # pause
                "← Back",
            ],
        )
        _assert_clean(capsys, "config")
        cfg = config_module.load()
        assert cfg is not None and cfg.engine_url == ENGINE_URL, "engine URL not saved"
        assert cfg.token, "token not saved"

        # 2. Auth — bootstrap (idempotent on the live engine).
        _run_leg(
            monkeypatch,
            menu_auth.run_auth_menu,
            ctx,
            [
                "Bootstrap (first-time login)",
                "Freshman",  # display name
                "",  # timezone (auto-detect)
                True,  # Confirm and call engine?
                "",  # pause
                "← Back",
            ],
        )
        _assert_clean(capsys, "auth bootstrap")

        # 3. Accounts — create a USD account.
        _run_leg(
            monkeypatch,
            menu_accounts.run_accounts_menu,
            ctx,
            [
                "Create an account",
                f"freshman-{suffix}",  # name
                "USD",  # currency
                "",  # color (skip)
                "",  # sort order (skip)
                True,  # Confirm and submit?
                "",  # pause
                "← Back",
            ],
        )
        account_id = _captured_created_id(
            _assert_clean(capsys, "accounts create"), "accounts create"
        )

        # 4. Categories — create a category (color is required here).
        _run_leg(
            monkeypatch,
            menu_categories.run_categories_menu,
            ctx,
            [
                "Create a category",
                f"freshman-cat-{suffix}",  # name
                "#3366FF",  # color
                "",  # sort order (skip)
                True,  # Confirm and submit?
                "",  # pause
                "← Back",
            ],
        )
        category_id = _captured_created_id(
            _assert_clean(capsys, "categories create"), "categories create"
        )

        # 5. Log — the new account/category appear in the cache-backed pickers.
        _run_leg(
            monkeypatch,
            menu_log.run_log_flow,  # root shortcut: no sub-menu, no "← Back"
            ctx,
            [
                "freshman smoke",  # title
                "-100",  # signed amount (cents)
                account_id,  # pick_account → popped value
                category_id,  # pick_category → popped value
                False,  # Set additional optional fields?
                True,  # Confirm and submit?
                "",  # pause
            ],
        )
        transaction_id = _captured_created_id(_assert_clean(capsys, "log"), "log")

        # 6. Outstanding Amounts (via the Reports umbrella) — current month
        #    renders against the live engine (GET /v1/dashboard).
        _run_leg(
            monkeypatch,
            menu_reports.run_reports_menu,
            ctx,
            [
                "Outstanding Amounts (current month)",
                "",  # pause
                "← Back",
            ],
        )
        out = _assert_clean(capsys, "dashboard")
        assert out.strip(), "dashboard rendered no output"

    finally:
        # Best-effort cleanup; reverse dependency order. Ignore failures.
        if transaction_id:
            try:
                transactions_cmd.delete(ctx, id_=transaction_id, yes=True, json_output=True)
            except Exception:
                pass
        if category_id:
            try:
                categories_cmd.delete(ctx, id_=category_id, yes=True, json_output=True)
            except Exception:
                pass
        if account_id:
            try:
                accounts_cmd.delete(ctx, id_=account_id, yes=True, json_output=True)
            except Exception:
                pass
