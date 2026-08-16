"""Contract smoke: hits a real engine's /health endpoint. Gated in conftest.py."""

import httpx

from tests.contract.conftest import ENGINE_URL


def test_health_live():
    """Engine /health returns 200 with {'status': 'ok'}."""
    # Timeout needs a positional default (httpx requires default-or-all-four).
    # The generous read timeout is a leftover of the Render cold start; harmless
    # against loopback, and cheap insurance if the engine is starting up.
    with httpx.Client(timeout=httpx.Timeout(10.0, read=60.0)) as client:
        response = client.get(f"{ENGINE_URL}/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
