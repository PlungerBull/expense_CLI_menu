"""Shared fixtures for tests/unit. Non-fixture helpers: tests/unit/helpers.py.

A file-local fixture with the same name shadows these, so files can migrate
one at a time by deleting their local copy — never leave a diverged local
fixture named `configured` behind.
"""

import socket

import pytest

from expense import config as config_module
from tests.unit import helpers

# Loopback stays reachable so a locally-bound helper never trips the guard;
# every engine URL in the suite is a real hostname, which does not.
_ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


@pytest.fixture(autouse=True)
def _block_real_network(monkeypatch):
    """Backstop: fail loudly if a unit test reaches the real network.

    respx intercepts at the httpcore layer, so a *mocked* request never opens a
    socket — only a request that no respx route matched (a forgotten
    ``@respx.mock``, a URL typo) falls through to a real DNS lookup / connect and
    trips this guard. The suite's hermeticity used to rest on the tmp-path
    redirect plus per-test convention alone (backlog §5); this makes a leak a
    hard failure instead of a silent production ping.
    """
    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect

    def _guard(host: object) -> None:
        if str(host) not in _ALLOWED_HOSTS:
            raise RuntimeError(
                f"Real network blocked in unit tests: attempted to reach {host!r}. "
                "Mock it with @respx.mock (or use the fake_client fixture)."
            )

    def _fake_getaddrinfo(host, *args, **kwargs):
        _guard(host)
        return real_getaddrinfo(host, *args, **kwargs)

    def _fake_connect(self, address):
        _guard(address[0] if isinstance(address, tuple) else address)
        return real_connect(self, address)

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", _fake_connect)
    yield


@pytest.fixture(autouse=True)
def _hermetic_paths(tmp_path, monkeypatch):
    """Point the config env at a nonexistent tmp file for EVERY test.

    Every ExpenseApp launch mounts HomeScreen, whose header stat worker
    (net · spent · owed) calls ensure_loaded + fetch_dashboard on mount —
    without this, tests would read the developer's actual ~/.expense-config
    and could ping a real engine. (The worker is failure-silent, so with this
    tmp path ensure_loaded raises and it no-ops.) `configured` re-sets the env
    var afterward and still wins.
    """
    monkeypatch.setenv("EXPENSE_CONFIG", str(tmp_path / "hermetic-config"))
    yield


@pytest.fixture
def configured(tmp_path, monkeypatch):
    """Config saved under tmp_path — every command runs engine-direct."""
    monkeypatch.setenv("EXPENSE_CONFIG", str(tmp_path / ".expense-config"))
    config_module.save(
        config_module.Config(
            engine_url=helpers.ENGINE_URL,
            token="ewe_pat_test",
        )
    )
    yield


@pytest.fixture
def fake_client(monkeypatch):
    """A helpers.FakeClient wired into the TUI's lazy-import seams.

    Patches expense.http.ExpenseClient (factory returning this one instance)
    and expense.config.ensure_loaded (opaque stub — re-monkeypatch after
    taking this fixture if a test needs a real Config). CLI command modules
    import ExpenseClient at module top — keep respx for those.
    """
    client = helpers.FakeClient()

    monkeypatch.setattr("expense.http.ExpenseClient", lambda *a, **k: client)
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())
    return client
