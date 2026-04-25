from datetime import datetime

import pytest
import typer

from expense.dates import to_canonical_aware


@pytest.fixture(autouse=True)
def pin_local_tz(monkeypatch):
    """Pin the local timezone so output strings are deterministic across machines."""
    monkeypatch.setattr("tzlocal.get_localzone_name", lambda: "America/New_York")


def test_aware_utc_passthrough():
    assert to_canonical_aware("2026-04-25T16:30:00Z") == "2026-04-25T16:30:00Z"


def test_aware_offset_passthrough():
    assert to_canonical_aware("2026-04-25T16:30:00-05:00") == "2026-04-25T16:30:00-05:00"


def test_aware_plus_offset_passthrough():
    assert to_canonical_aware("2026-04-25T16:30:00+02:00") == "2026-04-25T16:30:00+02:00"


def test_naive_datetime_t_separator_attaches_local_tz():
    result = to_canonical_aware("2026-04-25T16:30:00")
    parsed = datetime.fromisoformat(result)
    assert parsed.tzinfo is not None
    assert parsed.year == 2026 and parsed.month == 4 and parsed.day == 25
    assert parsed.hour == 16 and parsed.minute == 30 and parsed.second == 0


def test_naive_datetime_space_separator_attaches_local_tz():
    result = to_canonical_aware("2026-04-25 16:30:00")
    parsed = datetime.fromisoformat(result)
    assert parsed.tzinfo is not None
    assert parsed.hour == 16 and parsed.minute == 30


def test_naive_datetime_no_seconds():
    result = to_canonical_aware("2026-04-25T16:30")
    parsed = datetime.fromisoformat(result)
    assert parsed.tzinfo is not None
    assert parsed.hour == 16 and parsed.minute == 30


def test_date_only_midnight_local():
    result = to_canonical_aware("2026-04-25")
    parsed = datetime.fromisoformat(result)
    assert parsed.tzinfo is not None
    assert parsed.year == 2026 and parsed.month == 4 and parsed.day == 25
    assert parsed.hour == 0 and parsed.minute == 0


def test_garbage_raises_bad_parameter():
    with pytest.raises(typer.BadParameter):
        to_canonical_aware("not-a-date")


def test_invalid_time_raises_bad_parameter():
    with pytest.raises(typer.BadParameter):
        to_canonical_aware("2026-04-25T25:99:00")
