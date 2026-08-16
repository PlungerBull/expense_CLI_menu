"""Pagination — widget window/indicator/keys + the shared helpers.

Pages are min(20, what fits the terminal) since 2026-07-13 (adaptive rows,
pick A + cap 20): the tier-E wire tests at the bottom pin `run_test(size=…)`
so the expected rows-per-page is deterministic — a tall harness proves the
20 cap, a 30-line one proves the shrink, a tiny one proves the floor.

Mostly pure tests in the style of the other widget suites: `_build()` renders
through a Rich Console; action handlers run with `_refresh`/`post_message`
stubbed so no event loop is needed.
"""

import asyncio
import io

from rich.console import Console

from expense.commands._resource import DEFAULT_PAGE_ROWS, effective_limit
from expense.tui.app import ExpenseApp
from expense.tui.screens._base import PagedListMixin
from expense.tui.widgets.checklist import CheckList
from expense.tui.widgets.cursor_list import CursorList, page_indicator
from tests.unit.helpers import wait_for


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


def test_set_page_size_rewindows_around_cursor():
    """Terminal resize (adaptive rows, 2026-07-13): the window re-slices to the
    new size and keeps following the cursor."""
    lst = _list(45)
    lst.set_page_size(10)
    out = _text(lst._build())
    assert "row 00" in out and "row 09" in out and "row 10" not in out
    assert lst.page_status == "rows 1-10 of 45 · page 1 of 5"
    lst.set_cursor(23)
    assert lst.page_status == "rows 21-30 of 45 · page 3 of 5"
    lst.set_page_size(10)  # no-op: same size must not re-render
    assert lst._page_size == 10


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


def test_checklist_set_page_size_keeps_checks():
    """Resize re-slices the window; membership is a key-set over the whole
    batch, so checks survive (adaptive rows, 2026-07-13)."""
    chk = _checklist(25, checked=["t3", "t22"])
    chk.set_page_size(6)
    out = _text(chk._build())
    assert "txn 05" in out and "txn 06" not in out
    assert chk.checked == {"t3", "t22"}
    assert chk.page_status == "items 1-6 of 25 · page 1 of 5"


# ---- manage-list fetch: all pages, not the source default -------------------


def test_categories_manage_fetches_all_pages(monkeypatch):
    """The manage screens window locally, so the fetch must exhaust the
    envelope — 150 categories were silently cut at the replica's 100 before."""

    def fake_fetch(cfg, *, limit, offset, **kw):
        items = [{"id": f"c{i}"} for i in range(offset, min(offset + limit, 150))]
        return {"items": items, "total": 150, "limit": limit, "offset": offset}

    monkeypatch.setattr("expense.commands.categories_cmd.fetch_categories", fake_fetch)
    from expense.tui.screens.categories import CategoriesScreen

    assert len(CategoriesScreen().fetch_items(None)) == 150


def test_hashtags_manage_fetches_all_pages(monkeypatch):
    def fake_fetch(cfg, *, limit, offset, **kw):
        items = [{"id": f"h{i}"} for i in range(offset, min(offset + limit, 130))]
        return {"items": items, "total": 130, "limit": limit, "offset": offset}

    monkeypatch.setattr("expense.commands.hashtags_cmd.fetch_hashtags", fake_fetch)
    from expense.tui.screens.hashtags import HashtagsScreen

    assert len(HashtagsScreen().fetch_items(None)) == 130


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


def test_mixin_resize_refetches_and_reanchors():
    """Terminal shrank 19→13 rows: refetch with the new limit, the offset
    re-anchored so the old first visible row stays on the new page (pick A,
    2026-07-13). An unchanged size must not refetch."""
    scr = _FakeScreen(total=133)
    scr._page_rows = 19
    scr._page = 2  # first visible row 38
    scr.measure_list_rows = lambda: 13
    scr._viewport_resized()
    assert scr._page_rows == 13 and scr.loads == 1
    assert scr.page_offset <= 38 < scr.page_offset + 13
    scr._viewport_resized()  # same measure → no spurious refetch
    assert scr.loads == 1


def test_fetch_page_body_snaps_back_when_page_vanishes():
    """Rows shrank under us (e.g. a delete emptied the last page): the mixin
    snaps to the last real page and refetches once."""
    scr = _FakeScreen()
    scr._page = 2  # offset 40, but only 21 rows exist now
    fetched = []

    def fetch(pkw):
        fetched.append(dict(pkw))
        offset = pkw["offset"]
        items = [{"id": i} for i in range(offset, min(offset + 20, 21))]
        return {"items": items, "total": 21, "limit": pkw["limit"], "offset": offset}

    body = scr.fetch_page_body(fetch)
    assert scr._page == 1 and scr._page_total == 21
    assert fetched == [{"limit": 20, "offset": 40}, {"limit": 20, "offset": 20}]
    assert [it["id"] for it in body["items"]] == [20]


# ---- tier-E screens: real limit/offset on the wire ---------------------------


