"""Home header stat cluster — pure-function coverage (no event loop).

The header's `net · spent · owed` line is built by three pure helpers in
home.py. These lock the contract: home-currency figures only, owed flips
label + color with its sign and vanishes at zero, and every color comes from
the palette (never a literal color name — which also keeps the no-literal-color
guard in test_tui_theme.py green).
"""

import io

from rich.console import Console

import expense.tui.screens.home as home
from expense.tui.theme import Palette

PALETTE = Palette(success="#7fbf8f", error="#cf8d8d", warning="#d6b878")


def _spans(text):
    """(substring, style-str) for every styled span, for asserting sign colors."""
    return [(text.plain[s.start : s.end], str(s.style)) for s in text.spans]


def _render(renderable, width=100) -> str:
    con = Console(file=io.StringIO(), width=width)
    con.print(renderable)
    return con.file.getvalue()


# ---- _signed -------------------------------------------------------------


def test_signed_prefixes_plus_for_nonnegative():
    assert home._signed(480000) == "+4,800.00"
    assert home._signed(0) == "+0.00"
    assert home._signed(-32000) == "-320.00"
    assert home._signed(None) == "(null)"  # format_cents' own null sentinel, no +


# ---- _extract_stats ------------------------------------------------------


def test_extract_stats_pulls_home_figures():
    body = {
        "totals": {
            "net_home_cents": 480000,
            "outflow_home_cents": 320000,
            "net_cents": 999,  # native — must be ignored
            "outflow_cents": 111,
        },
        "people": [{"current_balance_cents": -4500, "current_balance_home_cents": -4500}],
    }
    assert home._extract_stats(body) == {"net": 480000, "spent": 320000, "owed": -4500}


def test_owed_sums_home_cents_skips_none_ignores_native():
    body = {
        "totals": {},
        "people": [
            {"current_balance_cents": 100, "current_balance_home_cents": 30000},
            {"current_balance_cents": 200, "current_balance_home_cents": -12000},
            {"current_balance_cents": 999, "current_balance_home_cents": None},  # skipped
        ],
    }
    stats = home._extract_stats(body)
    assert stats["owed"] == 30000 - 12000  # native ignored, None skipped
    assert stats["net"] is None and stats["spent"] is None


def test_extract_stats_missing_blocks_are_safe():
    assert home._extract_stats({}) == {"net": None, "spent": None, "owed": 0}


# ---- _stat_cluster -------------------------------------------------------


def test_cluster_none_is_empty():
    assert home._stat_cluster(None, PALETTE).plain == ""


def test_cluster_owed_to_you_is_green():
    text = home._stat_cluster({"net": 480000, "spent": 320000, "owed": 42000}, PALETTE)
    plain = text.plain
    assert "net +4,800.00" in plain
    assert "spent 3,200.00" in plain
    assert "owed to you 420.00" in plain
    assert "you owe" not in plain
    spans = _spans(text)
    assert ("+4,800.00", PALETTE.success) in spans  # net ≥ 0 → success
    assert ("3,200.00", PALETTE.error) in spans  # spent is outflow → error
    assert ("420.00", PALETTE.success) in spans  # owed to you → success


def test_cluster_you_owe_is_red_and_label_flips():
    text = home._stat_cluster({"net": -5000, "spent": 320000, "owed": -18000}, PALETTE)
    plain = text.plain
    assert "you owe 180.00" in plain  # abs magnitude
    assert "owed to you" not in plain
    spans = _spans(text)
    assert ("-50.00", PALETTE.error) in spans  # net < 0 → error
    assert ("180.00", PALETTE.error) in spans  # you owe → error


def test_cluster_drops_owed_when_zero():
    text = home._stat_cluster({"net": 480000, "spent": 320000, "owed": 0}, PALETTE)
    plain = text.plain
    assert "owed" not in plain and "you owe" not in plain
    assert plain == "net +4,800.00  ·  spent 3,200.00"


def test_cluster_uses_no_literal_color_names_when_palette_absent():
    text = home._stat_cluster({"net": 480000, "spent": 320000, "owed": 42000}, None)
    assert "net +4,800.00" in text.plain
    styles = {str(s.style) for s in text.spans}
    assert not ({"green", "red", "yellow"} & styles)


# ---- _build_header -------------------------------------------------------


def test_build_header_shows_wordmark_and_cluster():
    out = _render(home._build_header({"net": 480000, "spent": 320000, "owed": 42000}, PALETTE))
    assert "EXPENSE WORLD" in out
    assert "net" in out and "owed to you" in out


def test_build_header_none_is_wordmark_only():
    out = _render(home._build_header(None, None))
    assert "EXPENSE WORLD" in out
    assert "net" not in out and "spent" not in out
