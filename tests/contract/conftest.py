"""Shared gating, target resolution and the real-ledger guard for tests/contract.

These tests hit a real engine and make real writes. Before this file existed, each
test module resolved its own target, and three of the five signed in as the
developer via `~/.expense-config` — so `pytest tests/contract` wrote to the one true
ledger with the real credential, and cleanup was soft-delete, leaving tombstones
behind forever. Two modules also still defaulted to the Render host that was
switched off 2026-07-30.

The rule now (backlog Phase 5, decided 2026-08-16 — option C of
docs/mockups/expense-world-phase5-sketch.html): a contract run that would write to
the real ledger **refuses to start**. Point it at the disposable practice database
instead, or set EXPENSE_ALLOW_REAL_LEDGER=1 to say you meant it.

    # the normal, isolated way (see ../../../expense_world_engine/deploy/local/)
    deploy/local/seed-test-user.sh
    SUPABASE_DB_URL=…/expense_world_test python -m uvicorn app.main:app --port 8001
    PYTEST_LIVE=1 EXPENSE_PAT=<seeded> EXPENSE_ENGINE_URL=http://127.0.0.1:8001 \
        pytest tests/contract

Full ops guide: docs/cli-runtime.md "Working against the live engine".
"""

import os

import pytest

from expense import config as config_module
from expense.config import Config
from expense.http import ExpenseClient

# There is one engine: the local deployment. The old default was the mothballed
# cloud host, which made EXPENSE_ENGINE_URL effectively mandatory while the docs
# claimed the defaults suited the local profile.
DEFAULT_ENGINE_URL = "http://127.0.0.1:8000"

ENGINE_URL = os.environ.get("EXPENSE_ENGINE_URL", DEFAULT_ENGINE_URL)
PAT = os.environ.get("EXPENSE_PAT")
ALLOW_REAL_LEDGER = os.environ.get("EXPENSE_ALLOW_REAL_LEDGER") == "1"

LIVE = os.environ.get("PYTEST_LIVE") == "1"


def pytest_collection_modifyitems(config, items):
    """Gate the whole directory on PYTEST_LIVE=1.

    This is a hook, not a module-level `pytestmark`: a `pytestmark` assigned in a
    conftest does NOT apply to tests in other modules. Relying on that was a real
    incident on 2026-08-16 — the per-module marks were removed in favour of one in
    this file, and `pytest tests/contract` promptly ran against the live engine and
    created rows. The gate belongs somewhere that provably covers every item.
    """
    if LIVE:
        return
    skip = pytest.mark.skip(reason="Contract tests require PYTEST_LIVE=1")
    for item in items:
        item.add_marker(skip)


_REFUSAL = """
┌────────────────────────────────────────────────────────────┐
│  REFUSING TO RUN                                           │
│  this would write to your real ledger                      │
│    engine       {url:<42}│
│    signed in as you, from ~/.expense-config                │
│    rows created here are soft-deleted, never removed       │
│                                                            │
│  practice database instead:                                │
│    ../expense_world_engine/deploy/local/seed-test-user.sh  │
│    then EXPENSE_PAT=… EXPENSE_ENGINE_URL=http://127.0.0.1:8001
│                                                            │
│  or, to mean it:                                           │
│    EXPENSE_ALLOW_REAL_LEDGER=1                             │
└────────────────────────────────────────────────────────────┘
"""


def _is_real_ledger() -> bool:
    """True when the run would write as the developer, to their own ledger.

    A PAT in the environment is the isolation signal: it is how the practice user
    is addressed. Without one, the only credential available is the developer's
    saved config — which is the real ledger by definition, whatever the URL says.
    """
    return not PAT


def pytest_sessionstart(session):
    """Option C: refuse rather than warn — before collection, before any fixture.

    Deliberately a session hook rather than an autouse fixture: a fixture only runs
    when something requests it, and the guard must hold even if a future test
    forgets the `client` fixture entirely.
    """
    if not LIVE:
        return
    if _is_real_ledger() and not ALLOW_REAL_LEDGER:
        pytest.exit(_REFUSAL.format(url=ENGINE_URL), returncode=2)
    source = "EXPENSE_PAT" if PAT else "~/.expense-config (ALLOWED EXPLICITLY)"
    print(f"\ncontract target: {ENGINE_URL} · credential: {source}")


@pytest.fixture
def client():
    """An ExpenseClient aimed at the resolved target.

    Prefers EXPENSE_PAT + EXPENSE_ENGINE_URL so every module obeys the same target
    as the freshman walk; falls back to the developer's config only when the guard
    above has explicitly allowed it.
    """
    cfg = Config(engine_url=ENGINE_URL, token=PAT) if PAT else config_module.ensure_loaded()
    with ExpenseClient(cfg) as c:
        yield c
