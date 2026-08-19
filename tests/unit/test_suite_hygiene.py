"""Guard: the TUI tests must wait on a condition, never on the clock.

A timed `pilot.pause(0.05)` is a guess at how long the app takes, and it is
wrong in both directions — too short on a loaded CI box (a red build with no
bug behind it, which teaches everyone to stop trusting red), too long on a
normal run. `wait_for(pilot, predicate)` in [helpers.py](helpers.py) polls
every 20ms and continues the instant the thing is there, failing loudly at the
wait site after 2s; a bare `pilot.pause()` drains the message pump once, which
is what a *non-event* assertion needs (an inert keypress, a confirm that must
not fire) since no predicate can express "wait until nothing happens".

Backlog Phase 8 swept the last 31 timed pauses out on 2026-08-18. This test is
what keeps the 32nd from landing silently — the second pass over the same
problem (commit `9d8d2c3` was the first), which is why it is armor now.

`time.sleep` is deliberately NOT guarded: its uses are fake engine clients
simulating latency, not test waits.
"""

import re
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SELF = Path(__file__).name  # this file quotes the very pattern it forbids

_TIMED_PAUSE = re.compile(r"pilot\.pause\(\s*[0-9]")

# The one pause that must stay on the clock: its fake fetch does a real
# time.sleep(0.15), and the test's whole point is to outlast it and prove the
# superseded worker never paints. Keyed on the full line so that editing it
# re-opens the question here rather than silently widening the exemption.
JUSTIFIED = {
    "await pilot.pause(0.25)  # window for the cancelled worker to (not) paint",
}


def test_no_timed_pauses_in_tests():
    offenders = [
        f"{path.name}:{lineno}: {stripped}"
        for path in sorted(TESTS_DIR.glob("*.py"))
        if path.name != SELF
        for lineno, line in enumerate(path.read_text().splitlines(), start=1)
        if _TIMED_PAUSE.search(line) and (stripped := line.strip()) not in JUSTIFIED
    ]
    assert not offenders, (
        "timed pauses are flaky under load — wait on the condition with "
        "wait_for(pilot, predicate), or use a bare pilot.pause() when the "
        f"assertion is a non-event: {offenders}"
    )


def test_justified_exemption_still_exists():
    """The allowlist must not outlive the line it exempts (dead-exemption rot)."""
    corpus = "\n".join(
        path.read_text() for path in sorted(TESTS_DIR.glob("*.py")) if path.name != SELF
    )
    stale = [line for line in JUSTIFIED if line not in corpus]
    assert not stale, f"JUSTIFIED exempts lines that no longer exist: {stale}"
