import json
import re

import httpx
import respx
from typer.testing import CliRunner

from expense.commands.reports_cmd import app as reports_app
from tests.unit.helpers import make_cli_app

cli_app = make_cli_app(reports_app, "reports")

runner = CliRunner()


_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[mGKH]")


def _strip_panel(output: str) -> str:
    """Typer wraps long error messages across box-drawn panel lines.

    Strip ANSI color codes (which CI emits but local doesn't), box-drawing
    characters, and collapse line breaks so substring asserts work regardless
    of terminal width or color support. Spaces inside the message are preserved.
    """
    no_ansi = _ANSI_ESCAPE_RE.sub("", output)
    no_box = "".join(c for c in no_ansi if c not in "│╭╮╰╯─\n\t")
    return " ".join(no_box.split())


# Aggregates are home-currency ONLY since the engine's 2026-08-05 read-time
# currency change: `spent_cents` and the native month totals were deleted, and
# every survivor is nullable with an `unconverted_count` beside it.
SINGLE_MONTH_RESPONSE = {
    "month": {"year": 2026, "month": 3},
    "categories": [
        {
            "id": "cat-food",
            "name": "Food",
            "spent_home_cents": -50000,
            "unconverted_count": 0,
            "hashtag_breakdown": [
                {
                    "hashtag_ids": ["aaaa"],
                    "spent_home_cents": -30000,
                    "unconverted_count": 0,
                },
                {
                    "hashtag_ids": [],
                    "spent_home_cents": -20000,
                    "unconverted_count": 0,
                },
            ],
        }
    ],
    "totals": {
        "inflow_home_cents": 800000,
        "outflow_home_cents": 50000,
        "net_home_cents": 750000,
        "unconverted_count": 0,
    },
}


def _cat(cat_id, name, home_cents, unconverted=0):
    return {
        "id": cat_id,
        "name": name,
        "spent_home_cents": home_cents,
        "unconverted_count": unconverted,
        "hashtag_breakdown": [],
    }


def _month(year, month, categories, net_home_cents, unconverted=0):
    return {
        "month": {"year": year, "month": month},
        "categories": categories,
        "totals": {
            "inflow_home_cents": 0 if net_home_cents is not None else None,
            "outflow_home_cents": 0 if net_home_cents is not None else None,
            "net_home_cents": net_home_cents,
            "unconverted_count": unconverted,
        },
    }


RANGE_RESPONSE = {
    "months": [
        _month(
            2025, 11, [_cat("cat-food", "Food", -10000), _cat("cat-rent", "Rent", -200000)], -210000
        ),
        _month(
            2025, 12, [_cat("cat-food", "Food", -15000), _cat("cat-rent", "Rent", -200000)], -115000
        ),
    ]
}

#: The three grid states side by side. `Gifts` has nothing in any month and must
#: vanish; Food's December is a real zero (no activity → `—`) while its January
#: is unpriceable (→ `3 unrated`). Conflating those two was the Phase 4 bug.
RANGE_THREE_STATES = {
    "months": [
        _month(
            2025,
            11,
            [
                _cat("cat-food", "Food", -10000),
                _cat("cat-gifts", "Gifts", 0),
                _cat("cat-rent", "Rent", -200000),
            ],
            -210000,
        ),
        _month(
            2025,
            12,
            [
                _cat("cat-food", "Food", 0),
                _cat("cat-gifts", "Gifts", 0),
                _cat("cat-rent", "Rent", -200000),
            ],
            -200000,
        ),
        _month(
            2026,
            1,
            [
                _cat("cat-food", "Food", None, 3),
                _cat("cat-gifts", "Gifts", 0),
                _cat("cat-rent", "Rent", 0),
            ],
            None,
            3,
        ),
    ]
}


@respx.mock
def test_monthly_single_resolves_hashtag_names_live(configured):
    """The breakdown's hashtag UUIDs resolve against a live GET /v1/hashtags."""
    hashtags_route = respx.get("https://api.example.com/v1/hashtags").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [{"id": "aaaa", "name": "Groceries"}],
                "total": 1,
                "limit": 200,
                "offset": 0,
            },
        )
    )
    respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(200, json=SINGLE_MONTH_RESPONSE)
    )
    result = runner.invoke(cli_app, ["reports", "monthly", "--date", "2026-03"])
    assert result.exit_code == 0, result.output
    assert hashtags_route.called
    assert "Groceries" in result.output


@respx.mock
def test_monthly_single_unresolvable_hashtag_falls_back_to_the_id(configured):
    """No reference list reachable → the renderer degrades to the raw id, never fails."""
    respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(200, json=SINGLE_MONTH_RESPONSE)
    )
    result = runner.invoke(cli_app, ["reports", "monthly", "--date", "2026-03"])
    assert result.exit_code == 0, result.output
    assert "aaaa" in result.output


