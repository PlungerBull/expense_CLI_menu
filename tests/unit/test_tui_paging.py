"""20-row pagination — widget window/indicator/keys + the shared helpers.

Pure tests in the style of the other widget suites: `_build()` renders through
a Rich Console; action handlers run with `_refresh`/`post_message` stubbed so
no event loop is needed. Screen-level adoption (fetch params, page turns) is
tested in the per-screen suites.
"""

import io

from rich.console import Console

from expense.commands._resource import DEFAULT_PAGE_ROWS, effective_limit
from expense.tui.screens._base import PagedListMixin
from expense.tui.widgets.checklist import CheckList
from expense.tui.widgets.cursor_list import CursorList, page_indicator


def _text(renderable) -> str:
    con = Console(file=io.StringIO(), width=120)
    con.print(renderable)
    return con.file.getvalue()


def _rows(n: int) -> list[tuple]:
    return [(f"id{i}", (f"row {i:02d}", f"{i}.00")) for i in range(n)]


def _list(n: int = 45, **kwargs) -> CursorList:
    lst = CursorList(["Title", "Amount"], _rows(n), align_right={1}, **kwargs)
    lst._refresh = lambda: None  # pure: no event loop, no live repaint
    return lst


# ---- page_indicator / effective_limit (shared helpers) ---------------------


def test_page_indicator_none_when_single_page():
    assert page_indicator(0, 5, 5, 20) is None
    assert page_indicator(0, 20, 20, 20) is None
    assert page_indicator(0, 0, 0, 20) is None


def test_page_indicator_counts_rows_and_pages():
    assert page_indicator(0, 20, 133, 20) == "rows 1-20 of 133 · page 1 of 7"
    assert page_indicator(20, 20, 133, 20) == "rows 21-40 of 133 · page 2 of 7"
    assert page_indicator(120, 13, 133, 20) == "rows 121-133 of 133 · page 7 of 7"
    assert page_indicator(20, 5, 25, 20, unit="items") == "items 21-25 of 25 · page 2 of 2"


def test_effective_limit_human_default_json_untouched():
    assert effective_limit(None, json_mode=False) == DEFAULT_PAGE_ROWS
    assert effective_limit(None, json_mode=True) is None  # --json: raw request
    assert effective_limit(5, json_mode=False) == 5  # explicit --limit wins
    assert effective_limit(5, json_mode=True) == 5


# ---- CursorList window mode (full data in memory) ---------------------------


def test_build_windows_to_page_size():
    out = _text(_list(45)._build())
    assert "row 00" in out and "row 19" in out
    assert "row 20" not in out  # window ends at page_size


def test_window_follows_cursor_across_pages():
    lst = _list(45)
    lst.set_cursor(20)  # j past the boundary lands here
    out = _text(lst._build())
    assert "row 20" in out and "row 39" in out
    assert "row 19" not in out and "row 40" not in out


def test_cursor_restore_lands_on_its_page():
    lst = _list(45)
    lst.set_cursor(lst.index_of("id33"))  # the _restore_key pattern after a write
    assert "row 33" in _text(lst._build())
    assert lst.page_status == "rows 21-40 of 45 · page 2 of 3"


def test_action_page_jumps_and_clamps():
    lst = _list(45)
    lst.post_message = lambda m: True
    lst.action_page(1)
    assert lst._cursor == 20
    lst.action_page(1)
    assert lst._cursor == 40
    lst.action_page(1)
    assert lst._cursor == 44  # clamped to the last row
    lst.action_page(-1)
    assert lst._cursor == 24


def test_action_page_posts_highlighted_in_window_mode():
    lst = _list(45)
    captured = []
    lst.post_message = captured.append
    lst.action_page(1)
    assert len(captured) == 1 and isinstance(captured[0], CursorList.Highlighted)
    assert captured[0].key == "id20"  # two-pane screens stay in sync on page jumps


def test_single_page_hides_page_keys_and_subtitle():
    lst = _list(5)
    assert lst.page_status is None
    assert lst.check_action("page", ()) is False
    assert _list(45).check_action("page", ()) is True


# ---- CursorList fetched-page mode (page_meta, tier E) ------------------------


