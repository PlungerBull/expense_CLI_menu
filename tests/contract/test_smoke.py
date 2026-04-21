import os

import pytest

LIVE = os.environ.get("PYTEST_LIVE") == "1"


@pytest.mark.skipif(not LIVE, reason="Contract tests require PYTEST_LIVE=1")
def test_placeholder_live():
    assert True
