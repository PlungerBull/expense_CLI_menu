# TUI notes from the 2026-08-06 cache deletion — handoff for the TUI developer

The local SQLite replica and the engine's `GET /v1/sync` were deleted on 2026-08-06
(decision record: [decisions.md](decisions.md) "Delete the local replica"; engine side:
engine repo `docs/rework/WP4`). The TUI now reads live against the loopback engine on
every fetch. This file collects everything TUI-specific that changed, plus the
observations that surfaced while reworking the TUI test suite — the things you would
otherwise rediscover the hard way. It is a snapshot, not a living spec: once you have
absorbed it (or acted on the "worth considering" section), it can be deleted.

## What changed in `expense/tui/`

- **`ExpenseApp(verbose=...)` only.** The `no_cache` constructor param and the
  `_no_cache` attribute are gone; there is no stateless-vs-cache mode anywhere.
- **`screen_fetch_kwargs(app)` returns `{"verbose": app._verbose}`** — the
  `no_cache` / `cold_start_notice` / `notice_stream` plumbing is deleted. Screens pass
  it into the shared `fetch_*` helpers unchanged.
- **`EngineWriteMixin.run_write()` lost its `refresh=` parameter.** A write is now just
  the HTTP verb: no post-write replica refresh, no `_drain_refresh`, no
  `_notify_stale_replica` ("Saved — cache not refreshed" toast), no coalesced
  drain-time sync. The FIFO queue, one-in-flight serialization, and
  error-drops-the-queued-remainder semantics are unchanged.
- **`SectionScreen._load` no longer shows a "Syncing your data — first run…" note** —
  `_will_cold_start` and `_set_loading` are deleted. The only loading state is the
  spinner. There is no first-run penalty anymore; every load costs the same.
- **`SyncScreen` is gone** (with `_delta_table`, `_short_token`, `_cache_status`,
  `_read_cache_state`): removed from `system.py`, the home menu, and `_SCREENS`.
- **`ConfigScreen` shows only engine url / token / main currency** — the "client id"
  and "cache" rows are deleted (`client_id` no longer exists in the config model).
- **`ActivityScreen` resolves resource names in `fetch()`, not `build()`.**
  `activity_cmd.activity_display_cells(item, client)` now requires an open
  `ExpenseClient` because resolution is a live per-row engine read. `fetch()` opens one
  client for the whole page, returns `{"rows": [(key, cells), ...], "by_id": {...}}`,
  and `build()`/`on_cursor_list_selected` consume the precomputed cells
  (`self._cells`). **The invariant to preserve: `build()` runs on the UI thread and
  must never do HTTP.**
- **`InboxScreen`'s ready-ids probe runs on every load.** It was gated on
  `not self.app._no_cache`; the gate is gone. Every inbox load is now two
  `fetch_inbox` calls (the page + the unpaged `ready=True` probe) plus two name maps.

## Behavior notes (not bugs — things to know)

- **Name maps are live HTTP now.** `load_account_name_map` /
  `load_category_name_map` / `load_hashtag_name_map` each load config, open their own
  client, and page through the reference list (`limit=200`); they return `{}` on ANY
  failure, and renderers degrade to 8-char short ids. Verified 2026-08-06: every TUI
  call site is inside a worker thread (`fetch()` methods, `_load_txns`) — keep it that
  way when adding screens.
- **The reconciliation error path still "resyncs", just live.** A failed checklist
  toggle drops the queued intents and `_assign_failed` → `_load_txns()` re-fetches from
  the engine instead of running a replica delta. Same UX contract, different plumbing.
- **The keep-or-drop call on the toggle-burst test:** the drain-refresh half of
  `test_toggle_burst_syncs_replica_once_on_drain` died with the machinery; the
  surviving half was renamed `test_toggle_burst_puts_every_toggle_in_order`
  (`test_tui_reconcile_detail.py`) and pins that a same-row re-toggle round-trips in
  exact PUT order. Deliberately kept — it is real, otherwise-uncovered coverage.

## Test-infrastructure observations (from the suite rework)

- **Screens' tests monkeypatch `load_*_name_map` at the screen module**
  (`expense.tui.screens.X.load_account_name_map`), not at `_resource` — which is why
  the live-HTTP rewrite of those helpers was invisible to the TUI tests. Follow that
  pattern for new screens when the test's point is name display; use the short-id
  fallback when it isn't.
- **`fake_client` (conftest) patches the lazy-import seams only** —
  `expense.http.ExpenseClient` and `expense.config.ensure_loaded`. It no longer
  patches any refresh hook, and `helpers.FakeClient` has no `.refreshes` counter;
  assert on `client.calls` / `.posts` / `.puts` ordering instead.
- **`test_command_surface.py` gives no signal when a command disappears.** The Typer
  walker only checks commands it finds, so a deleted command silently drops out
  (`("sync",)` sat as a dead `READ_COMMAND_LEAVES` entry until removed). The only
  backstops are the total-count floor (>= 50) and the destructive count (== 8). If you
  add or remove TUI-reachable commands, adjust those counts deliberately.
- **The inbox paging test had a real behavior change under it:** because the ready-ids
  probe now runs on every load, `test_inbox_filter_change_resets_page` must filter to
  calls that carry an `offset` before selecting the ready one — the unpaged probe
  (offset `None`) otherwise shadows the paged fetch. The probe is documented in that
  test's fake.
- `test_config_screen_shows_only_the_engine_connection` (`test_tui_system.py`) pins
  the slimmed ConfigScreen — it asserts "client id"/"cache" rows are absent, and was
  mutation-checked (inverting the assertion fails).

## Worth considering later (not done, deliberately)

- **Client sharing per screen load.** A screen load can open several short-lived
  clients (e.g. inbox: 2 fetches + 2 name maps = 4). Harmless on loopback
  (sub-millisecond), but if you ever want to tidy it, thread one `ExpenseClient`
  through a screen's `fetch()` the way `ActivityScreen` already does.
- **The inbox ready-probe is unpaged.** It fetches every ready item to badge the
  visible page. Fine at personal scale; if inbox rows ever number in the thousands,
  badge from the paged body instead (the engine exposes `ready` as a filter, not a
  per-row field — that would be the engine ask).
- **Name-map failure is silent by design** (short ids, no toast). If a TUI user ever
  reports "my tables show hex ids", the likely cause is the engine rejecting the
  reference-list reads (auth/config), not data loss.
