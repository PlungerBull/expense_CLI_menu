import json
import sys
import time
import uuid
from json import JSONDecodeError
from typing import Any

import httpx

from expense.config import Config
from expense.errors import EngineConnectionError, EngineError

_WRITE_METHODS = frozenset(["POST", "PUT", "PATCH", "DELETE"])

# Bounded same-key retry for writes (backlog 3.1): the engine replays the
# original response for a repeated X-Idempotency-Key (24h TTL), so re-sending
# after a timeout or transient 5xx can never double-apply. Scope is exactly
# timeout + 5xx — a connect failure means the engine isn't reachable at all
# and fails fast, and reads are safe for callers to re-run themselves.
_WRITE_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = (1.0, 2.0)
_RETRYABLE_STATUS = frozenset({500, 502, 503, 504})


class ExpenseClient:
    def __init__(
        self,
        config: Config,
        *,
        verbose: bool = False,
        timeout_read: float = 60.0,
    ):
        self._config = config
        self._verbose = verbose

        timeout = httpx.Timeout(connect=10.0, read=timeout_read, write=10.0, pool=5.0)
        self._client = httpx.Client(
            base_url=config.engine_url,
            timeout=timeout,
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self) -> None:
        self._client.close()

    def get(self, path: str, *, auth: bool = True, params: dict | None = None) -> Any:
        """Return the engine's JSON verbatim — a dict envelope for most
        endpoints, a bare list for list-shaped ones."""
        return self._request("GET", path, auth=auth, params=params)

    def post(self, path: str, json_body: dict | None = None) -> dict:
        return self._request("POST", path, json_body=json_body)

    def put(self, path: str, json_body: dict | None = None) -> dict:
        return self._request("PUT", path, json_body=json_body)

    def patch(self, path: str, json_body: dict | None = None) -> dict:
        return self._request("PATCH", path, json_body=json_body)

    def delete(self, path: str) -> dict:
        return self._request("DELETE", path)

    def _resolve_path(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        if path == "/health":
            return path
        if path.startswith("/v1/") or path == "/v1":
            return path
        return "/v1" + path

    def _request(
        self,
        method: str,
        path: str,
        *,
        auth: bool = True,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> Any:
        resolved = self._resolve_path(path)
        headers: dict[str, str] = {}
        if auth and self._config.token:
            headers["Authorization"] = f"Bearer {self._config.token}"
        is_write = method in _WRITE_METHODS
        if is_write:
            # Minted once per logical write; the retry loop below re-sends the
            # same key so the engine replays instead of double-applying.
            headers["X-Idempotency-Key"] = str(uuid.uuid4())

        attempts = _WRITE_ATTEMPTS if is_write else 1

        for attempt in range(1, attempts + 1):
            request = self._client.build_request(
                method,
                resolved,
                params=params,
                json=json_body,
                headers=headers,
            )
            if self._verbose:
                self._dump_request(request)
            try:
                response = self._client.send(request)
            except httpx.TransportError as exc:
                # Base of connect/timeout plus read/write aborts, protocol
                # and proxy failures, and UnsupportedProtocol (scheme-less
                # URL) — none of these may escape as a raw traceback.
                if isinstance(exc, httpx.TimeoutException) and attempt < attempts:
                    self._notify_retry(attempt, attempts, "timed out")
                    time.sleep(_RETRY_BACKOFF_SECONDS[attempt - 1])
                    continue
                raise EngineConnectionError(url=str(request.url), original=exc) from exc
            if response.status_code in _RETRYABLE_STATUS and attempt < attempts:
                self._notify_retry(attempt, attempts, f"got HTTP {response.status_code}")
                time.sleep(_RETRY_BACKOFF_SECONDS[attempt - 1])
                continue
            break

        if self._verbose:
            self._dump_response(response)

        try:
            body = response.json() if response.content else {}
        except (JSONDecodeError, ValueError) as exc:
            raise EngineConnectionError(
                url=str(request.url),
                original=ValueError(
                    f"Non-JSON response (HTTP {response.status_code}): {response.text[:200]}"
                ),
            ) from exc

        if response.is_success:
            return body

        error = body.get("error") if isinstance(body, dict) else None
        if not (isinstance(error, dict) and "code" in error and "message" in error):
            raise EngineConnectionError(
                url=str(request.url),
                original=ValueError(
                    f"Unexpected error shape (HTTP {response.status_code}): {body}"
                ),
            )

        raise EngineError(
            code=error["code"],
            message=error["message"],
            fields=error.get("fields"),
            status=response.status_code,
            raw_body=body,
        )

    def _notify_retry(self, attempt: int, attempts: int, cause: str) -> None:
        print(
            f"Write {cause}; retrying ({attempt + 1}/{attempts}) with the same "
            "idempotency key — the engine replays instead of double-applying.",
            file=sys.stderr,
            flush=True,
        )

    def _dump_request(self, request: httpx.Request) -> None:
        print(f">>> {request.method} {request.url}", file=sys.stderr, flush=True)
        for name, value in request.headers.items():
            if name.lower() == "authorization":
                value = "Bearer [REDACTED]"
            print(f"    {name}: {value}", file=sys.stderr)
        if request.content:
            try:
                decoded = json.dumps(json.loads(request.content))
                print(f"    body: {decoded}", file=sys.stderr)
            except (JSONDecodeError, ValueError):
                print(f"    body: {request.content[:500]!r}", file=sys.stderr)
        print(file=sys.stderr, flush=True)

    def _dump_response(self, response: httpx.Response) -> None:
        print(
            f"<<< {response.status_code} {response.reason_phrase}",
            file=sys.stderr,
            flush=True,
        )
        for name, value in response.headers.items():
            print(f"    {name}: {value}", file=sys.stderr)
        if response.content:
            print(f"    body: {response.text}", file=sys.stderr)
        print(file=sys.stderr, flush=True)
