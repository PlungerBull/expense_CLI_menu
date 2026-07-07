"""Step 9 gate — freshman flow E2E (live engine).

Walks a brand-new user through the exact path Step 9 gate criterion 4 calls out:

    config set → ping → auth bootstrap → auth me
    → accounts create → categories create → log → dashboard → cleanup

Hits the live engine. Gated on PYTEST_LIVE=1 and EXPENSE_PAT.
Redirects EXPENSE_CONFIG and EXPENSE_CACHE to a temp dir so the developer's
real install is untouched.

Uses a USD account regardless of the user's main_currency — the engine has
FX rates available (USD→PEN at 3.75 as of 2026-05-10), so cross-currency
writes succeed. If RATE_UNAVAILABLE starts firing again, that's an engine
regression to investigate, not a known-broken state to work around.
"""

import json
import os
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from expense.__main__ import app

ENGINE_URL = os.environ.get("EXPENSE_ENGINE_URL", "https://expense-world-engine.onrender.com")
PAT = os.environ.get("EXPENSE_PAT")

pytestmark = pytest.mark.skipif(
    os.environ.get("PYTEST_LIVE") != "1" or not PAT,
    reason="Freshman flow requires PYTEST_LIVE=1 and EXPENSE_PAT",
)


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("EXPENSE_CONFIG", str(tmp_path / "config"))
    monkeypatch.setenv("EXPENSE_CACHE", str(tmp_path / "cache.sqlite3"))
    return tmp_path


def _run(*args):
    runner = CliRunner()
    return runner.invoke(app, list(args), catch_exceptions=False)


def _assert_ok(result, label):
    assert result.exit_code == 0, (
        f"{label} failed (exit={result.exit_code}).\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def _parse_json_stdout(stdout: str) -> dict:
    text = stdout.lstrip()
    if not text.startswith("{") and not text.startswith("["):
        # `--json` suppresses the "Created: <id>" prefix line in writes, but be defensive.
        idx = text.find("{")
        if idx == -1:
            raise AssertionError(f"No JSON object in stdout:\n{stdout}")
        text = text[idx:]
    return json.loads(text)


def test_freshman_flow(isolated_env):
    config_file = isolated_env / "config"

    _assert_ok(
        _run("config", "set", "--engine-url", ENGINE_URL, "--token", PAT),
        "config set",
    )
    assert config_file.exists(), "config file was not created at the EXPENSE_CONFIG path"

    _assert_ok(_run("ping"), "ping")
    _assert_ok(_run("auth", "bootstrap"), "auth bootstrap")

    me_result = _run("auth", "me", "--json")
    _assert_ok(me_result, "auth me --json")
    me = _parse_json_stdout(me_result.stdout)
    assert me.get("user", {}).get("id"), f"auth me missing user.id: {me}"

    account_id = None
    category_id = None
    transaction_id = None
    suffix = uuid4().hex[:8]
    try:
        result = _run(
            "accounts",
            "create",
            "--name",
            f"freshman-{suffix}",
            "--currency-code",
            "USD",
            "--json",
        )
        _assert_ok(result, "accounts create")
        account_id = _parse_json_stdout(result.stdout)["id"]

        result = _run("categories", "create", "--name", f"freshman-cat-{suffix}", "--json")
        _assert_ok(result, "categories create")
        category_id = _parse_json_stdout(result.stdout)["id"]

        result = _run(
            "log",
            "--title",
            "freshman smoke",
            "--amount",
            "-100",
            "--account-id",
            account_id,
            "--category-id",
            category_id,
            "--json",
        )
        _assert_ok(result, "log")
        transaction_id = _parse_json_stdout(result.stdout)["id"]

        dashboard_result = _run("dashboard", "--json")
        _assert_ok(dashboard_result, "dashboard --json")
        dashboard = _parse_json_stdout(dashboard_result.stdout)
        assert any(key in dashboard for key in ("totals", "accounts", "bank_accounts")), (
            f"dashboard --json missing expected keys; got: {sorted(dashboard.keys())}"
        )

    finally:
        # Best-effort cleanup; reverse dependency order. Ignore failures.
        if transaction_id:
            _run("transactions", "delete", transaction_id, "--yes")
        if category_id:
            _run("categories", "delete", category_id, "--yes")
        if account_id:
            _run("accounts", "delete", account_id, "--yes")