@respx.mock
def test_monthly_single_happy(configured):
    route = respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(200, json=SINGLE_MONTH_RESPONSE)
    )
    result = runner.invoke(cli_app, ["reports", "monthly", "--date", "2026-03"])
    assert result.exit_code == 0, result.output
    assert "Month: 2026-03" in result.output
    assert "Food" in result.output
    # New table layout: hashtag sub-rows are indented in the Name column with
    # spent/home as right-aligned cells (no `label: amount` colon syntax).
    assert "aaaa" in result.output
    assert "-300.00" in result.output
    assert "(no hashtags)" in result.output
    assert "-200.00" in result.output
    assert "net: 7,500.00" in result.output

    request = route.calls.last.request
    assert request.url.params.get("year") == "2026"
    assert request.url.params.get("month") == "3"
    assert "from_year" not in request.url.params


@respx.mock
def test_monthly_range_keeps_no_activity_and_unpriceable_apart(configured):
    """The Phase 4 fix: `—` and `3 unrated` must not be the same cell."""
    respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(200, json=RANGE_THREE_STATES)
    )
    result = runner.invoke(cli_app, ["reports", "monthly", "--from", "2025-11", "--to", "2026-01"])
    assert result.exit_code == 0, result.output

    lines = {ln.split()[0]: ln for ln in result.output.splitlines() if ln.strip()}
    # Food: a figure, then a no-activity month, then an unpriceable one.
    assert "-100.00" in lines["Food"]
    assert "—" in lines["Food"]
    assert "3 unrated" in lines["Food"]
    # The unpriceable month propagates to the totals row.
    assert "3 unrated" in lines["Totals"]
    # A category with nothing in any month of the window is not drawn at all.
    assert "Gifts" not in result.output
    # ...but Rent, which is empty only in January, keeps its row and its dash.
    assert "-2,000.00" in lines["Rent"]
    assert "—" in lines["Rent"]
    # Never a zero and never a bare null standing in for a refused total.
    assert "(null)" not in result.output


@respx.mock
def test_monthly_range_json_keeps_the_rows_the_table_hides(configured):
    """--json is the raw engine body — hiding is a rendering choice, not a filter."""
    respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(200, json=RANGE_THREE_STATES)
    )
    result = runner.invoke(
        cli_app, ["reports", "monthly", "--from", "2025-11", "--to", "2026-01", "--json"]
    )
    assert result.exit_code == 0
    assert json.loads(result.output) == RANGE_THREE_STATES
    assert "Gifts" in result.output


@respx.mock
def test_monthly_single_json_passthrough(configured):
    respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(200, json=SINGLE_MONTH_RESPONSE)
    )
    result = runner.invoke(cli_app, ["reports", "monthly", "--date", "2026-03", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == SINGLE_MONTH_RESPONSE


@respx.mock
def test_monthly_range_happy(configured):
    route = respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(200, json=RANGE_RESPONSE)
    )
    result = runner.invoke(cli_app, ["reports", "monthly", "--from", "2025-11", "--to", "2025-12"])
    assert result.exit_code == 0, result.output
    assert "2025-11" in result.output
    assert "2025-12" in result.output
    assert "Food" in result.output
    assert "Rent" in result.output
    assert "Totals (net)" in result.output
    assert "-2,100.00" in result.output
    assert "-1,150.00" in result.output
    # inflow/outflow joined the range table with the Overview merge (2026-08-29):
    # they were already in this payload, and the screen that used to draw them
    # (Outstanding Amounts) no longer exists.
    assert "inflow" in result.output
    assert "outflow" in result.output

    request = route.calls.last.request
    assert request.url.params.get("from_year") == "2025"
    assert request.url.params.get("from_month") == "11"
    assert request.url.params.get("to_year") == "2025"
    assert request.url.params.get("to_month") == "12"
    assert "year" not in request.url.params


@respx.mock
def test_monthly_range_draws_inflow_and_outflow_from_the_same_payload(configured):
    """The three totals rows come from `month["totals"]`, no second call.

    Guards the sign convention the merge inherited: the engine returns inflow
    AND outflow **positive** (outflow is not a negative number), so `9,000.00`
    is the outflow of a month whose net is `-1,000.00`. A renderer that assumed
    outflow was signed would print `-9,000.00` here and the row would stop
    reconciling with net.
    """
    body = {
        "months": [
            {
                "month": {"year": 2025, "month": 11},
                "categories": [_cat("cat-rent", "Rent", -100000)],
                "totals": {
                    "inflow_home_cents": 800000,
                    "outflow_home_cents": 900000,
                    "net_home_cents": -100000,
                    "unconverted_count": 0,
                },
            }
        ]
    }
    respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(200, json=body)
    )
    result = runner.invoke(cli_app, ["reports", "monthly", "--from", "2025-11", "--to", "2025-11"])
    assert result.exit_code == 0, result.output
    assert "8,000.00" in result.output
    assert "9,000.00" in result.output
    assert "-9,000.00" not in result.output
    assert "-1,000.00" in result.output


