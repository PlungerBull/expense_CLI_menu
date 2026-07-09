import json

import pytest
import typer

from expense.errors import (
    CacheUnavailableError,
    ConfigMissingError,
    EngineConnectionError,
    EngineError,
    SyncContractError,
    format_error,
    handle_errors,
    render,
)


def test_engine_error_attributes():
    err = EngineError(
        code="VALIDATION_ERROR",
        message="Amount must not be zero",
        fields={"amount_cents": "Must not be zero"},
        status=422,
        raw_body={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "...",
                "fields": {"amount_cents": "..."},
            }
        },
    )
    assert err.code == "VALIDATION_ERROR"
    assert err.status == 422
    assert err.fields == {"amount_cents": "Must not be zero"}


def test_render_engine_error_human_with_fields():
    err = EngineError(
        code="VALIDATION_ERROR",
        message="Amount must not be zero",
        fields={"amount_cents": "Must not be zero"},
        status=422,
        raw_body={},
    )
    output, exit_code, use_stderr = render(err, json_mode=False)
    assert exit_code == 1
    assert use_stderr is True
    assert "Error: VALIDATION_ERROR — Amount must not be zero" in output
    assert "  amount_cents: Must not be zero" in output


def test_render_engine_error_human_401_surfaces_config_set_hint():
    err = EngineError(
        code="UNAUTHORIZED",
        message="Missing or invalid token",
        fields=None,
        status=401,
        raw_body={},
    )
    output, exit_code, use_stderr = render(err, json_mode=False)
    assert exit_code == 1
    assert use_stderr is True
    assert output.startswith("Error: UNAUTHORIZED — Missing or invalid token")
    assert "expense config set --token" in output
    assert "expense auth bootstrap" in output


def test_render_engine_error_human_non_401_no_hint():
    err = EngineError(
        code="NOT_FOUND",
        message="Not found",
        fields=None,
        status=404,
        raw_body={},
    )
    output, exit_code, use_stderr = render(err, json_mode=False)
    assert exit_code == 1
    assert output == "Error: NOT_FOUND — Not found"


def test_render_engine_error_json_passes_through_raw_body():
    raw = {"error": {"code": "NOT_FOUND", "message": "x", "fields": None}}
    err = EngineError(
        code="NOT_FOUND",
        message="x",
        fields=None,
        status=404,
        raw_body=raw,
    )
    output, exit_code, use_stderr = render(err, json_mode=True)
    assert exit_code == 1
    assert use_stderr is False
    assert json.loads(output) == raw


def test_render_connection_error_human_includes_url():
    err = EngineConnectionError(
        url="https://nonexistent.invalid",
        original=ConnectionRefusedError("refused"),
    )
    output, exit_code, use_stderr = render(err, json_mode=False)
    assert exit_code == 2
    assert use_stderr is True
    assert "https://nonexistent.invalid" in output
    assert "could not reach engine" in output


def test_render_connection_error_json_envelope():
    err = EngineConnectionError(
        url="https://x.invalid",
        original=TimeoutError("timeout"),
    )
    output, exit_code, _ = render(err, json_mode=True)
    assert exit_code == 2
    envelope = json.loads(output)
    assert envelope["error"]["code"] == "CONNECTION_ERROR"
    assert envelope["error"]["fields"] is None


def test_render_config_missing_human():
    err = ConfigMissingError("No config found. Run: expense config set ...")
    output, exit_code, use_stderr = render(err, json_mode=False)
    assert exit_code == 3
    assert use_stderr is True
    assert "Error:" in output
    assert "config set" in output


def test_render_cache_unavailable_human():
    err = CacheUnavailableError("Local cache at /x is unavailable (database is locked).")
    output, exit_code, use_stderr = render(err, json_mode=False)
    assert exit_code == 4
    assert use_stderr is True
    assert output.startswith("Error:")
    assert "database is locked" in output


def test_render_cache_unavailable_json_envelope():
    err = CacheUnavailableError("Local cache at /x is unavailable (database is locked).")
    output, exit_code, _ = render(err, json_mode=True)
    assert exit_code == 4
    envelope = json.loads(output)
    assert envelope["error"]["code"] == "CACHE_UNAVAILABLE"
    assert envelope["error"]["fields"] is None


