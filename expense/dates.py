"""Date input normalization for commands that accept --date.

The engine accepts only RFC 3339 datetimes with an explicit timezone offset
(naive datetimes return 422). This module accepts the user's natural shapes
(YYYY-MM-DD, naive datetimes with T or space separator, etc.) and emits the
engine-canonical form. Aware input passes through verbatim so the user's
exact wire format is preserved.
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import typer
import tzlocal


def _local_tz() -> ZoneInfo:
    return ZoneInfo(tzlocal.get_localzone_name())


def now_local_iso() -> str:
    """Local wall-clock time with local timezone offset, ISO 8601."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def to_canonical_aware(user_input: str) -> str:
    """Normalize a user-typed date into RFC 3339 with a timezone offset.

    Accepted shapes:
      - 'YYYY-MM-DD'                     midnight in the user's local zone
      - 'YYYY-MM-DD HH:MM[:SS]'          local zone (space separator)
      - 'YYYY-MM-DDTHH:MM[:SS]'          local zone (T separator)
      - 'YYYY-MM-DDTHH:MM:SSZ'           UTC, passed through verbatim
      - 'YYYY-MM-DDTHH:MM:SS+HH:MM'      explicit offset, passed through verbatim

    Raises typer.BadParameter on unparseable input.
    """
    try:
        dt = datetime.fromisoformat(user_input)
    except ValueError:
        try:
            d = date.fromisoformat(user_input)
        except ValueError as exc:
            raise typer.BadParameter(
                f"Invalid date {user_input!r}. Use YYYY-MM-DD, "
                "'YYYY-MM-DD HH:MM[:SS]', or RFC 3339 with offset.",
                param_hint="--date",
            ) from exc
        dt = datetime.combine(d, time())

    if dt.tzinfo is not None:
        return user_input
    return dt.replace(tzinfo=_local_tz()).isoformat(timespec="seconds")
