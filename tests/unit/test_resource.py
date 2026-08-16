"""Direct unit tests for the shared command helpers in expense/commands/_resource.py.

Covers: build_update_payload, require_yes, render_totals,
render_pagination_hint, run_toggle (including the hints= path added in
the audit refactor), and the nullable-aggregate helpers format_aggregate /
has_aggregate.
"""

import httpx
import pytest
import respx
import typer
from typer.testing import CliRunner

from expense.commands._resource import (
    account_choices,
    build_update_payload,
    fetch_all_pages,
    fetch_body,
    format_aggregate,
    format_bool,
    format_cents,
    format_field_value,
    format_hashtag_cell,
    format_month,
    has_aggregate,
    items_of,
    load_account_name_map,
    load_category_name_map,
    load_hashtag_name_map,
    parse_hashtag_ids,
    redact_token,
    render_pagination_hint,
    render_record,
    render_table,
    render_totals,
    require_yes,
    run_toggle,
)
from expense.errors import EngineError, handle_errors

runner = CliRunner()


# ---------------------------------------------------------------------------
# build_update_payload
# ---------------------------------------------------------------------------


def test_build_update_payload_strips_none_values():
    out = build_update_payload({"a": 1, "b": None, "c": "x"})
    assert out == {"a": 1, "c": "x"}


def test_build_update_payload_keeps_falsy_non_none_values():
    out = build_update_payload({"flag": False, "count": 0, "text": ""})
    assert out == {"flag": False, "count": 0, "text": ""}


def test_build_update_payload_exits_when_all_none():
    app = typer.Typer()

    @app.command()
    def fake() -> None:
        build_update_payload({"a": None, "b": None})

    result = runner.invoke(app, [])
    assert result.exit_code == 1
    assert "No fields to update" in result.output


# ---------------------------------------------------------------------------
# require_yes
# ---------------------------------------------------------------------------


def test_require_yes_passes_through_when_yes_true():
    require_yes(True, "ignored prompt")  # no exception, returns None


def test_require_yes_exits_in_non_tty_without_yes(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    app = typer.Typer()

    @app.command()
    def fake() -> None:
        require_yes(False, "Delete?")

    result = runner.invoke(app, [])
    assert result.exit_code == 1
    assert "non-interactive" in result.output


def test_require_yes_declined_prompt_aborts(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(typer, "confirm", lambda prompt: False)

    with pytest.raises(typer.Exit) as exc:
        require_yes(False, "Delete?")

    assert exc.value.exit_code == 1
    assert "Aborted." in capsys.readouterr().out


# ---------------------------------------------------------------------------
# format_cents
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (651900, "6,519.00"),
        (-418797, "-4,187.97"),
        (-1027202, "-10,272.02"),
        (-800, "-8.00"),
        (0, "0.00"),
        (5, "0.05"),
        (-1, "-0.01"),
        (99, "0.99"),
        (None, "(null)"),
    ],
)
def test_format_cents(value, expected):
    assert format_cents(value) == expected


def test_format_cents_non_int_falls_back_to_str():
    # Booleans are an int subclass but are never amounts — keep them literal.
    assert format_cents(True) == "True"
    assert format_cents("n/a") == "n/a"


# ---------------------------------------------------------------------------
# format_aggregate / has_aggregate — the nullable home aggregates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "count", "expected"),
    [
        (-50000, 0, "-500.00"),  # a present figure formats as any amount does
        (0, 0, "0.00"),  # a real zero is a real zero
        (-50000, 3, "-500.00"),  # a figure wins over a stale count
        (None, 3, "3 unrated"),  # the engine refused to report a partial total
        (None, 1, "1 unrated"),
        (None, 0, "(null)"),  # null with no count is just missing data
        (None, None, "(null)"),
        (None, "3", "(null)"),  # a non-int count is not a count
        (None, True, "(null)"),  # bool is an int subclass but never a count
    ],
)
def test_format_aggregate(value, count, expected):
    assert format_aggregate(value, count) == expected


