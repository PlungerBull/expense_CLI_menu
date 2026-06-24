"""Step 9.5.8 — menu-driven Reports flows.

Covers single-month + range variants, the show-hashtags / expand-hashtags
toggles, pre-flight span guards (too wide + inverted), and the resolved
hashtag-name display path. Reports is engine-only (no cache reads in the
write path), so we stub GET /v1/reports/monthly directly with respx and
monkey-patch the hashtag-name resolver to inject a known UUID→name map.
"""

from uuid import uuid4

import httpx
import pytest
import respx

from expense import config as config_module
from expense.menu.groups import _common as menu_common
from expense.menu.groups import reports as menu_reports

SINGLE_MONTH_RESPONSE = {
    "month": {"year": 2026, "month": 3},
    "categories": [
        {
            "id": "cat-food",
            "name": "Food",
            "spent_cents": -50000,
            "spent_home_cents": -50000,
            "hashtag_breakdown": [
                {
                    "hashtag_ids": ["aaaa", "bbbb"],
                    "spent_cents": -30000,
                    "spent_home_cents": -30000,
                },
                {
                    "hashtag_ids": [],
                    "spent_cents": -20000,
                    "spent_home_cents": -20000,
                },
            ],
        }
    ],
    "totals": {
        "inflow_cents": 0,
        "inflow_home_cents": 0,
        "outflow_cents": 50000,
        "outflow_home_cents": 50000,
        "net_cents": -50000,
        "net_home_cents": -50000,
    },
}

RANGE_RESPONSE = {
    "months": [
        {
            "month": {"year": 2026, "month": 1},
            "categories": [
                {
                    "id": "cat-food",
                    "name": "Food",
                    "spent_cents": -45000,
                    "spent_home_cents": -45000,
                    "hashtag_breakdown": [
                        {
                            "hashtag_ids": ["aaaa", "bbbb"],
                            "spent_cents": -10000,
                            "spent_home_cents": -10000,
                        },
                        {
                            "hashtag_ids": ["aaaa"],
                            "spent_cents": -35000,
                            "spent_home_cents": -35000,
                        },
                    ],
                }
            ],
            "totals": {
                "inflow_cents": 0,
                "inflow_home_cents": 0,
                "outflow_cents": 45000,
                "outflow_home_cents": 45000,
                "net_cents": -45000,
                "net_home_cents": -45000,
            },
        },
        {
            "month": {"year": 2026, "month": 2},
            "categories": [
                {
                    "id": "cat-food",
                    "name": "Food",
                    "spent_cents": -52000,
                    "spent_home_cents": -52000,
                    "hashtag_breakdown": [
                        {
                            "hashtag_ids": ["aaaa", "bbbb"],
                            "spent_cents": -15000,
                            "spent_home_cents": -15000,
                        },
                        {
                            "hashtag_ids": ["aaaa"],
                            "spent_cents": -37000,
                            "spent_home_cents": -37000,
                        },
                    ],
                }
            ],
            "totals": {
                "inflow_cents": 0,
                "inflow_home_cents": 0,
                "outflow_cents": 52000,
                "outflow_home_cents": 52000,
                "net_cents": -52000,
                "net_home_cents": -52000,
            },
        },
    ]
}

NAME_MAP = {"aaaa": "Food", "bbbb": "Club"}


@pytest.fixture
def configured(tmp_path, monkeypatch):
    config_path = tmp_path / ".expense-config"
    cache_path = tmp_path / "cache.sqlite3"
    monkeypatch.setenv("EXPENSE_CONFIG", str(config_path))
    monkeypatch.setenv("EXPENSE_CACHE", str(cache_path))
    config_module.save(
        config_module.Config(
            engine_url="https://api.example.com",
            token="ewe_pat_test",
            client_id=uuid4(),
        )
    )
    monkeypatch.setenv("EXPENSE_STATELESS", "1")
    monkeypatch.setenv("EXPENSE_NO_SYNC_AFTER", "1")
    yield


def _patch_name_map(monkeypatch, mapping: dict[str, str]) -> None:
    monkeypatch.setattr(
        "expense.commands.dashboard_cmd.load_hashtag_name_map", lambda: dict(mapping)
    )
    monkeypatch.setattr("expense.commands.reports_cmd.load_hashtag_name_map", lambda: dict(mapping))


