"""Direct unit tests for the shared command helpers in expense/commands/_resource.py.

Covers: build_update_payload, require_yes, render_totals,
render_pagination_hint, run_toggle (including the hints= path added in
the audit refactor).
"""

import httpx
import pytest
import respx
import typer
from typer.testing import CliRunner

from expense.commands._resource import (
    build_update_payload,
    fetch_body,
    format_bool,
    format_cents,
    format_field_value,
    format_hashtag_cell,
    format_month,
    items_of,
    redact_token,
    render_pagination_hint,
    render_record,
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


def test_format_field_value_formats_only_cents_keys():
    # *_cents keys → grouped major units.
    assert format_field_value("amount_cents", -150000) == "-1,500.00"
    assert format_field_value("current_balance_cents", 5000) == "50.00"
    assert format_field_value("amount_cents", None) == "(null)"
    # Non-money fields pass through literally (incl. decimal rates, ids, ints).
    assert format_field_value("exchange_rate", 1.0) == "1.0"
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
def test_fetch_body_no_cache_hits_engine_and_skips_cache_read(configured):
    from expense import config as config_module

    respx.get("https://api.example.com/v1/things", params={"limit": "5"}).mock(
        return_value=httpx.Response(200, json={"items": [{"id": "a"}], "total": 1})
    )
    cache_reads = []
    body = fetch_body(
        config_module.ensure_loaded(),
        path="/things",
        params={"limit": 5},
        cache_read=lambda: cache_reads.append(1),
        no_cache=True,
        verbose=False,
    )
    assert body == {"items": [{"id": "a"}], "total": 1}
    assert cache_reads == []


def test_fetch_body_cached_warms_replica_then_reads_cache(configured, monkeypatch):
    from expense import config as config_module

    synced = []
    monkeypatch.setattr(
        "expense.commands._resource.ensure_synced",
        lambda client, cfg, notice_stream=None: synced.append(1),
    )
    body = fetch_body(
        config_module.ensure_loaded(),
        path="/things",
        params={"limit": 5},
        cache_read=lambda: {"items": [], "total": 0},
        no_cache=False,
        verbose=False,
    )
    assert body == {"items": [], "total": 0}
    assert synced == [1]  # replica warmed exactly once, no engine GET issued


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
            "inflow_cents": 800000,
            "inflow_home_cents": 800000,
            "outflow_cents": 320000,
            "outflow_home_cents": 320000,
            "net_cents": 480000,
            "net_home_cents": 480000,
        }
    )
    out = capsys.readouterr().out
    assert "Totals:" in out
    assert "inflow: 8,000.00" in out
    assert "outflow: 3,200.00" in out
    assert "net: 4,800.00" in out


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