def test_render_sync_contract_human():
    err = SyncContractError(
        "Cannot derive user_id from /sync response. Run 'expense auth bootstrap' first."
    )
    output, exit_code, use_stderr = render(err, json_mode=False)
    assert exit_code == 5
    assert use_stderr is True
    assert output.startswith("Error:")
    assert "auth bootstrap" in output


def test_render_sync_contract_json_envelope():
    err = SyncContractError("Engine /sync response is missing sync_token; refusing to apply it.")
    output, exit_code, _ = render(err, json_mode=True)
    assert exit_code == 5
    envelope = json.loads(output)
    assert envelope["error"]["code"] == "SYNC_CONTRACT"
    assert envelope["error"]["fields"] is None


def test_format_error_engine_error_with_fields():
    err = EngineError(
        code="VALIDATION_ERROR",
        message="Amount must not be zero",
        fields={"amount_cents": "Must not be zero"},
        status=422,
        raw_body={},
    )
    output = format_error(err)
    assert not output.startswith("Error:")
    assert output.startswith("VALIDATION_ERROR — Amount must not be zero")
    assert "  amount_cents: Must not be zero" in output


def test_format_error_401_includes_hint():
    err = EngineError(
        code="UNAUTHORIZED",
        message="Missing or invalid token",
        fields=None,
        status=401,
        raw_body={},
    )
    output = format_error(err)
    assert "\n\nHint: token is missing or invalid" in output
    assert "expense config set --token" in output


def test_format_error_connection_error():
    err = EngineConnectionError(
        url="https://nonexistent.invalid",
        original=ConnectionRefusedError("refused"),
    )
    assert format_error(err) == (
        "could not reach engine at https://nonexistent.invalid (is it running?)"
    )


def test_format_error_falls_back_to_str():
    assert format_error(RuntimeError("boom")) == "boom"


@pytest.mark.parametrize(
    "err",
    [
        EngineError(
            code="UNAUTHORIZED",
            message="Missing or invalid token",
            fields={"token": "expired"},
            status=401,
            raw_body={},
        ),
        EngineConnectionError(url="https://x.invalid", original=TimeoutError("timeout")),
        ConfigMissingError("No config found. Run: expense config set ..."),
    ],
)
def test_render_human_is_prefix_plus_format_error(err):
    output, _, _ = render(err, json_mode=False)
    assert output == "Error: " + format_error(err)


def test_render_unknown_exception_reraises():
    with pytest.raises(RuntimeError, match="unexpected"):
        render(RuntimeError("unexpected"), json_mode=False)


def test_handle_errors_catches_engine_error():
    @handle_errors
    def cmd(json_output: bool = False):
        raise EngineError(code="NOT_FOUND", message="x", fields=None, status=404, raw_body={})

    with pytest.raises(typer.Exit) as exc:
        cmd()
    assert exc.value.exit_code == 1


def test_handle_errors_catches_connection_error():
    @handle_errors
    def cmd(json_output: bool = False):
        raise EngineConnectionError(url="https://x", original=Exception("x"))

    with pytest.raises(typer.Exit) as exc:
        cmd()
    assert exc.value.exit_code == 2


def test_handle_errors_catches_config_missing():
    @handle_errors
    def cmd(json_output: bool = False):
        raise ConfigMissingError("no config")

    with pytest.raises(typer.Exit) as exc:
        cmd()
    assert exc.value.exit_code == 3


def test_handle_errors_catches_sync_contract():
    @handle_errors
    def cmd(json_output: bool = False):
        raise SyncContractError("broken contract")

    with pytest.raises(typer.Exit) as exc:
        cmd()
    assert exc.value.exit_code == 5


def test_handle_errors_propagates_unexpected():
    @handle_errors
    def cmd(json_output: bool = False):
        raise RuntimeError("bug")

    with pytest.raises(RuntimeError, match="bug"):
        cmd()