class _FakeAsk:
    def __init__(self, answer):
        self._answer = answer

    def ask(self):
        if isinstance(self._answer, BaseException):
            raise self._answer
        return self._answer


class _PromptScript:
    def __init__(self, answers: list):
        self._queue = list(answers)

    def __call__(self, *_args, **_kwargs):
        if not self._queue:
            raise AssertionError("Prompt script exhausted — unexpected questionary call.")
        return _FakeAsk(self._queue.pop(0))

    @property
    def remaining(self) -> int:
        return len(self._queue)


def _patch_questionary(monkeypatch, script: _PromptScript) -> None:
    monkeypatch.setattr(menu_common.questionary, "text", script)
    monkeypatch.setattr(menu_common.questionary, "select", script)
    monkeypatch.setattr(menu_reports.questionary, "select", script)
    monkeypatch.setattr(menu_reports.questionary, "text", script)


class _StubCtx:
    def __init__(self):
        from expense.context import AppContext

        self.obj = AppContext(verbose=False, no_cache=True, no_sync_after=True)


def _make_ctx() -> _StubCtx:
    return _StubCtx()


# --------------------------------------------------------------- back / abort


@respx.mock
def test_menu_back_exits(configured, monkeypatch):
    route = respx.get("https://api.example.com/v1/reports/monthly")
    script = _PromptScript(["← Back"])
    _patch_questionary(monkeypatch, script)
    menu_reports.run_reports_menu(_make_ctx())
    assert not route.called
    assert script.remaining == 0


@respx.mock
def test_menu_keyboard_interrupt_exits(configured, monkeypatch):
    route = respx.get("https://api.example.com/v1/reports/monthly")
    script = _PromptScript([KeyboardInterrupt()])
    _patch_questionary(monkeypatch, script)
    menu_reports.run_reports_menu(_make_ctx())
    assert not route.called


# --------------------------------------------- dashboard umbrella (delegation)

_DASHBOARD_RESPONSE = {
    "month": "2026-05",
    "accounts": [],
    "categories": [],
    "totals": {},
}


