import json

import httpx
import respx
from typer.testing import CliRunner

from expense.commands.rates_cmd import app as rates_app
from expense.commands.rates_cmd import format_rate
from expense.currencies import RATE_SCALE
from tests.unit.helpers import make_cli_app

cli_app = make_cli_app(rates_app, "rates")

runner = CliRunner()


# The engine sends `rate_e8: int` — the rate x RATE_SCALE (engine sql/036).
# 92340000 is 0.9234, which is what the human-mode renderer must still print.
RATE_RESPONSE = {
    "base": "USD",
    "target": "EUR",
    "date": "2026-05-03",
    "rate_e8": 92340000,
}


@respx.mock
def test_get_happy_default_base_and_date(configured):
    route = respx.get("https://api.example.com/v1/exchange-rates").mock(
        return_value=httpx.Response(200, json=RATE_RESPONSE)
    )
    result = runner.invoke(cli_app, ["rates", "get", "--target", "EUR"])
    assert result.exit_code == 0, result.output
    assert "EUR" in result.output
    assert "0.9234" in result.output

    request = route.calls.last.request
    assert request.url.params.get("target") == "EUR"
    # base and date omitted client-side so engine defaults apply
    assert request.url.params.get("base") is None
    assert request.url.params.get("date") is None


@respx.mock
def test_get_explicit_base_and_date(configured):
    route = respx.get("https://api.example.com/v1/exchange-rates").mock(
        return_value=httpx.Response(
            200,
            json={**RATE_RESPONSE, "base": "GBP", "date": "2026-04-01"},
        )
    )
    result = runner.invoke(
        cli_app,
        [
            "rates",
            "get",
            "--target",
            "EUR",
            "--base",
            "GBP",
            "--date",
            "2026-04-01",
        ],
    )
    assert result.exit_code == 0, result.output

    request = route.calls.last.request
    assert request.url.params.get("target") == "EUR"
    assert request.url.params.get("base") == "GBP"
    assert request.url.params.get("date") == "2026-04-01"


