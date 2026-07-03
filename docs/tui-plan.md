# Interactive TUI — Implementation Plan

> Status: **in progress (Step 10)** — Phases 0 & 1 shipped, Phase 2 (write flows)
> under way; Phase 3 not started. Entry command is **`expense world`**. This TUI
> **replaced the questionary `expense menu`**, which was **deleted at roadmap Step 10.X
> (2026-07-02)** — `expense/menu/`, its tests, the Typer command, and the `questionary`
> dep are gone (see §10). Builds a menu-driven, retained-mode terminal
> app on top of the existing engine-integration layer. Mockups: [docs/mockups/](mockups/)
> (the `expense-world-*.html` set). Expand/collapse = interactive `▼/▶` tree with
> arrow-key navigation. Theme = swappable token set, **neutral by default**.
>
> **What's wired (per [expense/tui/screens/home.py](../expense/tui/screens/home.py)):**
> Outstanding Amounts, Log a transaction (quick-add + transfer), Inbox, Transactions,
> Reconciliations, Accounts, Categories, Hashtags, Config, Auth & profile, and the
> System reads (Sync · Activity · Rates).
> **Still stubbed (`"soon"`):** Monthly report.

## 1. Goal & shape

A persistent terminal app — `expense world` — that opens to a **header + menu**,
and renders a dedicated **interface per section** (browse, create, edit, confirm),
with arrow-key navigation, an expandable category tree, and contextual key hints.

The flat commands (`expense log`, `expense dashboard`, …) keep working untouched — they
stay the canonical interface. The TUI **replaced** the questionary `expense menu`, which
was deleted at roadmap Step 10.X (2026-07-02) — the two ran in parallel only until the
decision to retire the menu. The TUI is a new *client* of the same data/command layer —
it implements **zero** business logic, per the repo's thin-wrapper rule. The engine stays
the single source of truth.

Built with **Textual** (Python, by the Rich authors — the direct analog to the Ink
stack Claude Code uses).

## 2. Why this is mostly presentation work

The hard, finance-critical layer already exists and is reused as-is:

| Already built (reused) | New (the TUI) |
|---|---|
| Engine HTTP client, idempotency, error envelope (`expense/http.py`) | Textual app shell, screen stack, key bindings |
| SQLite replica, `ensure_synced`, name maps (`expense/cache/`) | Header / breadcrumb / keybar widgets |
| Data shaping — the dicts renderers consume | List, tree, chip, and form screens |
| Business rules (engine-side) + 422 envelope | Loading / empty / error states |
| Command implementations & fetch/print split (`expense/commands/`) | Neutral theme token file |
| `format_cents`, hashtag/account/category resolution, ready-predicate | Confirm modals, navigation |

## 3. Architecture

The `expense/tui/` package (which replaced the now-deleted `expense/menu/`):

```
expense/tui/
  app.py            # ExpenseApp(App): screen stack, global bindings, theme, worker helper
  theme.tcss        # Textual CSS — NEUTRAL tokens (swap file to retheme)
  widgets/
    header.py       # full banner (home) + slim breadcrumb (sections)
    keybar.py       # contextual footer key hints (Textual Footer)
    table.py        # DataTable wrapper: glyph cols, right-aligned money, focus
    tree.py         # category→hashtag expand/collapse tree
    form.py         # reusable form: fields, validation, tri-state, conditional rows
    swatch.py, status.py
  screens/
    home.py         # header + section menu
    outstanding.py  # balances + people + category TREE + totals
    inbox.py        transactions.py  accounts.py  categories.py  hashtags.py
    reconcile.py    reports.py  system.py        # config/auth/sync/activity/rates
    forms/          # transaction_form, small_form (account/category/hashtag), reconcile_form
    modals.py       # confirm (promote/delete/archive/…), record detail
```

**The one enabling refactor — "fetch / print" split.** Some commands fetch *and*
print in one function (e.g. `reports_cmd.run_single_month` GETs then `typer.echo`s).
We extract a pure `fetch_*(cfg, …) -> dict` from each, leaving the typer command and
the TUI both calling it. `--json` mode already proves the data separates cleanly; this
just formalizes it. **No logic is duplicated** — the TUI imports `fetch_*`, never
reimplements it.

**Async / workers.** Textual runs on asyncio; the engine client is synchronous. We
keep the client as-is and call it inside a Textual worker (`@work(thread=True)`) via a
single helper so the UI never blocks. A standard pattern:
`self.run_engine(lambda: reports_cmd.fetch_single_month(...), on_done=self.populate)`.

## 4. Theming — neutral, swappable

All color lives in `theme.tcss` as Textual CSS variables; **no hardcoded colors in
widgets**. Default is a **neutral** palette (greyscale surfaces + one restrained
accent for focus/selection, plus a positive/negative pair for amounts). Retheming
(amber, a brand palette, light mode) is a one-file swap the designer can own. Textual
auto-degrades on `NO_COLOR` / non-truecolor terminals.

Tokens: `$surface $panel $text $text-muted $accent $selection $border $positive $negative`.

## 5. Phased delivery

Estimates assume one dev comfortable with Python; **add ~1 week if new to Textual**.

### Phase 0 — Walking skeleton · **3–5 days** · ✅ shipped
- `expense world` launches the Textual app; neutral theme loads.
- Header banner + **home menu** (real section list + live status line), arrow-key nav,
  footer keybar, quit.
