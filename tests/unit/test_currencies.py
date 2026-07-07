"""Drift trap: the USD/PEN whitelist has exactly one home (backlog 2.4).

Adding a currency engine-side (sql/015_lock_currencies_to_pen_usd.sql) must
mean touching expense/currencies.py only — if any client copy drifts, this
fails.
"""

from expense.currencies import SUPPORTED_CURRENCIES
from expense.import_ import mapping
from expense.tui.screens import create_forms


def test_currency_whitelist_single_source():
    assert set(dict(create_forms._CURRENCIES)) == set(SUPPORTED_CURRENCIES)
    assert mapping.VALID_CURRENCIES == frozenset(SUPPORTED_CURRENCIES)
