"""Contract smoke: hits the real engine's /health endpoint. Gated on PYTEST_LIVE=1."""

import os

import httpx
import pytest

ENGINE_URL = os.environ.get("EXPENSE_ENGINE_URL", "https://expense-world-engine.onrender.com")

pytestmark = pytest.mark.skipif(
    os.environ.get("PYTEST_LIVE") != "1",
    reason="Contract tests require PYTEST_LIVE=1",
)


def test_health_live():
    """Engine /health returns 200 with {'status': 'ok'}. Cold-start tolerated."""
    # Timeout needs a positional default (httpx requires default-or-all-four);
    # 60s read tolerates a Render cold start.
    with httpx.Client(timeout=httpx.Timeout(10.0, read=60.0)) as client:
        response = client.get(f"{ENGINE_URL}/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