- **One real read view wired to live data: Outstanding Amounts** (start flat, then add
  the tree) via the worker helper, reusing `ensure_synced`.
- **Exit criteria:** launch → navigate the menu → see real current-month data in your
  terminal. De-risks Textual + async + the data-reuse architecture.

### Phase 1 — Read views · **1–2 weeks** · ✅ shipped
> Note: Reports, Activity log, and Exchange rates list screens slipped from Phase 1 to
> Phase 2. Activity log and Exchange rates shipped there (as the System reads); only
> the **Monthly report** screen remains a `"soon"` stub on the home menu.
- Apply the fetch/print split to the resources in scope.
- List screens (Textual `DataTable`): **Inbox, Transactions, Accounts, Categories,
  Hashtags (chips), Reports (monthly), Activity log, Exchange rates** — filters,
  pagination, glyph columns, name resolution (all reused).
- **Outstanding Amounts: interactive `▼/▶` tree** with arrow-key navigation (the
  preferred expand/collapse), fed by the existing category→`hashtag_breakdown` data.
- Record **detail modal** (view one row). Loading / empty / error states; status bar.
- **Exit criteria:** every read surface is browsable in the TUI.

### Phase 2 — Write flows · **1–2 weeks** · 🔨 in progress
> **Shipped:** Log/quick-add + transfer, edit transactions + inbox drafts, create forms
> (account/category/hashtag), full Reconciliations screen (assign/complete/revert/delete +
> account-first browse + reorder), Config, Auth & profile, and the **Sync · Activity ·
> Rates** system-read screens.
> **Remaining before parity:** the **Monthly report** screen (still a `"soon"` stub on the
> home menu).
- **Confirm modal** (one component) for promote / delete / archive / restore /
  complete / revert / sync — reuses idempotency + error envelope.
- **The transaction form** (Log / Inbox-add / Transaction-edit — same fields): required
  fields, signed-amount validation, **tri-state cleared**, hashtag multi-select,
  **conditional transfer sub-flow** (opposite-sign rule), inline 422 surfacing.
- **Small forms** (reuse the form component): account, category, hashtag create/edit.
- **Reconciliation** create/edit form; reorder — shell out to the existing `$EDITOR`
  flow first, native reorder later.
- **Config / Auth & profile** forms. Post-write refresh reuses `refresh_after_write`.
- **Exit criteria:** create/edit/act parity with the flat command surface.

### Phase 3 — Polish & hardening · **~1 week** · ⬜ not started
- Designer's theme tokens dropped in; light/dark; `NO_COLOR` paths.
- Keybinding consistency, `?` help overlay, Textual command palette.
- Async edge cases (slow net, offline, cold-start notice shown in-app), spinners.
- Skeleton/empty/error states everywhere.
- **Textual pilot tests** for navigation + key flows; existing CLI suite stays green.
- Update `docs/roadmap.md`, `CLAUDE.md`; user-facing TUI notes.
- **Exit criteria:** shippable; feature-complete vs the flat command surface.

### Phase 4 (optional, later) — Live niceties
Auto-refresh / watch mode, search-as-you-type, mouse, richer dashboards.

## 6. Effort summary

| | Scope | Effort |
|---|---|---|
| **MVP** | Phase 0 + most read views + the transaction form | **~2 weeks** |
| **Complete & polished** | Phases 0–3 | **~6–8 weeks** |

Per-section difficulty: menus & lists *easy*; the tree & the transaction form
*moderate*; **Reconciliation reorder** the one outlier (the `$EDITOR` flow).

## 7. Risks & mitigations

- **Textual learning curve** → start with the skeleton; lean on built-in widgets.
- **Async correctness** → one `run_engine` worker helper; never touch the engine on the
  UI thread.
- **Logic duplication** → the fetch/print split is the guardrail; TUI imports `fetch_*`.
- **Reconcile `$EDITOR` reorder** → shell out to the existing flow first; native later.
- **Scope creep (live features)** → deferred to Phase 4.
- **Theming churn** → tokens file, neutral default, zero hardcoded colors.

## 8. Definition of done

- Parity checklist vs the flat command surface (every engine endpoint reachable in the TUI).
- Pilot smoke tests + the full existing suite green.
- Degrades gracefully on `NO_COLOR` / non-TTY / tiny terminals.
- **`expense menu` (`expense/menu/`) removed** — done at Step 10.X (2026-07-02): its
  screens, tests, the Typer command, and the now-unused `questionary` dep are all gone.

## 9. Decisions

**Resolved:**

1. **Entry command** — ✅ **`expense world`**. (Wired in [expense/tui/app.py](../expense/tui/app.py) / `__main__.py`.)
2. **Coexistence** — ✅ **The TUI replaced `expense menu`, now deleted** (roadmap Step 10.X,
   2026-07-02). They shipped in parallel only until the menu was retired. The flat
   commands (`expense log`, …) stay permanently as the canonical contract-validator interface.
4. **Reconcile reorder** — ✅ **shell out to `$EDITOR`** for v1 (reuses `expense/_editor.py`);
   native reorder deferred.

**Still open:**

3. **Neutral theme** — monochrome + single accent, dark default? Designer to finalize the
   `theme.tcss` tokens; plan assumes dark-neutral.
5. **Minimum terminal size** — fallback/refuse below e.g. 80×24?
