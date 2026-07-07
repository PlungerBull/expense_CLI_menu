"""Phase-1 currency whitelist — client mirror of the engine's schema lock.

Provenance: expense_world_engine/sql/015_lock_currencies_to_pen_usd.sql —
``CHECK (code IN ('USD','PEN'))`` on ``global_currencies``, which every
currency-typed column FKs into. Adding a currency engine-side requires an
explicit migration dropping that constraint; update this tuple in the same
change (backlog 2.4).

Tuple order is meaningful: it drives the account-form currency picker.
"""

SUPPORTED_CURRENCIES: tuple[str, ...] = ("PEN", "USD")