def test_format_aggregate_never_renders_a_null_as_zero():
    """The whole point: `null` is not `0`, and never falls back to a native figure."""
    rendered = format_aggregate(None, 3)
    assert "0.00" not in rendered
    assert rendered == "3 unrated"


@pytest.mark.parametrize(
    ("value", "count", "shown"),
    [
        (-50000, 0, True),  # spent something
        (50000, 0, True),  # earned something
        (0, 0, False),  # nothing spent — not drawn
        (None, 0, False),  # nothing to say at all
        (None, 3, True),  # unpriceable is NOT empty; it keeps its row
        (0, 2, True),  # a count always wins
        (True, 0, False),  # bool is not an amount
    ],
)
def test_has_aggregate(value, count, shown):
    assert has_aggregate(value, count) is shown


def test_format_field_value_formats_only_cents_keys():
    # *_cents keys → grouped major units.
    assert format_field_value("amount_cents", -150000) == "-1,500.00"
    assert format_field_value("current_balance_cents", 5000) == "50.00"
    assert format_field_value("amount_cents", None) == "(null)"
    # Non-money fields pass through literally (incl. decimal rates, ids, ints).
    assert format_field_value("rate", 1.0) == "1.0"
    assert format_field_value("version", 3) == "3"
    assert format_field_value("title", None) == "(null)"
    assert format_field_value("transaction_type", 1) == "1"


# ---------------------------------------------------------------------------
# render_record / format_bool / format_month
# ---------------------------------------------------------------------------


def test_render_record_human_formats_cents_keys(capsys):
    render_record({"title": "Rent", "amount_cents": -150000}, json_mode=False)
    out = capsys.readouterr().out
    assert "  title: Rent" in out
    assert "  amount_cents: -1,500.00" in out


def test_render_record_skip_hides_keys_in_human_mode(capsys):
    body = {"id": "abc", "transactions": [{"id": "t1"}]}
    render_record(body, json_mode=False, skip=("transactions",))
    out = capsys.readouterr().out
    assert "id: abc" in out
    assert "transactions" not in out


def test_render_record_json_mode_is_verbatim_and_ignores_skip(capsys):
    render_record({"id": "abc", "transactions": []}, json_mode=True, skip=("transactions",))
    out = capsys.readouterr().out
    assert '"transactions": []' in out


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, "yes"),
        (False, "no"),
        (None, "no"),
        ("2026-07-06T00:00:00Z", "yes"),  # truthy marker fields like deleted_at
        (0, "no"),
    ],
)
def test_format_bool(value, expected):
    assert format_bool(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"year": 2026, "month": 7}, "2026-07"),
        ({"year": 2026, "month": 12}, "2026-12"),
        ({"year": 2026}, "(unknown)"),
        ({"year": "2026", "month": "7"}, "(unknown)"),
        (None, "(unknown)"),
    ],
)
def test_format_month(value, expected):
    assert format_month(value) == expected


# ---------------------------------------------------------------------------
# fetch_body
# ---------------------------------------------------------------------------


@respx.mock
def test_fetch_body_issues_one_live_get(configured):
    from expense import config as config_module

    route = respx.get("https://api.example.com/v1/things", params={"limit": "5"}).mock(
        return_value=httpx.Response(200, json={"items": [{"id": "a"}], "total": 1})
    )
    body = fetch_body(
        config_module.ensure_loaded(),
        path="/things",
        params={"limit": 5},
        verbose=False,
    )
    assert body == {"items": [{"id": "a"}], "total": 1}
    assert route.call_count == 1


@respx.mock
def test_fetch_body_include_deleted_is_just_a_query_param(configured):
    """No special routing left — every read is live, so --include-deleted is a param."""
    from expense import config as config_module

    route = respx.get("https://api.example.com/v1/things", params={"include_deleted": "true"}).mock(
        return_value=httpx.Response(200, json={"items": [{"id": "a"}], "total": 1})
    )
    body = fetch_body(
        config_module.ensure_loaded(),
        path="/things",
        params={"include_deleted": "true"},
        verbose=False,
    )
    assert body == {"items": [{"id": "a"}], "total": 1}
    assert route.call_count == 1