def test_fetched_page_posts_page_requested():
    lst = _list(20, page_meta=(0, 133))
    captured = []
    lst.post_message = captured.append
    lst.action_page(1)
    assert len(captured) == 1 and isinstance(captured[0], CursorList.PageRequested)
    assert captured[0].delta == 1 and captured[0].control is lst


def test_fetched_page_move_clamps_at_edge():
    # pick A (2026-07-11): j at the bottom row never turns the page itself.
    lst = _list(20, page_meta=(0, 133))
    captured = []
    lst.post_message = captured.append
    lst.set_cursor(19)
    lst.action_move(1)
    assert lst._cursor == 19
    assert not any(isinstance(m, CursorList.PageRequested) for m in captured)


def test_fetched_page_status_uses_global_offset():
    lst = _list(20, page_meta=(20, 133))
    assert lst.page_status == "rows 21-40 of 133 · page 2 of 7"


def test_fetched_page_single_page_hides_keys():
    lst = _list(15, page_meta=(0, 15))
    assert lst.page_status is None
    assert lst.check_action("page", ()) is False


# ---- CheckList (always window mode; rows are two physical lines) ------------


def _chk_rows(n: int) -> list[tuple]:
    return [(f"t{i}", f"txn {i:02d}", -1000 - i, "2026-07-01", "cat · #tag") for i in range(n)]


def _checklist(n: int = 25, **kwargs) -> CheckList:
    chk = CheckList(_chk_rows(n), **kwargs)
    chk._refresh = lambda: None
    return chk


def test_checklist_windows_items_not_lines():
    out = _text(_checklist(25)._build())
    assert "txn 00" in out and "txn 19" in out
    assert "txn 20" not in out  # 20 ITEMS per page (40 lines), picked 2026-07-11


def test_checklist_page_status_counts_items():
    chk = _checklist(25)
    assert chk.page_status == "items 1-20 of 25 · page 1 of 2"
    chk._cursor = 20
    assert chk.page_status == "items 21-25 of 25 · page 2 of 2"


def test_checklist_checked_state_survives_paging():
    chk = _checklist(25, checked=["t3", "t22"])
    chk.post_message = lambda m: True
    chk.action_page(1)  # display window moves; membership must not
    assert chk.checked == {"t3", "t22"}
    out = _text(chk._build())
    assert "txn 22" in out and "[x]" in out


def test_checklist_toggle_on_page_two_targets_the_right_key():
    chk = _checklist(25)
    captured = []
    chk.post_message = captured.append
    chk.action_page(1)
    chk.action_toggle()
    assert chk.checked == {"t20"}
    toggles = [m for m in captured if isinstance(m, CheckList.Toggled)]
    assert len(toggles) == 1 and toggles[0].key == "t20" and toggles[0].checked


def test_checklist_single_page_hides_page_keys():
    assert _checklist(8).check_action("page", ()) is False
    assert _checklist(25).check_action("page", ()) is True


# ---- PagedListMixin (tier-E screen plumbing) ---------------------------------


class _FakeScreen(PagedListMixin):
    def __init__(self, total=None):
        self.loads = 0
        self._page_total = total

    def _load(self):
        self.loads += 1


class _Evt:
    def __init__(self, delta):
        self.delta = delta
        self.stopped = False

    def stop(self):
        self.stopped = True


def test_mixin_fetch_kwargs_and_page_turn():
    scr = _FakeScreen(total=133)
    assert scr.page_fetch_kwargs() == {"limit": DEFAULT_PAGE_ROWS, "offset": 0}
    evt = _Evt(1)
    scr.on_cursor_list_page_requested(evt)
    assert evt.stopped and scr._page == 1 and scr.loads == 1
    assert scr.page_fetch_kwargs() == {"limit": DEFAULT_PAGE_ROWS, "offset": 20}


def test_mixin_clamps_below_zero_and_past_total():
    scr = _FakeScreen(total=15)  # one page only
    scr.on_cursor_list_page_requested(_Evt(-1))
    scr.on_cursor_list_page_requested(_Evt(1))
    assert scr._page == 0 and scr.loads == 0


def test_mixin_reset_page_for_filter_changes():
    scr = _FakeScreen(total=133)
    scr.on_cursor_list_page_requested(_Evt(1))
    scr.reset_page()
    assert scr._page == 0
