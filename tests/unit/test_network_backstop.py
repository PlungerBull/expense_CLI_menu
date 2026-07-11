"""The hermetic-network backstop must actually block a real outbound call.

Guards the autouse `_block_real_network` fixture in conftest.py: a unit test
that forgets `@respx.mock` and issues a live request should fail loudly rather
than silently pinging the production engine (backlog §5).
"""

import socket

import httpx
import pytest


def test_external_dns_lookup_is_blocked():
    with pytest.raises(RuntimeError, match="Real network blocked"):
        socket.getaddrinfo("api.example.com", 443)


def test_external_connect_is_blocked():
    with pytest.raises(RuntimeError, match="Real network blocked"):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect(("93.184.216.34", 443))  # a literal external IP, no DNS


def test_loopback_is_not_blocked_by_the_guard():
    # Loopback must pass the guard cleanly (it resolves; the guard is host-based).
    assert socket.getaddrinfo("127.0.0.1", 80)


def test_unmocked_httpx_request_never_reaches_the_network():
    # End-to-end: an httpx call with no respx route raises instead of hanging or
    # hitting the real engine. httpx may wrap the guard's RuntimeError in its own
    # error type, so accept either — the point is that it fails fast.
    with pytest.raises((RuntimeError, httpx.HTTPError)):
        httpx.get("https://api.example.com/v1/health", timeout=1.0)