def _patch_transactions(monkeypatch) -> list:
    """133 fake transactions behind fetch_transactions; returns the calls log."""
    import expense.tui.screens.transactions as tx_mod

    calls = []

    def fake_fetch(cfg, *, limit=None, offset=None, **kw):
        calls.append((limit, offset))
        items = [
            {"id": f"t{i}", "title": f"Txn {i}", "amount_cents": -100 - i, "date": "2026-07-01"}
            for i in range(offset, min(offset + limit, 133))
        ]
        return {"items": items, "total": 133, "limit": limit, "offset": offset}

    monkeypatch.setattr("expense.commands.transactions_cmd.fetch_transactions", fake_fetch)
    monkeypatch.setattr(tx_mod, "load_account_name_map", lambda: {})
    monkeypatch.setattr(tx_mod, "load_category_name_map", lambda: {})
    monkeypatch.setattr(tx_mod, "load_hashtag_name_map", lambda: {})
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())
    return calls


def _drive_transactions(size: tuple[int, int], calls: list, checks) -> None:
    """Push a TransactionsScreen in a `size` harness and run `checks(pilot, screen)`."""

    async def scenario():
        from expense.tui.screens.transactions import TransactionsScreen

        app = ExpenseApp()
        async with app.run_test(size=size) as pilot:
            screen = TransactionsScreen()
            await app.push_screen(screen)
            await wait_for(
                pilot,
                lambda: screen.query(CursorList) and not screen.query("#content LoadingIndicator"),
            )
            await checks(pilot, screen)

    asyncio.run(scenario())


def test_transactions_screen_pages_on_the_wire(monkeypatch):
    """A tall terminal caps at 20 (pick: cap 20, 2026-07-13): loads with
    limit=20&offset=0; pgdn refetches offset=20 (picks A+B, 2026-07-11)."""
    calls = _patch_transactions(monkeypatch)

    async def checks(pilot, screen):
        assert calls == [(20, 0)]
        assert screen.query(CursorList).first().page_status == "rows 1-20 of 133 · page 1 of 7"
        await pilot.press("pagedown")
        await wait_for(
            pilot,
            lambda: (
                screen.query(CursorList)
                and screen.query(CursorList).first().page_status
                == "rows 21-40 of 133 · page 2 of 7"
            ),
        )
        assert calls[-1] == (20, 20)

    # content 28 lines → 24 rows fit → capped at the 20 standard
    _drive_transactions((120, 35), calls, checks)


def test_transactions_screen_adapts_rows_to_short_terminal(monkeypatch):
    """A 30-line terminal fits 19 rows (chrome takes 11): the page IS the
    screenful — limit=19 on the wire, 19-row pages in the indicator (pick A,
    2026-07-13). This is the 2026-07-12 clipped-panel screenshot, fixed."""
    calls = _patch_transactions(monkeypatch)

    async def checks(pilot, screen):
        assert calls == [(19, 0)]
        assert screen.page_rows == 19
        assert screen.query(CursorList).first().page_status == "rows 1-19 of 133 · page 1 of 7"
        await pilot.press("pagedown")
        await wait_for(
            pilot,
            lambda: (
                screen.query(CursorList)
                and screen.query(CursorList).first().page_status
                == "rows 20-38 of 133 · page 2 of 7"
            ),
        )
        assert calls[-1] == (19, 19)

    _drive_transactions((120, 30), calls, checks)


def test_transactions_screen_floors_at_five_rows(monkeypatch):
    """Below a ~16-line terminal the fit goes under 5; the floor holds (the
    panel clips there — pre-2026-07-13 behavior, terminal was never usable)."""
    calls = _patch_transactions(monkeypatch)

    async def checks(pilot, screen):
        assert calls == [(5, 0)]

    _drive_transactions((120, 14), calls, checks)


def test_inbox_filter_change_resets_page(monkeypatch):
    """`f` invalidates the old offset: page 2 of `all` must not leak into `ready`."""
    import expense.tui.screens.inbox as inbox_mod

    calls = []

    def fake_inbox(cfg, *, ready=False, overdue=False, limit=None, offset=None, **kw):
        # Every load also issues an unpaged ready=True probe (the `rdy` glyph).
        # It carries no offset — that is how `_filter_calls` tells the probe
        # apart from the paged filter fetch this test is about.
        calls.append({"ready": ready, "offset": offset})
        items = [{"id": f"d{i}", "title": f"Draft {i}", "status": 1} for i in range(limit or 20)]
        return {"items": items, "total": 60, "limit": limit, "offset": offset}

    monkeypatch.setattr("expense.commands.inbox_cmd.fetch_inbox", fake_inbox)
    monkeypatch.setattr(inbox_mod, "load_account_name_map", lambda: {})
    monkeypatch.setattr(inbox_mod, "load_category_name_map", lambda: {})
    monkeypatch.setattr("expense.config.ensure_loaded", lambda: object())

    async def scenario():
        from expense.tui.screens.inbox import InboxScreen

        def _filter_calls():
            return [c for c in calls if c["offset"] is not None]

        app = ExpenseApp()
        # 35 lines: inbox chrome + legend take 13, so the 20 cap still applies
        async with app.run_test(size=(120, 35)) as pilot:
            screen = InboxScreen()
            await app.push_screen(screen)
            await wait_for(
                pilot,
                lambda: screen.query(CursorList) and not screen.query("#content LoadingIndicator"),
            )
            await pilot.press("pagedown")
            await wait_for(pilot, lambda: any(c["offset"] == 20 for c in _filter_calls()))
            await pilot.press("f")  # all → ready; offset must reset
            await wait_for(pilot, lambda: any(c["ready"] for c in _filter_calls()))
            ready_call = next(c for c in _filter_calls() if c["ready"])
            assert ready_call["offset"] == 0 and screen._page == 0

    asyncio.run(scenario())