@respx.mock
def test_get_json_mode_passthrough(configured):
    respx.get("https://api.example.com/v1/exchange-rates").mock(
        return_value=httpx.Response(200, json=RATE_RESPONSE)
    )
    result = runner.invoke(cli_app, ["rates", "get", "--target", "EUR", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == RATE_RESPONSE


@respx.mock
def test_get_unsupported_currency_surfaces_engine_error(configured):
    """An unsupported code is a 422 field error, not a missing-rate error.

    Re-pinned 2026-08-16 (backlog 5.1) against the live engine: the old fixture
    invented a `RATE_UNAVAILABLE` 422 whose `fields.exchange_rate` told the user to
    "supply an explicit exchange_rate" — a flag purged in Phase 1.1 and an error
    code the engine cannot emit. Per the 2026-08-07 entry, a bad currency code is
    now field-scoped `VALIDATION_ERROR` on `base`/`target`.
    """
    respx.get("https://api.example.com/v1/exchange-rates").mock(
        return_value=httpx.Response(
            422,
            json={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid currency code.",
                    "fields": {"target": "'EUR' is not a valid currency code."},
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["rates", "get", "--target", "EUR"])
    assert result.exit_code == 1
    assert "VALIDATION_ERROR" in result.output
    assert "target" in result.output


@respx.mock
def test_get_no_rate_for_date_surfaces_not_found(configured):
    """404 now means exactly one thing: supported pair, no rate row on/before the date.

    Verified against the live engine 2026-08-16 — `fields` is null, so the renderer
    must survive a `fields: null` envelope, not just a missing key.
    """
    respx.get("https://api.example.com/v1/exchange-rates").mock(
        return_value=httpx.Response(
            404,
            json={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "exchange rate for USD->PEN not found.",
                    "fields": None,
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["rates", "get", "--target", "PEN", "--date", "2020-01-01"])
    assert result.exit_code == 1
    assert "NOT_FOUND" in result.output


def test_get_target_required(configured):
    """Without --target, Typer should bail before any HTTP call."""
    result = runner.invoke(cli_app, ["rates", "get"])
    assert result.exit_code != 0
    assert "target" in result.output.lower()


HISTORY_RESPONSE = {
    "items": [
        {"base": "USD", "target": "PEN", "rate_date": "2026-07-05", "rate_e8": 360000000},
        {"base": "EUR", "target": "PEN", "rate_date": "2026-07-05", "rate_e8": 460000000},
        {"base": "USD", "target": "PEN", "rate_date": "2026-07-04", "rate_e8": 359000000},
    ],
    "total": 3,
    "limit": 50,
    "offset": 0,
}


@respx.mock
def test_list_renders_table_newest_first(configured):
    route = respx.get("https://api.example.com/v1/exchange-rates/history").mock(
        return_value=httpx.Response(200, json=HISTORY_RESPONSE)
    )
    result = runner.invoke(cli_app, ["rates", "list"])
    assert result.exit_code == 0, result.output
    assert "3.6000" in result.output and "4.6000" in result.output  # 4-decimal display
    assert "showing 3 of 3" in result.output
    # bare human list → the 20-row default limit (2026-07-11); nothing else sent
    request = route.calls.last.request
    assert request.url.params.get("date") is None
    assert request.url.params.get("limit") == "20"
    assert request.url.params.get("offset") is None


@respx.mock
def test_list_passes_date_and_pagination(configured):
    route = respx.get("https://api.example.com/v1/exchange-rates/history").mock(
        return_value=httpx.Response(200, json={**HISTORY_RESPONSE, "items": [], "total": 0})
    )
    result = runner.invoke(
        cli_app, ["rates", "list", "--date", "2026-07-04", "--limit", "10", "--offset", "5"]
    )
    assert result.exit_code == 0, result.output
    assert "No rates stored for 2026-07-04." in result.output
    request = route.calls.last.request
    assert request.url.params.get("date") == "2026-07-04"
    assert request.url.params.get("limit") == "10"
    assert request.url.params.get("offset") == "5"


@respx.mock
def test_list_json_mode_passthrough(configured):
    respx.get("https://api.example.com/v1/exchange-rates/history").mock(
        return_value=httpx.Response(200, json=HISTORY_RESPONSE)
    )
    result = runner.invoke(cli_app, ["rates", "list", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == HISTORY_RESPONSE


# --- format_rate ----------------------------------------------------------
# The engine's wire field became `rate_e8: int` (engine sql/036); it was
# `rate: float`, the last float on the money path. These pin that the CLI side
# closed with it — the display contract is unchanged, and nothing here divides.


def test_format_rate_renders_four_decimals_from_the_scaled_integer():
    assert format_rate(360000000) == "3.6000"
    assert format_rate(335187273) == "3.3519"  # rounds up at the 5th place
    assert format_rate(29834068) == "0.2983"  # the PEN->USD inversion
    assert format_rate(RATE_SCALE) == "1.0000"


def test_format_rate_rounds_half_up_on_integers():
    """Half-up, matching every other rounding decision on the money path.

    Python's round() is banker's rounding and would send the first of these to
    3.3752 — the same class of one-off the engine hit as bug 1.7-round.
    """
    assert format_rate(337515000) == "3.3752"  # exact .5 in the 5th place
    assert format_rate(337525000) == "3.3753"


def test_format_rate_does_no_float_arithmetic():
    """A float on the wire means the engine regressed — show it, do not format it.

    Silently formatting would hide exactly the wire-format drift this field
    change was meant to make visible.
    """
    assert format_rate(3.6) == "3.6"
    assert format_rate(None) == "—"
    assert format_rate(True) == "True"
    assert format_rate("3.6") == "3.6"


def test_format_rate_never_loses_the_low_digits_to_binary():
    """The property the integer path buys: exactness at any magnitude.

    A rate whose scaled form exceeds 2**53 cannot round-trip through a float,
    so this asserts the arithmetic really is integer end to end.
    """
    big = 9_007_199_254_740_993 * (RATE_SCALE // 100_000_000)  # 2**53 + 1
    assert format_rate(big) == "90071992.5474"