@respx.mock
def test_fetch_body_empty_params_sends_no_query(configured):
    from expense import config as config_module

    route = respx.get("https://api.example.com/v1/things").mock(
        return_value=httpx.Response(200, json={"items": [], "total": 0})
    )
    fetch_body(config_module.ensure_loaded(), path="/things", params={}, verbose=False)
    assert route.calls.last.request.url.query == b""


# ---------------------------------------------------------------------------
# load_*_name_map — live reference lookups, `{}` on any failure
# ---------------------------------------------------------------------------


def _list_body(items: list[dict], total: int | None = None) -> httpx.Response:
    body = {
        "items": items,
        "total": len(items) if total is None else total,
        "limit": 200,
        "offset": 0,
    }
    return httpx.Response(200, json=body)


@respx.mock
def test_load_account_name_map_fetches_live_with_archived_and_people(configured):
    route = respx.get("https://api.example.com/v1/accounts").mock(
        return_value=_list_body([{"id": "a1", "name": "BCP"}, {"id": "p1", "name": "Mom"}])
    )
    assert load_account_name_map() == {"a1": "BCP", "p1": "Mom"}

    params = route.calls.last.request.url.params
    assert params["include_archived"] == "true"
    assert params["include_people"] == "true"
    assert params["limit"] == "200"
    assert params["offset"] == "0"


@respx.mock
def test_load_category_name_map_fetches_live(configured):
    route = respx.get("https://api.example.com/v1/categories").mock(
        return_value=_list_body([{"id": "c1", "name": "Food"}])
    )
    assert load_category_name_map() == {"c1": "Food"}
    assert "include_archived" not in route.calls.last.request.url.params


@respx.mock
def test_load_hashtag_name_map_fetches_live(configured):
    route = respx.get("https://api.example.com/v1/hashtags").mock(
        return_value=_list_body([{"id": "h1", "name": "trabajo"}])
    )
    assert load_hashtag_name_map() == {"h1": "trabajo"}
    assert "include_archived" not in route.calls.last.request.url.params


@respx.mock
def test_load_name_map_pages_through_every_row(configured):
    first = [{"id": f"c{i}", "name": f"n{i}"} for i in range(200)]
    second = [{"id": "c200", "name": "n200"}]
    route = respx.get("https://api.example.com/v1/categories").mock(
        side_effect=[_list_body(first, total=201), _list_body(second, total=201)]
    )
    out = load_category_name_map()
    assert len(out) == 201
    assert route.call_count == 2
    assert route.calls[1].request.url.params["offset"] == "200"


@respx.mock
def test_load_name_map_skips_rows_without_a_string_id_and_name(configured):
    respx.get("https://api.example.com/v1/categories").mock(
        return_value=_list_body([{"id": "c1", "name": "Food"}, {"id": "c2"}, {"name": "orphan"}])
    )
    assert load_category_name_map() == {"c1": "Food"}


def test_load_name_map_without_config_is_empty():
    """No config → no engine to ask; renderers degrade to short ids, never raise."""
    assert load_account_name_map() == {}
    assert load_category_name_map() == {}
    assert load_hashtag_name_map() == {}


@respx.mock
def test_load_name_map_on_engine_error_is_empty(configured):
    respx.get("https://api.example.com/v1/categories").mock(
        return_value=httpx.Response(
            401, json={"error": {"code": "UNAUTHORIZED", "message": "nope", "fields": None}}
        )
    )
    assert load_category_name_map() == {}


# ---------------------------------------------------------------------------
# redact_token / format_hashtag_cell
# ---------------------------------------------------------------------------


def test_redact_token_masks_middle():
    assert redact_token("ewe_pat_abcd1234wxyz") == "ewe_pat_****wxyz"


def test_redact_token_short_tokens_fully_masked():
    assert redact_token("short") == "****"
    assert redact_token("12345678") == "****"  # exactly 8 → still fully masked