@respx.mock
def test_monthly_range_json_passthrough(configured):
    respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(200, json=RANGE_RESPONSE)
    )
    result = runner.invoke(
        cli_app, ["reports", "monthly", "--from", "2025-11", "--to", "2025-12", "--json"]
    )
    assert result.exit_code == 0
    assert json.loads(result.output) == RANGE_RESPONSE


@respx.mock
def test_monthly_no_args_errors_before_http(configured):
    route = respx.get("https://api.example.com/v1/reports/monthly")
    result = runner.invoke(cli_app, ["reports", "monthly"])
    assert result.exit_code != 0
    assert "Pass either --date" in _strip_panel(result.output)
    assert route.call_count == 0


@respx.mock
def test_monthly_both_forms_errors_before_http(configured):
    route = respx.get("https://api.example.com/v1/reports/monthly")
    result = runner.invoke(
        cli_app, ["reports", "monthly", "--date", "2026-03", "--from", "2025-11"]
    )
    assert result.exit_code != 0
    assert "mutually exclusive" in _strip_panel(result.output)
    assert route.call_count == 0


@respx.mock
def test_monthly_partial_range_errors_before_http(configured):
    route = respx.get("https://api.example.com/v1/reports/monthly")
    result = runner.invoke(cli_app, ["reports", "monthly", "--from", "2025-11"])
    assert result.exit_code != 0
    assert "must be passed together" in _strip_panel(result.output)
    assert route.call_count == 0


@respx.mock
def test_monthly_range_too_wide_sent_to_engine_422_surfaces(configured):
    route = respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(
            422,
            json={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Range span exceeds 24 months.",
                    "fields": {"to_month": "Range span exceeds 24 months."},
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["reports", "monthly", "--from", "2024-01", "--to", "2026-04"])
    assert result.exit_code == 1
    assert route.call_count == 1
    assert "VALIDATION_ERROR" in result.output
    assert "24 months" in result.output


@respx.mock
def test_monthly_range_inverted_sent_to_engine_422_surfaces(configured):
    route = respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(
            422,
            json={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Range start must be on or before range end.",
                    "fields": None,
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["reports", "monthly", "--from", "2026-04", "--to", "2025-11"])
    assert result.exit_code == 1
    assert route.call_count == 1
    assert "VALIDATION_ERROR" in result.output

    request = route.calls.last.request
    assert request.url.params.get("from_year") == "2026"
    assert request.url.params.get("from_month") == "4"
    assert request.url.params.get("to_year") == "2025"
    assert request.url.params.get("to_month") == "11"


@respx.mock
def test_monthly_out_of_range_month_sent_to_engine_422_surfaces(configured):
    route = respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(
            422,
            json={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid month payload.",
                    "fields": {"month": "Must be between 1 and 12."},
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["reports", "monthly", "--date", "2026-13"])
    assert result.exit_code == 1
    assert route.call_count == 1
    assert "VALIDATION_ERROR" in result.output
    assert "month" in result.output

    request = route.calls.last.request
    assert request.url.params.get("year") == "2026"
    assert request.url.params.get("month") == "13"


@respx.mock
def test_monthly_invalid_date_shape_errors_before_http(configured):
    route = respx.get("https://api.example.com/v1/reports/monthly")
    result = runner.invoke(cli_app, ["reports", "monthly", "--date", "2026-3"])
    assert result.exit_code != 0
    assert "YYYY-MM" in _strip_panel(result.output)
    assert route.call_count == 0


@respx.mock
def test_monthly_engine_422_surfaces_validation_error(configured):
    respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(
            422,
            json={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid month payload.",
                    "fields": {"year": "Must be between 2000 and 2100."},
                }
            },
        )
    )
    result = runner.invoke(cli_app, ["reports", "monthly", "--date", "2026-04"])
    assert result.exit_code == 1
    assert "VALIDATION_ERROR" in result.output
    assert "year" in result.output


@respx.mock
def test_monthly_engine_500(configured):
    respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(
            500,
            json={"error": {"code": "INTERNAL", "message": "boom", "fields": None}},
        )
    )
    result = runner.invoke(cli_app, ["reports", "monthly", "--date", "2026-04"])
    assert result.exit_code == 1
    assert "INTERNAL" in result.output


@respx.mock
def test_monthly_connection_error(configured):
    respx.get("https://api.example.com/v1/reports/monthly").mock(
        side_effect=httpx.ConnectError("refused")
    )
    result = runner.invoke(cli_app, ["reports", "monthly", "--date", "2026-04"])
    assert result.exit_code == 6
    assert "could not reach engine" in result.output
