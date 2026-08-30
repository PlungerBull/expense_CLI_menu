"""Phase-1 currency whitelist — client mirror of the engine's schema lock.

Provenance: expense_world_engine/sql/015_lock_currencies_to_pen_usd.sql —
``CHECK (code IN ('USD','PEN'))`` on ``global_currencies``, which every
currency-typed column FKs into. Adding a currency engine-side requires an
explicit migration dropping that constraint; update this tuple in the same
change (backlog 2.4).

Tuple order is meaningful: it drives the account-form currency picker.
"""

SUPPORTED_CURRENCIES: tuple[str, ...] = ("PEN", "USD")


# The minor-unit scale: how many minor units make one major unit. Consumed by
# quickadd/money.py (both directions), commands/_resource.format_cents and
# commands/import_cmd — previously four independent `100` literals with nothing
# naming the assumption they shared.
#
# ⚠️ One constant for every currency is correct ONLY because the tuple above is
# locked to {USD, PEN}, which are both exponent 2. Centralizing makes the
# assumption findable and single-edit; it does NOT make it data-driven.
# `global_currencies` deliberately has no `exponent` column (engine sql/024
# drops columns nothing varies on), so admitting a currency with a different
# exponent — JPY is 0, KWD is 3 — means introducing the concept, not editing
# this number. Every call site below would have to learn which currency it is
# formatting, which none of them currently knows.
#
# The engine has no counterpart: it stores and serves integer cents and never
# converts to major units at all. This scale is a presentation concern and lives
# entirely on this side.
MINOR_UNIT_SCALE = 100

# The scale stored exchange rates are expressed at — client mirror of the
# engine's `app.constants.RATE_SCALE` and the `rate_e8` column from engine
# sql/036. The engine's wire format is `rate_e8: int` (the rate x this), so
# commands/rates_cmd divides by it for display and never does arithmetic on the
# quotient. Same provenance rule as SUPPORTED_CURRENCIES above: if the engine
# changes the scale, this changes in the same commit.
RATE_SCALE = 100_000_000
