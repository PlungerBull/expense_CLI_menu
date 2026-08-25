"""The shared batch poster — one atomic chunk, then row by row when it is refused.

Extracted from `expense/import_/apply.py` on 2026-08-25 so the TUI's LOG bar and
the `.xlsx` importer share one copy (docs/decisions.md). These tests are its own
spec; `tests/unit/test_cmd_import.py` remains the proof that the extraction did
not change what the importer does.
"""

import pytest

from expense.batch_write import (
    BATCH_PATH,
    BatchOutcome,
    RowResult,
    chunked,
    post_transaction_batch,
)
from expense.errors import EngineConnectionError, EngineError


class _Client:
    """Answers POSTs from a script, and records what it was asked."""

    def __init__(self, answers=()):
        self.answers = list(answers)
        self.calls: list[tuple[str, dict]] = []

    def post(self, path, json_body=None):
        self.calls.append((path, json_body))
        if self.answers:
            answer = self.answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return {}

    @property
    def sizes(self) -> list[int]:
        return [len(body["transactions"]) for _, body in self.calls]


def _items(n: int) -> list[dict]:
    return [{"id": f"id{i}", "title": f"row {i}"} for i in range(n)]


def _conflict() -> EngineError:
    return EngineError("CONFLICT", "id exists", None, 409, {})


def _invalid() -> EngineError:
    return EngineError("VALIDATION_ERROR", "amount_cents: Must not be zero.", None, 422, {})


def test_chunked_sizes():
    """Moved from test_import_parse.py with the function itself."""
    assert [len(c) for c in chunked(list(range(450)), 200)] == [200, 200, 50]


def test_an_empty_list_makes_no_call_at_all():
    client = _Client()
    outcome = post_transaction_batch(client, [])
    assert client.calls == []
    assert outcome.results == [] and not outcome.stopped


def test_a_clean_batch_reports_every_row_created():
    client = _Client()
    outcome = post_transaction_batch(client, _items(3))
    assert client.sizes == [3]  # one call, not three
    assert outcome.results == [RowResult.CREATED] * 3
    assert outcome.errors == {} and not outcome.stopped
    assert outcome.written == [0, 1, 2]


def test_chunking_splits_at_the_size_asked_for():
    client = _Client()
    post_transaction_batch(client, _items(450), chunk_size=200)
    assert client.sizes == [200, 200, 50]


def test_a_422_falls_back_to_one_row_per_batch_and_names_the_bad_one():
    """The engine will not say which row, so the fallback asks one at a time —
    the good rows still land and the bad one reports its own error."""
    client = _Client([_invalid(), {}, _invalid(), {}])
    outcome = post_transaction_batch(client, _items(3))

    assert client.sizes == [3, 1, 1, 1]  # the chunk, then each row
    assert outcome.results == [RowResult.CREATED, RowResult.FAILED, RowResult.CREATED]
    assert "Must not be zero" in outcome.errors[1]
    assert 0 not in outcome.errors and 2 not in outcome.errors


def test_a_409_row_counts_as_written_not_failed():
    """A client-minted id that already exists means the row IS in the ledger.
    That is what makes a retry after a half-written save safe."""
    client = _Client([_conflict(), _conflict(), {}])
    outcome = post_transaction_batch(client, _items(2))

    assert outcome.results == [RowResult.EXISTED, RowResult.CREATED]
    assert outcome.errors == {}
    assert outcome.written == [0, 1]


def test_a_chunk_level_refusal_is_not_retried_row_by_row():
    """401/403/5xx would fail identically for every row — one honest message
    beats hammering the engine once per row."""
    client = _Client([EngineError("FORBIDDEN", "nope", None, 403, {})])
    outcome = post_transaction_batch(client, _items(3))

    assert client.sizes == [3]  # no fallback
    assert outcome.results == [RowResult.FAILED] * 3
    assert len(outcome.failures) == 1  # grouped, not one per row
    assert outcome.failures[0].indices == (0, 1, 2)
    assert outcome.errors == {i: "FORBIDDEN — nope" for i in range(3)}


def test_a_connection_error_stops_and_leaves_the_tail_unsent():
    """Unsent is not failed: those rows never reached the engine, so they are
    safe to retry exactly as they are."""
    client = _Client([{}, EngineConnectionError(url="http://x", original=OSError("down"))])
    outcome = post_transaction_batch(client, _items(3), chunk_size=1)

    assert client.sizes == [1, 1]  # the third chunk was never attempted
    assert outcome.results == [RowResult.CREATED, RowResult.UNSENT, RowResult.UNSENT]
    assert outcome.stopped and outcome.stop_chunk_index == 1
    assert outcome.unsent == [1, 2]


def test_a_connection_error_inside_the_fallback_also_stops():
    client = _Client(
        [_invalid(), {}, EngineConnectionError(url="http://x", original=OSError("down"))]
    )
    outcome = post_transaction_batch(client, _items(3))

    assert outcome.results == [RowResult.CREATED, RowResult.UNSENT, RowResult.UNSENT]
    assert outcome.stopped


@pytest.mark.parametrize(
    "results,wanted,count",
    [
        ([RowResult.CREATED, RowResult.EXISTED], RowResult.CREATED, 1),
        ([RowResult.FAILED, RowResult.FAILED], RowResult.FAILED, 2),
    ],
)
def test_count_tallies_one_result(results, wanted, count):
    assert BatchOutcome(results=results).count(wanted) == count


def test_the_path_is_the_batch_endpoint_with_the_transactions_envelope():
    client = _Client()
    post_transaction_batch(client, _items(1))
    path, body = client.calls[0]
    assert path == BATCH_PATH == "/transactions/batch"
    assert list(body) == ["transactions"]
