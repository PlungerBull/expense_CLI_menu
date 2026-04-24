from uuid import uuid4

import httpx
import pytest
import respx

from expense.config import Config
from expense.errors import EngineConnectionError, EngineError
from expense.http import ExpenseClient


@pytest.fixture
def config():
    return Config(
        engine_url="https://api.example.com",
        token="ewe_pat_test123",
        client_id=uuid4(),
        main_currency="USD",
    )


@respx.mock
def test_health_bypasses_v1_prefix(config):
    route = respx.get("https://api.example.com/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    with ExpenseClient(config) as client:
        result = client.get("/health", auth=False)

    assert result == {"status": "ok"}
    assert route.called
    assert route.calls.last.request.url.path == "/health"


@respx.mock
def test_other_paths_get_v1_prefix(config):
    route = respx.get("https://api.example.com/v1/auth/me").mock(
        return_value=httpx.Response(200, json={"user": {}, "settings": {}})
    )
    with ExpenseClient(config) as client:
        client.get("/auth/me")

    assert route.calls.last.request.url.path == "/v1/auth/me"


@respx.mock
def test_path_already_v1_is_not_double_prefixed(config):
    route = respx.get("https://api.example.com/v1/auth/me").mock(
        return_value=httpx.Response(200, json={})
    )
    with ExpenseClient(config) as client:
        client.get("/v1/auth/me")

    assert route.calls.last.request.url.path == "/v1/auth/me"


@respx.mock
def test_authorization_header_present_on_auth_requests(config):
    route = respx.get("https://api.example.com/v1/auth/me").mock(
        return_value=httpx.Response(200, json={})
    )
    with ExpenseClient(config) as client:
        client.get("/auth/me")

    assert route.calls.last.request.headers["Authorization"] == f"Bearer {config.token}"


@respx.mock
def test_authorization_absent_when_auth_false(config):
    route = respx.get("https://api.example.com/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    with ExpenseClient(config) as client:
        client.get("/health", auth=False)

    assert "authorization" not in route.calls.last.request.headers


@respx.mock
def test_x_client_id_present_on_every_request(config):
    route_me = respx.get("https://api.example.com/v1/auth/me").mock(
        return_value=httpx.Response(200, json={})
    )
    route_health = respx.get("https://api.example.com/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    with ExpenseClient(config) as client:
        client.get("/auth/me")
        client.get("/health", auth=False)

    assert route_me.calls.last.request.headers["X-Client-Id"] == str(config.client_id)
    assert route_health.calls.last.request.headers["X-Client-Id"] == str(config.client_id)


@respx.mock
def test_writes_get_unique_idempotency_keys(config):
    route = respx.post("https://api.example.com/v1/auth/bootstrap").mock(
        return_value=httpx.Response(200, json={"user": {}, "settings": {}})
    )
    with ExpenseClient(config) as client:
        client.post("/auth/bootstrap", json_body={"display_name": "a"})
        client.post("/auth/bootstrap", json_body={"display_name": "a"})

    keys = [call.request.headers["X-Idempotency-Key"] for call in route.calls]
    assert len(keys) == 2
    assert keys[0] != keys[1]


@respx.mock
def test_reads_do_not_send_idempotency_key(config):
    route = respx.get("https://api.example.com/v1/auth/me").mock(
        return_value=httpx.Response(200, json={})
    )
    with ExpenseClient(config) as client:
        client.get("/auth/me")

    assert "x-idempotency-key" not in route.calls.last.request.headers


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "UNAUTHORIZED"),
        (403, "FORBIDDEN"),
        (404, "NOT_FOUND"),
        (409, "CONFLICT"),
        (422, "VALIDATION_ERROR"),
    ],
)
@respx.mock
def test_engine_errors_translate_by_status(config, status, code):
    respx.get("https://api.example.com/v1/auth/me").mock(
        return_value=httpx.Response(
            status,
            json={"error": {"code": code, "message": "bad", "fields": None}},
        )
    )
    with ExpenseClient(config) as client, pytest.raises(EngineError) as exc:
        client.get("/auth/me")

    assert exc.value.code == code
    assert exc.value.status == status


@respx.mock
def test_validation_error_includes_fields(config):
    respx.put("https://api.example.com/v1/auth/settings").mock(
        return_value=httpx.Response(
            422,
            json={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid",
                    "fields": {"main_currency": "Unsupported currency"},
                }
            },
        )
    )
    with ExpenseClient(config) as client, pytest.raises(EngineError) as exc:
        client.put("/auth/settings", json_body={"main_currency": "EUR"})

    assert exc.value.fields == {"main_currency": "Unsupported currency"}


@respx.mock
def test_connection_error_on_network_failure(config):
    respx.get("https://api.example.com/v1/auth/me").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    with ExpenseClient(config) as client, pytest.raises(EngineConnectionError) as exc:
        client.get("/auth/me")

    assert "api.example.com" in exc.value.url


@respx.mock
def test_connection_error_on_timeout(config):
    respx.get("https://api.example.com/v1/auth/me").mock(
        side_effect=httpx.TimeoutException("timed out")
    )
    with ExpenseClient(config) as client, pytest.raises(EngineConnectionError):
        client.get("/auth/me")


@respx.mock
def test_connection_error_on_non_json_response(config):
    respx.get("https://api.example.com/v1/auth/me").mock(
        return_value=httpx.Response(500, text="<html>Internal Server Error</html>")
    )
    with ExpenseClient(config) as client, pytest.raises(EngineConnectionError):
        client.get("/auth/me")


@respx.mock
def test_connection_error_on_malformed_error_envelope(config):
    respx.get("https://api.example.com/v1/auth/me").mock(
        return_value=httpx.Response(500, json={"unexpected": "shape"})
    )
    with ExpenseClient(config) as client, pytest.raises(EngineConnectionError):
        client.get("/auth/me")


@respx.mock
def test_verbose_dump_redacts_authorization(config, capsys):
    respx.get("https://api.example.com/v1/auth/me").mock(
        return_value=httpx.Response(200, json={"user": {"id": "x"}})
    )
    with ExpenseClient(config, verbose=True) as client:
        client.get("/auth/me")

    captured = capsys.readouterr()
    assert "Bearer [REDACTED]" in captured.err
    assert config.token not in captured.err


@respx.mock
def test_verbose_dump_shows_request_body(config, capsys):
    respx.post("https://api.example.com/v1/auth/bootstrap").mock(
        return_value=httpx.Response(200, json={"user": {}, "settings": {}})
    )
    with ExpenseClient(config, verbose=True) as client:
        client.post("/auth/bootstrap", json_body={"display_name": "Alex"})

    captured = capsys.readouterr()
    assert "Alex" in captured.err
    assert "POST" in captured.err


@respx.mock
def test_verbose_dump_shows_response_body(config, capsys):
    respx.get("https://api.example.com/v1/auth/me").mock(
        return_value=httpx.Response(200, json={"user": {"id": "u_xyz"}})
    )
    with ExpenseClient(config, verbose=True) as client:
        client.get("/auth/me")

    captured = capsys.readouterr()
    assert "u_xyz" in captured.err
    assert "200" in captured.err
