#!/usr/bin/env python3
"""Report unit-test fixtures that still expect fields the engine no longer serves.

Why this exists: `pytest tests/unit` is respx-mocked, so it validates the CLI
against fixtures *we* wrote, not against the engine. After the 2026-08 rework it
stayed green while pinning several deleted fields — green meant "the CLI agrees
with itself". This closes that gap mechanically: the engine publishes every field
it serves in `openapi.json` (guaranteed since the 2026-08-07 shapes fix, see
docs/client-breaking-changes.md), so a fixture key that appears in no engine
schema is either drift or a test-local key.

Deliberately NOT a pytest file. tests/unit is hermetic — `tests/unit/conftest.py`
blocks real sockets on purpose — and that rule is worth more than the convenience
of folding this in. Run it by hand after any engine change:

    python scripts/check_fixture_drift.py
    python scripts/check_fixture_drift.py --engine-url http://127.0.0.1:8001

Exit code is 0 when nothing retired is found, 1 otherwise, so it also works as a
gate. It cannot tell a retired engine field from a key a test invented for its own
bookkeeping, so it prints the unknowns and leaves the judgement to a human — see
KNOWN_LOCAL for the ones already triaged.

KNOWN LIMITATION — it unions every schema rather than checking each fixture against
the one endpoint it mocks, so a field that is real *somewhere* passes everywhere.
That is exactly how `cleared` on the inbox fixture survived this check on
2026-08-16: it is real on a transaction, absent from `InboxResponse`, and was found
by reading schemas side by side instead. Tightening this means mapping each fixture
to its endpoint, which the flat `MODULE_RESPONSE = {...}` layout does not encode
today. Until then: a clean run means "no field is dead everywhere", not "every
fixture matches its endpoint".
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

DEFAULT_ENGINE_URL = "http://127.0.0.1:8000"
UNIT_TESTS = Path(__file__).resolve().parent.parent / "tests" / "unit"

# Envelope keys the engine returns that are not schema properties: pagination,
# the error envelope (docs/cli-runtime.md "Engine errors surface cleanly"), and
# the auth/bootstrap wrapper.
ENVELOPE_KEYS = frozenset(
    {
        "items",
        "total",
        "limit",
        "offset",
        "has_more",
        "error",
        "code",
        "message",
        "fields",
        "detail",
        "warnings",
        "user",
        "settings",
        "token",
    }
)

# Keys that are test-local bookkeeping, not engine fields — triaged 2026-08-16.
# Each is a dict key a fixture invents for itself: TUI header stat names, sample
# ids used as dict keys, CLI-side config fields, query-param assertions.
KNOWN_LOCAL = frozenset(
    {
        # TUI home-header stat dict (expense/tui/screens/home.py builds this)
        "net",
        "spent",
        "owed",
        "unrated",
        "cents",
        "unconverted",
        "net_cents",
        "outflow_cents",
        # sample ids used as dict keys in name-map fixtures
        "jan",
        "acc1",
        "acc2",
        "cat1",
        "cat2",
        "aaaa",
        "bbbb",
        "amt",
        # CLI-side config file fields — never sent to the engine
        "engine_url",
        "client_id",
        "future_field",
        "verbose",
        # query-param / flag assertions, not response bodies
        "include_deleted",
        "include_archived",
        "debit_as_negative",
        "hashtag_id",
        "date_from",
        "date_to",
        "to_month",
        "search",
        "statement_date",
        "currency",
        # 422 `fields` payload keys and respx route names
        "user_settings",
        "count",
        "flag",
        "text",
        "note",
        "dashboard",
        "whoami",
        "ping",
        "log",
        "import",
        "delete",
        "unexpected",
        "mouse",
        "ready",
        "actor_type",
    }
)

# A quoted dict key: `"some_key":`. Three chars minimum skips `"id":`-style noise
# that is universally valid anyway.
KEY_RE = re.compile(r'"([a-z][a-z0-9_]{2,})"\s*:')


def engine_field_names(engine_url: str) -> set[str]:
    """Every field name the engine declares across all published schemas."""
    url = engine_url.rstrip("/") + "/openapi.json"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            doc = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        sys.exit(
            f"could not read {url}: {exc}\n"
            "Is the engine running? See ../expense_world_engine/deploy/local/README.md"
        )

    names: set[str] = set()
    for schema in doc.get("components", {}).get("schemas", {}).values():
        names |= set((schema.get("properties") or {}).keys())
    if not names:
        sys.exit(f"{url} published no schema properties — wrong host?")
    return names


def scan_fixtures(known: set[str]) -> dict[str, list[str]]:
    """Map every unknown fixture key to the file:line sites that use it."""
    sites: dict[str, list[str]] = defaultdict(list)
    for path in sorted(UNIT_TESTS.glob("*.py")):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            for key in KEY_RE.findall(line):
                if key not in known:
                    sites[key].append(f"{path.name}:{lineno}")
    return sites


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--engine-url",
        default=DEFAULT_ENGINE_URL,
        help=f"engine to read the contract from (default: {DEFAULT_ENGINE_URL})",
    )
    args = parser.parse_args()

    print(f"reading the engine's own published field list from {args.engine_url} ...")
    known = engine_field_names(args.engine_url) | ENVELOPE_KEYS | KNOWN_LOCAL
    sites = scan_fixtures(known)

    if not sites:
        print("\nno fixture claims a field the engine does not serve.")
        return 0

    print("\nfields the tests still expect, that the engine no longer has:")
    for key in sorted(sites):
        for i, site in enumerate(sorted(sites[key])):
            label = key if i == 0 else ""
            print(f"  {label:<30} {site}")
    print(
        "\nEach is either engine drift (fix the fixture) or a test-local key "
        "(add it to KNOWN_LOCAL, with a note on what it is)."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