def test_format_hashtag_cell_resolves_names():
    cell = format_hashtag_cell(["h1", "h2"], {"h1": "trabajo", "h2": "club"}, max_width=24)
    assert cell == "trabajo, club"


def test_format_hashtag_cell_unresolved_id_gets_short_id_with_ellipsis():
    cell = format_hashtag_cell(["0123456789abcdef"], {}, max_width=24)
    assert cell == "01234567…"


def test_format_hashtag_cell_truncates_to_max_width():
    cell = format_hashtag_cell(["h1", "h2"], {"h1": "a" * 20, "h2": "b" * 20}, max_width=10)
    assert len(cell) == 10
    assert cell.endswith("…")


def test_format_hashtag_cell_empty_or_non_list_is_dash():
    assert format_hashtag_cell([], {}, max_width=24) == "—"
    assert format_hashtag_cell(None, {}, max_width=24) == "—"
    assert format_hashtag_cell("h1", {}, max_width=24) == "—"


# --- parse_hashtag_ids -------------------------------------------------------
# Hoisted to _resource.py with backlog 6.1 so the four commands taking
# `--hashtag-ids` (transactions update, log, inbox add, inbox update) share one
# parse. Behaviour pinned here rather than in each command's suite.


def test_parse_hashtag_ids_splits_and_strips():
    assert parse_hashtag_ids("h-1, h-2,h-3") == ["h-1", "h-2", "h-3"]
    assert parse_hashtag_ids("  h-1  ") == ["h-1"]


def test_parse_hashtag_ids_empty_string_is_empty_list_not_none():
    """`--hashtag-ids ""` is an explicit *clear*, so it must survive as `[]`.

    `build_update_payload` drops `None` (meaning "leave alone") but keeps `[]`,
    which the engine acts on. Returning `None` here would silently turn a clear
    into a no-op.
    """
    assert parse_hashtag_ids("") == []
    assert parse_hashtag_ids(",") == []
    assert parse_hashtag_ids("  ,  ") == []


def test_parse_hashtag_ids_does_not_validate_uuids():
    """Bad ids are the engine's 422, not ours — the thin-wrapper rule."""
    assert parse_hashtag_ids("not-a-uuid,also-bad") == ["not-a-uuid", "also-bad"]


# ---------------------------------------------------------------------------
# items_of
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"items": [{"id": "a"}], "total": 1}, [{"id": "a"}]),  # paginated dict
        ({"items": []}, []),
        ({"items": None}, []),  # items present but null
        ({"total": 3}, []),  # dict without items — never a row source
        ([{"id": "a"}], [{"id": "a"}]),  # flat list (e.g. accounts live path)
        ([], []),
        (None, []),
        ("oops", []),  # scalar garbage
    ],
)
def test_items_of(body, expected):
    assert items_of(body) == expected


# ---------------------------------------------------------------------------
# render_totals
# ---------------------------------------------------------------------------


def test_render_totals_human_renders_inflow_outflow_net(capsys):
    render_totals(
        {
            "inflow_home_cents": 800000,
            "outflow_home_cents": 320000,
            "net_home_cents": 480000,
            "unconverted_count": 0,
        }
    )
    out = capsys.readouterr().out
    assert "Totals:" in out
    assert "inflow: 8,000.00" in out
    assert "outflow: 3,200.00" in out
    assert "net: 4,800.00" in out
    # One figure per line since 2026-08-05 — the native aggregates are deleted,
    # so there is nothing left to put in the old `(home: ...)` parenthetical.
    assert "(home:" not in out


def test_render_totals_unconvertible_collapses_to_one_line(capsys):
    """The three figures share one count, so they fail together, not three times."""
    render_totals(
        {
            "inflow_home_cents": None,
            "outflow_home_cents": None,
            "net_home_cents": None,
            "unconverted_count": 3,
        }
    )
    out = capsys.readouterr().out
    assert "3 unrated — no totals this month" in out
    assert "inflow:" not in out
    # Never zero, never "(null)" — the engine refused to report a partial total.
    assert "0.00" not in out
    assert "(null)" not in out


