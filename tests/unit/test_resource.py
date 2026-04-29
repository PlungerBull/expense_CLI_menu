"""Direct unit tests for the shared command helpers in expense/commands/_resource.py.

Covers: build_update_payload, require_yes, render_totals,
render_pagination_hint, run_toggle (including the hints= path added in
the audit refactor).
"""

from uuid import uuid4

import httpx
import pytest
import respx
import typer
from typer.testing import CliRunner

from expense import config as config_module
from expense.commands._resource import (
    build_update_payload,
    render_pagination_hint,
    render_totals,
    require_yes,
    run_toggle,
)
from expense.errors import EngineError, handle_errors

runner = CliRunner()


@pytest.fixture
def configured(tmp_path, monkeypatch):
    config_path = tmp_path / ".expense-config"
    monkeypatch.setenv("EXPENSE_CONFIG", str(config_path))
    config_module.save(
        config_module.Config(
            engine_url="https://api.example.com",
            token="ewe_pat_test",
            client_id=uuid4(),
        )
    )
    yield


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
    assert "inflow: 800000" in out
    assert "outflow: 320000" in out
    assert "net: 480000" in out


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