@respx.mock
def test_umbrella_routes_dashboard_current_month(configured, monkeypatch):
    """Reports is the umbrella: the Dashboard entry hits GET /v1/dashboard."""
    route = respx.get("https://api.example.com/v1/dashboard").mock(
        return_value=httpx.Response(200, json=_DASHBOARD_RESPONSE)
    )
    script = _PromptScript(
        [
            "Outstanding Amounts (current month)",
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_reports.run_reports_menu(_make_ctx())
    assert route.called
    assert "include_archived" not in route.calls.last.request.url.params


@respx.mock
def test_umbrella_routes_dashboard_archived(configured, monkeypatch):
    route = respx.get("https://api.example.com/v1/dashboard").mock(
        return_value=httpx.Response(200, json=_DASHBOARD_RESPONSE)
    )
    script = _PromptScript(
        [
            "Outstanding Amounts (with archived panels)",
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_reports.run_reports_menu(_make_ctx())
    assert route.called
    assert route.calls.last.request.url.params.get("include_archived") == "true"


# --------------------------------------------------------------- single month


@respx.mock
def test_single_month_with_breakdown_resolves_names(configured, monkeypatch, capsys):
    _patch_name_map(monkeypatch, NAME_MAP)
    route = respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(200, json=SINGLE_MONTH_RESPONSE)
    )
    script = _PromptScript(
        [
            "Monthly report (single month)",
            "2026-03",  # month prompt
            True,  # Show hashtag breakdown? Yes
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_reports.run_reports_menu(_make_ctx())

    assert route.called
    request = route.calls.last.request
    assert request.url.params.get("year") == "2026"
    assert request.url.params.get("month") == "3"

    out = capsys.readouterr().out
    assert "Month: 2026-03" in out
    # Hashtag sub-rows now render as indented rows in the categories table:
    # the combo name lives in the Name column and amounts in Spent/Home cells.
    assert "Food + Club" in out
    assert "-300.00" in out
    assert "(no hashtags)" in out
    assert "-200.00" in out


@respx.mock
def test_single_month_hides_breakdown_when_toggled_off(configured, monkeypatch, capsys):
    _patch_name_map(monkeypatch, NAME_MAP)
    route = respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(200, json=SINGLE_MONTH_RESPONSE)
    )
    script = _PromptScript(
        [
            "Monthly report (single month)",
            "2026-03",
            False,  # Show hashtag breakdown? No
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_reports.run_reports_menu(_make_ctx())

    assert route.called
    out = capsys.readouterr().out
    assert "Month: 2026-03" in out
    assert "Food" in out
    assert "breakdown:" not in out
    assert "Food + Club" not in out


# --------------------------------------------------------------- range


@respx.mock
def test_range_compact_matrix(configured, monkeypatch, capsys):
    _patch_name_map(monkeypatch, NAME_MAP)
    route = respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(200, json=RANGE_RESPONSE)
    )
    script = _PromptScript(
        [
            "Monthly report (range)",
            "2026-01",  # From
            "2026-02",  # To
            False,  # Expand by hashtag? No
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_reports.run_reports_menu(_make_ctx())

    assert route.called
    request = route.calls.last.request
    assert request.url.params.get("from_year") == "2026"
    assert request.url.params.get("from_month") == "1"
    assert request.url.params.get("to_year") == "2026"
    assert request.url.params.get("to_month") == "2"

    out = capsys.readouterr().out
    assert "2026-01" in out
    assert "2026-02" in out
    assert "Food" in out
    assert "Totals (net)" in out
    # Compact mode — no per-combo sub-rows.
    assert "Food + Club" not in out


@respx.mock
def test_range_expanded_shows_resolved_subrows(configured, monkeypatch, capsys):
    _patch_name_map(monkeypatch, NAME_MAP)
    route = respx.get("https://api.example.com/v1/reports/monthly").mock(
        return_value=httpx.Response(200, json=RANGE_RESPONSE)
    )
    script = _PromptScript(
        [
            "Monthly report (range)",
            "2026-01",
            "2026-02",
            True,  # Expand by hashtag? Yes
            "",  # pause
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_reports.run_reports_menu(_make_ctx())

    assert route.called
    out = capsys.readouterr().out
    assert "Food + Club" in out
    # Single-id row stays as just the resolved name.
    assert "Food " in out
    # Numbers from the breakdown should appear.
    assert "-100.00" in out
    assert "-350.00" in out


# --------------------------------------------------------------- span guards


@respx.mock
def test_range_too_wide_rejected_before_http(configured, monkeypatch, capsys):
    route = respx.get("https://api.example.com/v1/reports/monthly")
    script = _PromptScript(
        [
            "Monthly report (range)",
            "2024-01",
            "2026-06",  # 30 months
            "",  # pause after error
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_reports.run_reports_menu(_make_ctx())

    assert not route.called
    err = capsys.readouterr().err
    assert "max is 24" in err


@respx.mock
def test_range_inverted_rejected_before_http(configured, monkeypatch, capsys):
    route = respx.get("https://api.example.com/v1/reports/monthly")
    script = _PromptScript(
        [
            "Monthly report (range)",
            "2026-06",
            "2026-01",
            "",  # pause after error
            "← Back",
        ]
    )
    _patch_questionary(monkeypatch, script)
    menu_reports.run_reports_menu(_make_ctx())

    assert not route.called
    err = capsys.readouterr().err
    assert "must be on or before" in err


# --------------------------------------------------------------- prompt_year_month


def test_prompt_year_month_canonicalizes(monkeypatch):
    script = _PromptScript(["2026-03"])
    monkeypatch.setattr(menu_common.questionary, "text", script)
    ok, ym = menu_common.prompt_year_month("Month")
    assert ok is True
    assert ym == "2026-03"


def test_prompt_year_month_ctrl_c(monkeypatch):
    script = _PromptScript([None])
    monkeypatch.setattr(menu_common.questionary, "text", script)
    ok, ym = menu_common.prompt_year_month("Month")
    assert ok is False
    assert ym is None
