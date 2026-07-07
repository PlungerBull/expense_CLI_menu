import json
import sys
import threading
import uuid
from json import JSONDecodeError

import httpx

from expense.config import Config
from expense.errors import EngineConnectionError, EngineError

_WRITE_METHODS = frozenset(["POST", "PUT", "PATCH", "DELETE"])


class ExpenseClient:
    def __init__(
        self,
        config: Config,
        *,
        verbose: bool = False,
        cold_start_notice: bool = False,
        timeout_read: float = 60.0,
    ):
        self._config = config
        self._verbose = verbose
        self._cold_start_notice = cold_start_notice

        timeout = httpx.Timeout(connect=10.0, read=timeout_read, write=10.0, pool=5.0)
        self._client = httpx.Client(
            base_url=config.engine_url,
            timeout=timeout,
            headers={"X-Client-Id": str(config.client_id)},
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self) -> None:
        self._client.close()

    def get(self, path: str, *, auth: bool = True, params: dict | None = None) -> dict:
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
    ) -> dict:
        resolved = self._resolve_path(path)
        headers: dict[str, str] = {}
        if auth and self._config.token:
            headers["Authorization"] = f"Bearer {self._config.token}"
        if method in _WRITE_METHODS:
            headers["X-Idempotency-Key"] = str(uuid.uuid4())

        timer = self._start_cold_notice() if self._cold_start_notice else None

        try:
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
                # Base of connect/timeout plus read/write aborts, protocol and
                # proxy failures, and UnsupportedProtocol (scheme-less URL) —
                # none of these may escape as a raw traceback.
                raise EngineConnectionError(url=str(request.url), original=exc) from exc
        finally:
            if timer is not None:
                timer.cancel()

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

    def _start_cold_notice(self) -> threading.Timer:
        def notice() -> None:
            print(
                "Engine cold-start can take up to 45s...",
                file=sys.stderr,
                flush=True,
            )

        timer = threading.Timer(3.0, notice)
        timer.daemon = True
        timer.start()
        return timer

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
