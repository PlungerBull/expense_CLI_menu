"""Shared fixtures for tests/unit. Non-fixture helpers: tests/unit/helpers.py.

A file-local fixture with the same name shadows these, so files can migrate
one at a time by deleting their local copy — never leave a diverged local
fixture named `configured` behind.
"""

from uuid import uuid4

import pytest

from expense import config as config_module
from expense.cache import db as cache_db
from expense.cache import state as cache_state
from tests.unit import helpers


@pytest.fixture(autouse=True)
def _hermetic_paths(tmp_path, monkeypatch):
    """Point config + cache env at nonexistent tmp files for EVERY test.

    Every ExpenseApp launch mounts HomeScreen, whose status line (backlog 4.3)
    reads real config/cache state — without this, tests would read the
    developer's actual ~/.expense-config and could ping a real engine.
    `configured` and friends re-set these env vars afterward and still win.
    """
    monkeypatch.setenv("EXPENSE_CONFIG", str(tmp_path / "hermetic-config"))
    monkeypatch.setenv("EXPENSE_CACHE", str(tmp_path / "hermetic-cache.sqlite3"))
    yield


@pytest.fixture
def configured(tmp_path, monkeypatch):
    """Config saved under tmp_path; cache redirected to tmp (never the real one).

    The cache file is NOT created — the replica is cold. Layer
    configured_stateless / configured_synced on top for the variants.
    """
    monkeypatch.setenv("EXPENSE_CONFIG", str(tmp_path / ".expense-config"))
    monkeypatch.setenv("EXPENSE_CACHE", str(tmp_path / "cache.sqlite3"))
    config_module.save(
        config_module.Config(
            engine_url=helpers.ENGINE_URL,
            token="ewe_pat_test",
            client_id=uuid4(),
        )
    )
    yield


@pytest.fixture
def configured_stateless(configured, monkeypatch):
    """configured + EXPENSE_STATELESS=1 — every command runs engine-direct."""
    monkeypatch.setenv("EXPENSE_STATELESS", "1")
    yield


@pytest.fixture
def configured_synced(configured):
    """configured + healthy empty replica (identity + sync token written), so
    ensure_synced/refresh_after_write run cheap deltas instead of cold-starts."""
    cfg = config_module.ensure_loaded()
    conn = cache_db.connect()
    try:
        cache_state.write_identity(
            conn,
            user_id="u1",
            client_id=str(cfg.client_id),
            engine_url=cfg.engine_url,
        )
        cache_state.write_token(conn, "tok-test")
    finally:
        conn.close()
    yield


@pytest.fixture
def fake_client(monkeypatch):
    """A helpers.FakeClient wired into the TUI's lazy-import seams.

    Patches expense.http.ExpenseClient (factory returning this one instance),
    expense.config.ensure_loaded (opaque stub — re-monkeypatch after taking
    this fixture if a test needs a real Config), and
    expense.cache.refresh_after_write (counted on client.refreshes).
    CLI command modules import ExpenseClient at module top — keep respx there.
    """
    client = helpers.FakeClient()

    def _bump_refreshes(*a, **k):
        client.refreshes += 1

    monkeypatch.setattr("expense.http.ExpenseClient", lambda *a, **k: client)
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())
    monkeypatch.setattr("expense.cache.refresh_after_write", _bump_refreshes)
    return client