def test_render_totals_handles_none(capsys):
    render_totals(None)
    out = capsys.readouterr().out
    assert "(no totals)" in out


def test_render_totals_handles_missing_keys(capsys):
    render_totals({})
    out = capsys.readouterr().out
    assert "inflow: (null)" in out


# ---------------------------------------------------------------------------
# render_pagination_hint
# ---------------------------------------------------------------------------


def test_render_pagination_hint_surfaces_when_more_to_fetch(capsys):
    render_pagination_hint({"total": 10, "limit": 5, "offset": 0}, [{}, {}, {}, {}, {}])
    out = capsys.readouterr().out
    assert "showing 5 of 10" in out
    assert "--offset 5 --limit 5" in out


def test_render_pagination_hint_silent_when_all_visible(capsys):
    render_pagination_hint({"total": 5, "limit": 5, "offset": 0}, [{}, {}, {}, {}, {}])
    assert capsys.readouterr().out == ""


def test_render_pagination_hint_silent_for_bare_array(capsys):
    render_pagination_hint([{}, {}], [{}, {}])
    assert capsys.readouterr().out == ""


def test_render_pagination_hint_silent_when_metadata_missing(capsys):
    render_pagination_hint({"items": []}, [])
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# run_toggle (including hints= path)
# ---------------------------------------------------------------------------


