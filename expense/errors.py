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


class ConfigInvalidError(Exception):
    pass


class CacheUnavailableError(Exception):
    """The local replica can't be opened right now (locked/unopenable, not corrupt)."""


class SyncContractError(Exception):
    """The engine's /sync response violated its own contract (missing sync_token,
    or no derivable user_id). Not retryable client-side."""


def format_error(err: Exception) -> str:
    """Human-readable error text, without the leading 'Error: ' prefix.

    Shared by render()'s human branch (CLI) and the TUI toasts/banners.
    """
    if isinstance(err, EngineError):
        lines = [f"{err.code} — {err.message}"]
        if err.fields:
            for field, message in err.fields.items():
                lines.append(f"  {field}: {message}")
        if err.status == 401:
            lines.append("")
            lines.append(
                "Hint: token is missing or invalid. Run "
                "'expense config set --token <pat>' to install a fresh PAT, "
                "or 'expense auth bootstrap' if your account is not yet provisioned."
            )
        return "\n".join(lines)
    if isinstance(err, EngineConnectionError):
        return f"could not reach engine at {err.url} (is it running?)"
    # ConfigMissing/ConfigInvalid render as their message, same as any other
    # exception — one fallback covers both.
    return str(err)


# The shared-envelope error families: {ExcType: (envelope code, exit code)}.
# EngineError stays a dedicated branch in render() — its --json output is the
# engine's raw body passed through verbatim, not a client-composed envelope.
_ENVELOPE_ERRORS: dict[type[Exception], tuple[str, int]] = {
    EngineConnectionError: ("CONNECTION_ERROR", 2),
    ConfigMissingError: ("CONFIG_MISSING", 3),
    ConfigInvalidError: ("CONFIG_INVALID", 3),
    CacheUnavailableError: ("CACHE_UNAVAILABLE", 4),
    SyncContractError: ("SYNC_CONTRACT", 5),
}

# Everything handle_errors catches — registering a type in _ENVELOPE_ERRORS
# is the single step that makes it render cleanly.
_HANDLED_ERRORS: tuple[type[Exception], ...] = (EngineError, *_ENVELOPE_ERRORS)


def render(err: Exception, *, json_mode: bool) -> tuple[str, int, bool]:
    """Render an error.

    Returns (output_text, exit_code, use_stderr).
    JSON mode writes to stdout so output is pipe-friendly; human mode writes to stderr.
    """
    if isinstance(err, EngineError):
        if json_mode:
            return json.dumps(err.raw_body, indent=2), 1, False
        return "Error: " + format_error(err), 1, True

    for exc_type, (code, exit_code) in _ENVELOPE_ERRORS.items():
        if isinstance(err, exc_type):
            if json_mode:
                envelope = {"error": {"code": code, "message": str(err), "fields": None}}
                return json.dumps(envelope, indent=2), exit_code, False
            return "Error: " + format_error(err), exit_code, True

    raise err


def handle_errors(fn):
    """Wrap a Typer command so engine/connection/config errors exit cleanly."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        json_mode = bool(kwargs.get("json_output", False))
        try:
            return fn(*args, **kwargs)
        except _HANDLED_ERRORS as err:
            output, exit_code, use_stderr = render(err, json_mode=json_mode)
            typer.echo(output, err=use_stderr)
            raise typer.Exit(code=exit_code) from err

    return wrapper
