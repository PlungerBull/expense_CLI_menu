import json
from functools import wraps
from typing import Any

import typer


class EngineError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        fields: dict[str, Any] | None,
        status: int,
        raw_body: dict[str, Any],
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.fields = fields
        self.status = status
        self.raw_body = raw_body


class EngineConnectionError(Exception):
    def __init__(self, url: str, original: Exception):
        super().__init__(str(original))
        self.url = url
        self.original = original


class ConfigMissingError(Exception):
    pass


def render(err: Exception, *, json_mode: bool) -> tuple[str, int, bool]:
    """Render an error.

    Returns (output_text, exit_code, use_stderr).
    JSON mode writes to stdout so output is pipe-friendly; human mode writes to stderr.
    """
    if isinstance(err, EngineError):
        if json_mode:
            return json.dumps(err.raw_body, indent=2), 1, False
        lines = [f"Error: {err.code} — {err.message}"]
        if err.fields:
            for field, message in err.fields.items():
                lines.append(f"  {field}: {message}")
        return "\n".join(lines), 1, True

    if isinstance(err, EngineConnectionError):
        if json_mode:
            envelope = {
                "error": {
                    "code": "CONNECTION_ERROR",
                    "message": str(err),
                    "fields": None,
                }
            }
            return json.dumps(envelope, indent=2), 2, False
        return f"Error: could not reach engine at {err.url} (is it running?)", 2, True

    if isinstance(err, ConfigMissingError):
        if json_mode:
            envelope = {
                "error": {
                    "code": "CONFIG_MISSING",
                    "message": str(err),
                    "fields": None,
                }
            }
            return json.dumps(envelope, indent=2), 3, False
        return f"Error: {err}", 3, True

    raise err


def handle_errors(fn):
    """Wrap a Typer command so engine/connection/config errors exit cleanly."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        json_mode = bool(kwargs.get("json_output", False))
        try:
            return fn(*args, **kwargs)
        except (EngineError, EngineConnectionError, ConfigMissingError) as err:
            output, exit_code, use_stderr = render(err, json_mode=json_mode)
            typer.echo(output, err=use_stderr)
            raise typer.Exit(code=exit_code) from err

    return wrapper