def _build_toggle_app() -> typer.Typer:
    """Build a fresh Typer app that exposes a no-arg toggle command for testing."""
    app = typer.Typer()

    @app.callback()
    def _root() -> None:
        pass

    @app.command("test-toggle")
    @handle_errors
    def test_toggle(
        ctx: typer.Context,
        id_: str = typer.Argument(..., metavar="ID"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        run_toggle(
            ctx,
            resource="things",
            id_=id_,
            verb="archive",
            json_output=json_output,
            render_human=lambda body: typer.echo(f"archived: {body.get('id')}"),
            hints={
                403: "Hint: this thing is system-protected.",
                409: "Hint: another thing has the same name.",
            },
        )

    return app


@respx.mock
def test_run_toggle_happy_posts_correct_url(configured):
    route = respx.post("https://api.example.com/v1/things/abc/archive").mock(
        return_value=httpx.Response(200, json={"id": "abc"})
    )
    result = runner.invoke(_build_toggle_app(), ["test-toggle", "abc"])
    assert result.exit_code == 0, result.output
    assert "archived: abc" in result.output
    assert "X-Idempotency-Key" in route.calls.last.request.headers


@respx.mock
def test_run_toggle_surfaces_403_hint(configured):
    respx.post("https://api.example.com/v1/things/abc/archive").mock(
        return_value=httpx.Response(
            403,
            json={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "Cannot archive a system thing.",
                    "fields": None,
                }
            },
        )
    )
    result = runner.invoke(_build_toggle_app(), ["test-toggle", "abc"])
    assert result.exit_code == 1
    assert "system-protected" in result.output


@respx.mock
def test_run_toggle_surfaces_409_hint(configured):
    respx.post("https://api.example.com/v1/things/abc/archive").mock(
        return_value=httpx.Response(
            409,
            json={"error": {"code": "CONFLICT", "message": "Conflict.", "fields": None}},
        )
    )
    result = runner.invoke(_build_toggle_app(), ["test-toggle", "abc"])
    assert result.exit_code == 1
    assert "same name" in result.output


@respx.mock
def test_run_toggle_no_hint_for_unmapped_status(configured):
    respx.post("https://api.example.com/v1/things/abc/archive").mock(
        return_value=httpx.Response(
            500,
            json={"error": {"code": "ERR", "message": "boom", "fields": None}},
        )
    )
    result = runner.invoke(_build_toggle_app(), ["test-toggle", "abc"])
    assert result.exit_code == 1
    assert "system-protected" not in result.output
    assert "same name" not in result.output


@respx.mock
def test_run_toggle_no_hints_kwarg_means_no_hint(configured):
    """When hints= is not passed, errors render with the standard envelope only."""
    app = typer.Typer()

    @app.callback()
    def _root() -> None:
        pass

    @app.command("plain")
    @handle_errors
    def plain(
        ctx: typer.Context,
        id_: str = typer.Argument(..., metavar="ID"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        run_toggle(
            ctx,
            resource="things",
            id_=id_,
            verb="restore",
            json_output=json_output,
            render_human=lambda body: typer.echo("ok"),
        )

    respx.post("https://api.example.com/v1/things/abc/restore").mock(
        return_value=httpx.Response(
            403,
            json={"error": {"code": "FORBIDDEN", "message": "x", "fields": None}},
        )
    )
    result = runner.invoke(app, ["plain", "abc"])
    assert result.exit_code == 1
    assert "Hint:" not in result.output


@respx.mock
def test_run_toggle_raises_engine_error_for_handle_errors_to_render(configured):
    """The engine error bubbles up so handle_errors renders the full envelope."""
    respx.post("https://api.example.com/v1/things/abc/archive").mock(
        return_value=httpx.Response(
            403,
            json={"error": {"code": "FORBIDDEN", "message": "Forbidden", "fields": None}},
        )
    )
    result = runner.invoke(_build_toggle_app(), ["test-toggle", "abc"])
    assert result.exit_code == 1
    assert "FORBIDDEN" in result.output
    assert isinstance(result.exception, SystemExit) or result.exception is None


def test_run_toggle_signature_accepts_hints_kwarg():
    """Smoke check: hints= is a keyword-only optional parameter, default None."""
    import inspect

    sig = inspect.signature(run_toggle)
    assert "hints" in sig.parameters
    assert sig.parameters["hints"].default is None


def test_engine_error_attribute_access():
    """EngineError instances expose .status, .code, .fields for hint lookups."""
    err = EngineError(code="X", message="m", fields={"a": "b"}, status=403, raw_body={})
    assert err.status == 403
    assert err.code == "X"
    assert err.fields == {"a": "b"}


# ---------------------------------------------------------------------------
# account_choices (backlog 6.4c — the one picker-tuple build)
# ---------------------------------------------------------------------------

_ACCOUNT_ROWS = [
    {"id": "a1", "name": "BCP", "currency_code": "PEN", "current_balance_cents": 100},
    {"id": "a2", "name": None, "currency_code": None, "is_person": False},
    {"id": "p1", "name": "Mom", "currency_code": "PEN", "is_person": True},
    {"name": "no-id row is skipped"},
]


def test_account_choices_includes_people_by_default():
    rows = account_choices(_ACCOUNT_ROWS)
    assert [r[0] for r in rows] == ["a1", "a2", "p1"]
    assert rows[0] == ("a1", "BCP", "PEN")
    assert rows[1] == ("a2", "(unnamed)", "?")  # null name/currency fallbacks


def test_account_choices_can_exclude_people():
    rows = account_choices(_ACCOUNT_ROWS, include_people=False)
    assert [r[0] for r in rows] == ["a1", "a2"]


def test_account_choices_with_balance_appends_cents():
    rows = account_choices(_ACCOUNT_ROWS, include_people=False, with_balance=True)
    assert rows[0] == ("a1", "BCP", "PEN", 100)
    assert rows[1][3] is None  # missing balance stays None


# ---------------------------------------------------------------------------
# fetch_all_pages (backlog 6.4a — the one pagination loop)
# ---------------------------------------------------------------------------


def _pager(pages):
    """fetch_page stub serving canned bodies; records (limit, offset) calls."""
    calls: list[tuple[int, int]] = []

    def fetch_page(limit, offset):
        calls.append((limit, offset))
        return pages[len(calls) - 1]

    return fetch_page, calls


def test_fetch_all_pages_full_then_short_page():
    full = {"items": [{"id": f"t{i}"} for i in range(200)], "total": 240}
    short = {"items": [{"id": f"t{200 + i}"} for i in range(40)], "total": 240}
    fetch_page, calls = _pager([full, short])
    rows = fetch_all_pages(fetch_page)
    assert calls == [(200, 0), (200, 200)]
    assert len(rows) == 240


def test_fetch_all_pages_flat_list_returned_whole():
    fetch_page, calls = _pager([[{"id": "a1"}, {"id": "a2"}]])
    rows = fetch_all_pages(fetch_page)
    assert calls == [(200, 0)]
    assert rows == [{"id": "a1"}, {"id": "a2"}]


def test_fetch_all_pages_empty_first_page():
    fetch_page, calls = _pager([{"items": [], "total": 0}])
    assert fetch_all_pages(fetch_page) == []
    assert calls == [(200, 0)]


def test_fetch_all_pages_total_stops_padded_pages():
    """A full page with total == collected stops without an extra request."""
    page = {"items": [{"id": f"t{i}"} for i in range(200)], "total": 200}
    fetch_page, calls = _pager([page])
    assert len(fetch_all_pages(fetch_page)) == 200
    assert calls == [(200, 0)]


def test_fetch_all_pages_no_total_stops_on_short_page():
    """Missing total falls back to the short-page rule (keeps paging first)."""
    full = {"items": [{"id": f"t{i}"} for i in range(200)]}
    short = {"items": [{"id": "t200"}]}
    fetch_page, calls = _pager([full, short])
    assert len(fetch_all_pages(fetch_page)) == 201
    assert calls == [(200, 0), (200, 200)]


def test_fetch_all_pages_custom_page_size():
    full = {"items": [{"id": "a"}, {"id": "b"}]}
    short = {"items": [{"id": "c"}]}
    fetch_page, calls = _pager([full, short])
    assert len(fetch_all_pages(fetch_page, page_size=2)) == 3
    assert calls == [(2, 0), (2, 2)]


# ---------------------------------------------------------------------------
# render_table (incl. optional footer)
# ---------------------------------------------------------------------------


def _is_rule(line: str) -> bool:
    """A separator line is only dashes and the column separators."""
    return "-" in line and set(line) <= {"-", " "}


def test_render_table_no_footer_single_rule(capsys):
    render_table(
        headers={"name": "Name", "amt": "Amt"},
        rows=[{"name": "Food", "amt": "-50.00"}],
        align_right={"amt"},
    )
    lines = capsys.readouterr().out.splitlines()
    # header, one rule, one data row — no footer, exactly one rule line
    assert len(lines) == 3
    assert [_is_rule(line) for line in lines] == [False, True, False]
    assert "Name" in lines[0] and "Amt" in lines[0]
    assert "Food" in lines[2] and "-50.00" in lines[2]


def test_render_table_footer_adds_second_rule_and_row(capsys):
    render_table(
        headers={"name": "Category", "jan": "jan"},
        rows=[{"name": "Food", "jan": "-50.00"}],
        align_right={"jan"},
        footer={"name": "Totals (net)", "jan": "-50.00"},
    )
    lines = capsys.readouterr().out.splitlines()
    # header, header-rule, data row, footer-rule, footer row
    assert len(lines) == 5
    assert [_is_rule(line) for line in lines] == [False, True, False, True, False]
    assert lines[4].startswith("Totals (net)")
    # name column widened to fit "Totals (net)" (12 cols) — the header rule's
    # first segment is that many dashes.
    assert lines[1].split()[0] == "-" * len("Totals (net)")


def test_render_table_footer_prints_when_rows_empty(capsys):
    render_table(
        headers={"name": "Category", "jan": "jan"},
        rows=[],
        align_right={"jan"},
        footer={"name": "Totals (net)", "jan": "0.00"},
    )
    lines = capsys.readouterr().out.splitlines()
    # header, header-rule, footer-rule, footer row — still renders with zero data rows
    assert len(lines) == 4
    assert [_is_rule(line) for line in lines] == [False, True, True, False]
    assert lines[-1].startswith("Totals (net)")


def test_render_table_empty_without_footer_prints_nothing(capsys):
    render_table(headers={"name": "Name"}, rows=[])
    assert capsys.readouterr().out == ""
