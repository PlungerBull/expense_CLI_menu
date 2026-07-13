# Decision record

Why the big calls went the way they did — **including the alternatives that were rejected**, which is the part that otherwise lives only in session history and evaporates. A future maintainer (human or AI) with nothing but this repo should be able to answer "why is it like this?" without re-deriving or re-litigating.

Rules for this file:

- **One home per fact.** If a decision's rationale already lives in another doc, the index links there — no copies. Full entries below exist only for decisions whose *why* had no home.
- **Absolute dates, always.** "Recently" means nothing in two years.
- New entry template: `## <decision> (<date>)` → **Context** / **Decision** / **Rejected** — three short paragraphs, link the artifacts.

## Index

| Decision | Decided | The why lives in |
|---|---|---|
| CLI is a thin wrapper / contract validator for the multi-client engine | project inception | [CLAUDE.md](../CLAUDE.md) "Product scope and role" |
| Server-first writes, no offline queue (queue is iOS-only) | project inception | [CLAUDE.md](../CLAUDE.md) "Tech stack" · [cli-runtime.md](cli-runtime.md) "Write semantics" |
| Cache-by-default, stateless as escape hatch | Step 7b | [cli-runtime.md](cli-runtime.md) "Overview" (implements engine §3b) |
| PAT auth (Option B: `ewe_pat_` prefix, JWT fallthrough) | 2026-04-23 | [cli-spec.md](cli-spec.md) "Auth model" |
| Public GitHub repo → secrets never enter the repo | project inception | [CLAUDE.md](../CLAUDE.md) "Config isolation" |
| Sanctioned deviations from the principles (3 items) | 2026-07 (backlog 2.1/2.6) | [cli-spec.md](cli-spec.md) "Sanctioned exceptions" |
| Sign is always literal — no default-to-expense magic | 2026-04-25 | full entry below |
| Dual-UX strategy (flat + TUI + quick-add) | 2026-04-25 | full entry below |
| Questionary menu deleted ahead of its gate | 2026-07-02 | full entry below |
| Mockup-first, and showing ≠ approval | 2026-05-24 (hardened) | full entry below |
| polish-backlog.md holds only open work | 2026-07-06 | full entry below |
| Manage detail: system categories are editable, not immutable | 2026-07-07 | full entry below |
| Monthly report TUI is a sliding 4-month grid, not a single-month view | 2026-07-08 | full entry below |
| `SyncContractError` + exit code 5 for /sync contract violations | 2026-07-08 | full entry below |
| TUI writes: FIFO queue in EngineWriteMixin, error drops the queue | 2026-07-08 | full entry below |
| Connection errors → exit code 6, off the click-usage collision on 2 | 2026-07-10 | full entry below |
| TUI paints the terminal's own background (ANSI mode) — one surface, no seam | 2026-07-11 | full entry below |
| Archive is a prompt-free toggle; Manage record detail deleted | 2026-07-11 | full entry below |
| Every data table pages at 20 rows (CLI human mode + TUI), two-tier design | 2026-07-11 | full entry below |
| TUI is keyboard-only — mouse disabled via `run(mouse=False)` | 2026-07-12 | full entry below |

## Sign is always literal — no default-to-expense magic (2026-04-25)

**Context.** The engine's `debit_as_negative` convention (negative = expense, positive = income) is central to how the whole system reasons about money. While designing the capture UX (structured `log`, future quick-add parser), the tempting default existed: treat a bare unsigned amount as an expense, since most entries are expenses.

**Decision.** The sign is always explicit, end-to-end, in every UX layer: `$20` = income, `-$20` = expense. An unsigned amount where the sign is ambiguous gets a prompt or an error — never a guess. The rule surfaces in [cli-spec.md](cli-spec.md) "Principles" and the quick-add entry under "To Be Defined". The **single sanctioned exception** is the TUI transfer "To amount" field (magnitude entry, sign auto-set opposite the Amount leg per the engine's zero-sum rule, computed value visible before submit) — see [cli-spec.md](cli-spec.md) "Sanctioned exceptions", backlog 2.1.

**Rejected.** Default-to-expense for quick-add, offered explicitly and declined by the user. Reasons: a magic default is hidden behavior that diverges from what the engine actually stores; it confuses the user about what was recorded; and it complicates the future parser with intent inference. When a new command or parser takes an amount, require the sign or reject the input.

## Dual-UX strategy — flat commands + TUI + quick-add (2026-04-25)

**Context.** For a multi-command CLI, discoverability friction is real for infrequent management tasks ("which flag archives an account?"), but for daily capture, flat commands beat any menu (`expense log -20 …` beats walking six prompts). One interaction mode can't serve both.

**Decision.** Three surfaces over one implementation, each matched to an actual need: (1) **flat commands** — canonical, scriptable, the contract-validator surface, always the source of truth for behavior; (2) an **interactive surface** for management and first-time discovery — originally the questionary `expense menu`, replaced by the Textual TUI `expense world` (see next entry); (3) a **quick-add parser** for daily capture (post-Step-9, [roadmap.md](roadmap.md) "Post-Step-9 ergonomics"). Every interactive action delegates to the shared fetch/write layer — no parallel logic. `expense` with no args keeps printing group help; the interactive surface is opt-in.

**Rejected.** Interactive-first UX (slower for capture, unscriptable); folding flat commands under the interactive surface (kills scripting, testing, and the parser's dispatch target); building the interactive layer before Step 9 (UI over a moving action surface is wasted work). This mirrors Todoist's architecture — quick-add bar for capture, menus for everything else — per the lessons docs in the engine repo.

## Questionary menu deleted ahead of its gate (2026-07-02, Step 10.X)

**Context.** The questionary `expense menu` shipped at Step 9.5 as the first interactive surface. The Textual TUI (`expense world`, Step 10) superseded it while still short of full parity; the original plan deleted the menu only after TUI P2+P3 completion.

**Decision.** Delete early: `expense/menu/`, its test suite, the Typer command, and the `questionary` dependency all removed at Step 10.X ([roadmap.md](roadmap.md)). Nothing was lost because the flat commands are the complete contract-validator surface — the menu was a convenience layer, not a capability. Keeping two interactive surfaces alive meant maintaining every new feature twice for no product value, since the TUI was already the committed direction. <!-- [user to confirm: the double-maintenance motivation matches your recollection of the 2026-07-02 call] -->

**Rejected.** Waiting for full TUI parity (pays double maintenance during the overlap); keeping the menu as a fallback (two half-loved surfaces instead of one good one).

## Mockup-first, and showing ≠ approval (hardened 2026-05-24)

**Context.** The rule "mock every screen before building it" existed from the Step 9.5 table work. On 2026-05-24 it grew teeth: three Reports-view mockups were produced for the user to choose between, and before a pick was made, a vague follow-up ("where were we?") was taken as a go-ahead — Option A got implemented unilaterally. The user expected the render to *be* the deliverable; implementation needed its own green light.

**Decision.** Every user-facing view or table change starts with an HTML mockup in [mockups/](mockups/), **and presenting mockups is never authorization** — implementation waits for an explicit pick, even in auto-accept mode, even when a follow-up sounds like consent. A prior session's approval is not a standing license: the user re-reads the mockup each time a screen is picked up, because specific observations only come from re-reading. Full rule in [CLAUDE.md](../CLAUDE.md) "Mock every screen before building it"; the CLI-table variant (propose columns + sign-off) in [cli-spec.md](cli-spec.md) "Output conventions".

**Rejected.** Treating an earlier approval as durable (screens drift, and so do the user's observations); inferring layout or columns from the engine response shape (scannability is the user's product judgment, not a derivable fact).

## polish-backlog.md holds only open work (2026-07-06)

**Context.** When the 2026-07-02 quality review was fully worked off, the choice was append the new review below the closed one, or replace.

**Decision.** Replace. A fully-closed review's content is deleted; the file header notes the commit holding the last full copy (the 2026-07-02 review lives at `2d42482`). The backlog is a working list, not an archive — git history is the archive ("If the previous data is finished, we might be better deleting the information", 2026-07-06).

**Rejected.** Append-and-keep (the file becomes noise; closed items get re-read forever); a separate archive doc (a second home for facts git already keeps).

## Manage detail: system categories are editable, not immutable (2026-07-07)

**Context.** Building the Manage edit flow (`enter`→detail→`e` edit / `a` archive; see [tui-plan.md](tui-plan.md) Phase 2), the question was how to treat system categories (`@Transfer`, `@Debt`). The initial instinct — and a first recommendation — was to make them fully read-only in the TUI (hide `e` and `a`), assuming "system = untouchable." The engine's actual contract is the opposite on the axis that matters.

**Decision.** The TUI **offers `e` (rename/recolor) on system categories** and **hides only `a` (archive)**. Rationale, from the engine spec: system categories are resolved by an immutable `system_key` column, never by name, so renaming is pipeline-safe and explicitly allowed (`PUT` has no `is_system` guard — engine-spec §Categories) — the `system_key` machinery was built specifically to make renaming safe, including localization (`@Transfer` → `@Transferencia`). Archive and delete, by contrast, change availability and would break the transfer pipeline, so the engine `403`s them. Hiding `a` therefore *reflects* a guaranteed-`403`; offering `e` reflects a guaranteed success. Implemented via `ResourceListScreen.check_action` in [_base.py](../expense/tui/screens/_base.py) (originally on the record detail's `ManageDetailScreen`, which was deleted 2026-07-11 — see the archive-toggle entry below; the system-category rule carried over unchanged).

**Rejected.** (1) **Hide `e` on system categories** (make them TUI-immutable) — rejected as client-invented business logic: the engine permits the rename, so a client silently forbidding it is exactly the split-brain the thin-wrapper rule exists to prevent. (2) **Ask the engine to `403` `PUT` on system categories** "for consistency" with archive/delete — rejected: that's a *false* consistency (existence vs. presentation are different axes) and would throw away the deliberately-engineered rename/localization capability. The engine is internally consistent as-is; only the CLI's `_SYSTEM_HINT` copy ("cannot be modified") was imprecise and was corrected. Distinction credited to the user's review of the first recommendation.

## Monthly report TUI is a sliding 4-month grid, not a single-month view (2026-07-08)

**Context.** The Monthly report screen was the last Phase-2 stub ([tui-plan.md](tui-plan.md)). The first mockup proposed a single-month view (categories + hashtag breakdown + totals, `[`/`]` to change month) — a natural mirror of the flat `reports monthly --date`. The user rejected it on review: a single month of category spend is what **Outstanding Amounts already shows**; a second screen rendering the same shape one navigation-step away adds no information, just a month picker.

**Decision.** The screen is a **4-month grid** — categories as rows, the last four months as columns (window ends at the current month), home-currency cells, net-only footer; `[`/`]` slide the window one month older/newer, no clamp. Mockup **Option A** (picked 2026-07-08): rows expand `▼/▶` into their hashtag combos across all four columns, reusing the Outstanding tree keymap; collapsed by default so the grid first reads like the CLI range table. One engine call per window (`GET /v1/reports/monthly` with from/to via the shared `fetch_range`); the grid merge (`build_range_grid`) is shared with the flat range renderer. Mockup: [mockups/expense-world-monthly-report.html](mockups/expense-world-monthly-report.html).

**Rejected.** (1) **Single-month view** — duplicates Outstanding Amounts; the report's value over the dashboard is the *time axis*, so the screen must show it. (2) **Single-month + a range-view toggle** — two layouts to build and maintain when the sliding window already covers the trend need with one. (3) **`←`/`→` for month navigation** — collides with the tree's expand/collapse bindings, hence `[`/`]`. (4) **Option B (flat, always-expanded grid)** — offered in the mockup, not picked; long months can't fold their hashtag noise.

## `SyncContractError` + exit code 5 for /sync contract violations (2026-07-08)

**Context.** Two cache-sync guards raised bare `RuntimeError` (backlog 6.1b): `_derive_user_id` when a /sync response has null settings and every resource empty (reachable by installing a PAT and running any list command before `auth bootstrap`), and `_fetch` when the engine omits `sync_token`. `handle_errors` catches only the domain errors, so both escaped as raw tracebacks — the exact freshman path the CLI exists to smooth.

**Decision.** A new domain error, `SyncContractError` ("the engine responded but violated its own contract"), registered in the `_ENVELOPE_ERRORS` table in [expense/errors.py](../expense/errors.py) with envelope code `SYNC_CONTRACT` and **exit code 5** — a new family alongside 1 (engine rejected the request), 2 (connection), 3 (config), 4 (cache). The user-facing message carries the remedy ("run 'expense auth bootstrap' first"), so the TUI toast inherits the hint via `format_error`'s fallback.

**Rejected.** Exit 1 (folding it into "engine error" hides that the *contract* broke, not a request — scripts couldn't tell a broken engine build from a validation error); exit 2 (already double-booked: connection errors share it with click's usage errors, then an open nit — since closed by moving connection to exit 6, see below — and adding a third meaning would have made it worse); keeping `RuntimeError` and catching it broadly in `handle_errors` (would swallow genuine client bugs, which must keep crashing loudly).

## TUI writes: FIFO queue in EngineWriteMixin, error drops the queue (2026-07-08)

**Context.** `run_write` was a thread worker with `exclusive=True`, but thread cancellation is cooperative and never checked — rapid repeated writes (double-pressed archive, fast checklist toggles) fired overlapping, unordered PUTs. The checklist screen had fixed this locally with its own queue + inflight flag (backlog 3.2); every other screen still raced (backlog 6.4b), and every write ran its own `refresh_after_write` delta — a 15–30-toggle reconciliation burst meant 2 engine round-trips per toggle against Render (backlog 6.5a).

**Decision.** The mixin owns a per-screen FIFO: `run_write` enqueues, exactly one request is in flight, order is preserved. **A failed write drops the queued remainder** — those intents were decided against a screen state the engine just contradicted; the error callback resyncs (user decision 2026-07-08, generalizing the tested toggle behavior). `run_write(refresh=False)` coalesces the replica refresh into one delta sync when the queue drains — including after an error drain, since earlier skipped-refresh successes already changed engine state. The checklist's local queue was deleted; its serialization tests pass unchanged against the mixin.

**Rejected.** Per-screen queues à la `_pump_toggles` (N copies of the same race fix, each one edit from drift); cancelling in-flight writes on supersede (cooperative cancellation can't actually stop a thread mid-request, and aborting engine writes mid-flight is worse than finishing them — the idempotency key already covers retries); continuing the queue past a failure (later writes may depend on the failed one, and it would silently change the tested toggle-error contract).

## Connection errors get exit code 6, off the click collision on 2 (2026-07-10)

**Context.** `EngineConnectionError` mapped to exit **2** — the same code click/Typer emit for usage errors (bad flags, missing args). A script or CI run couldn't tell "engine unreachable" from "you called it wrong." The `SyncContractError` decision above had already flagged this as an open nit when it took 5 rather than overload 2.

**Decision.** Move `EngineConnectionError` to **exit code 6** in the `_ENVELOPE_ERRORS` table ([expense/errors.py](../expense/errors.py)) — one row; `render()` and `handle_errors` inherit it automatically. The family is now 1 (engine rejected) · 3 (config) · 4 (cache) · 5 (sync contract) · **6 (connection)**, with **2 left to click alone**. Same principle as the exit-5 call: a new meaning gets a fresh code, never an overloaded one.

**Rejected.** Reusing 2 with a distinguishing message (scripts branch on the code, not prose); renumbering the family so connection sits contiguous with 1–5 (churns four codes and their tests for cosmetics — appending 6 is the minimal, non-breaking move).

## TUI paints the terminal's own background — ANSI mode (2026-07-11)

**Context.** On the `expense world` home screen the user saw three stacked background shades. Investigation confirmed the app paints exactly one fill — `$background = #0e0e11` — plus the selection bar. The "third" shade is the terminal emulator's own **window padding**, drawn in the Terminal profile's background (near-black). Because `#0e0e11` is a hair lighter than the terminal's black, the app content reads as a lighter panel inside a darker frame — a seam the app can't paint over, only *match*. Mockup + rejected-alternatives render: [mockups/tui-ansi-transparent-background.html](mockups/tui-ansi-transparent-background.html).

**Decision.** Run the TUI in **ANSI mode** — `ExpenseApp` passes `ansi_color=True` ([app.py](../expense/tui/app.py)). Textual then emits the terminal's default background (SGR 49) instead of a fixed hex, so the app fill and the window padding become one continuous surface that **follows whatever dark terminal it runs in**. Scope is deliberate: **adaptive background, pinned foreground.** The theme stays non-ANSI, so every design token keeps its authored hex (net/spent red, owed green, grey selection bar, `$surface` separators, footer); only the base fill and inherited text color go through the terminal, and [app.tcss](../expense/tui/app.tcss) pins the foreground back to `$foreground` under `Screen:ansi`. The base fills (`Screen`, `#menu`) carry `ansi_default` — the id-level `#menu` rule out-specifies Textual's `Screen:ansi`, so a hardcoded fill there would just relocate the seam to the menu edge (guarded by `test_base_fills_are_terminal_transparent`). `ModalScreen:ansi` is overridden to keep the dim scrim Textual otherwise drops. This is correct on any **dark** terminal and identical to before on a near-black one; it does **not** make the app readable on a **light** terminal — the fixed muted/semantic hexes assume a dark ground. That, plus a true light theme, remains the open [tui-plan.md](tui-plan.md) light/`NO_COLOR` backlog item.

**Rejected.** *Match a fixed hex* (`background="#000000"`) — exact and one line, but pinned to a single Terminal profile; on any other terminal the frame comes back. *Do nothing / fix the terminal profile* — punts a code-owned problem onto every machine's config. *Full native-ANSI theme* (`theme.ansi=True`, semantic colors → `ansi_*`) — truly terminal-agnostic including light terminals, but throws away the tuned sign-color palette and restyles foreground/scrollbars/footer app-wide; that belongs to the dedicated light/`NO_COLOR` theme work, not a seam fix.

## Archive is a prompt-free toggle; Manage record detail deleted (2026-07-11)

**Context.** `enter` on an Accounts/Categories/Hashtags row opened a record detail (`manage_detail.py`, Option B of 2026-07-07) whose field rows repeated the list's own columns one-for-one — its only value was hosting `e` (edit) and `a` (archive). The user flagged the redundancy ("I can see everything on the previous menu") and, reviewing alternatives, chose to make the list the whole surface. That reopened the archive-confirmation question: archive is fully reversible (`unarchive` restores, transactions untouched), so what does a confirm modal buy?

**Decision.** Two moves, decided together. **(1) The record detail is deleted**; the Manage lists act in place (`ResourceListScreen` in [_base.py](../expense/tui/screens/_base.py)): `e` pushes the prefilled edit bar-form, `a` archives/unarchives the cursor row, `enter` is a no-op. The cursor is preserved on the acted-on row across the post-write reload so a second `a` reliably undoes the first. **(2) Archive is reclassified as a reversible toggle, not a destructive operation — everywhere.** The TUI toggle runs with no confirm modal (toast only), and the flat CLI `archive` commands dropped both the confirmation prompt and the `--yes` flag, matching the always-prompt-free `unarchive`. Only delete/revert/clear remain confirm-gated (CLAUDE.md "Confirm destructive operations", [test_command_surface.py](../tests/unit/test_command_surface.py) armor). Chosen sketch: [mockups/expense-world-manage-merge.html](mockups/expense-world-manage-merge.html) (Alt A minus the confirm), superseding [mockups/expense-world-manage-edit.html](mockups/expense-world-manage-edit.html).

**Rejected.** *Inline cell edit* ([mockups/expense-world-manage-inline-edit.html](mockups/expense-world-manage-inline-edit.html)) — spreadsheet-style per-cell editing in the table; liked in principle but it introduces a second edit idiom used by only three screens, plus a bespoke cell-editor widget. *Below-table menu/action-bar/docked panel* ([mockups/expense-world-manage-menu-below.html](mockups/expense-world-manage-menu-below.html)) — three flavours sketched; all add chrome to teach two keys the footer already teaches. *Keeping the confirm modal on archive* — the original 2026-07-07 worry was `a` firing on a stray list row, but the cursor row is reverse-highlighted, the toast names the outcome, and a mis-archive is one keypress from undone; a confirm on a reversible toggle is pure friction (and the rest of the app — Inbox `p`/`d` — already acts on the cursor row). *`enter` as an edit alias* — declined by the user; only `e` edits, keeping `enter` strictly non-mutating.

## Every data table pages at 20 rows — CLI human mode + TUI, two tiers (2026-07-11)

**Context.** User request: no table shows more than 20 rows; the rest paginates. Before this, the TUI drew whole payloads into one Rich table (a fixed first-50 for Transactions/Activity/Rates — pages 2+ unreachable — and *everything* for Manage/Reconciliations), and CLI `list` commands printed whatever the source returned (engine default 50, replica default 100). The engine/cache already shared the offset envelope `{items, total, limit, offset}` and the CLI already had `--limit`/`--offset` + `render_pagination_hint` — the standard mostly had to be wired, not built.

**Decision.** A single 20-row page standard, `DEFAULT_PAGE_ROWS` in [_resource.py](../expense/commands/_resource.py) (one copy for CLI and TUI). **TUI, two tiers:** unbounded datasets (Transactions, Inbox, Activity, Rates) are *fetch-paged* — `PagedListMixin` sends real `limit=20&offset=20·page`, `pgdn`/`.` and `pgup`/`,` refetch, `j`/`k` clamp at the fetched edge (paging is a deliberate keypress); full-data screens (Manage lists, Reconciliations panes, the recon CheckList at 20 items = 40 lines) are *display-windowed* — fetch untouched where guard-pinned, the 20-row window follows the cursor so `j`/`k` walk through and cursor-restore-after-write lands on the right page. Every list became its own quiet-border panel (dossier pick L2 + treatment A): border title absorbs the old title/legend row, border subtitle carries `rows 21-40 of 133 · page 2 of 7`; page keys hide on a single page. Manage Categories/Hashtags switched to `fetch_all_pages` (they silently truncated at the replica's 100 before). **CLI:** human mode defaults to `limit=20` via `effective_limit` and the existing hint takes over; explicit flags win; `--json` sends no default and stays byte-verbatim. `accounts list` gained `--limit`/`--offset` (`queries.list_accounts` is dual-shape: flag-less keeps the flat list internal consumers rely on). **Exempt:** Outstanding's category tree and (pick still open) its static tables, the Monthly grid, System kv-tables, Home. Mockup + recorded picks: [mockups/expense-world-pagination.html](mockups/expense-world-pagination.html).

**Rejected.** *Client-side slicing for envelope-backed reads* — CLAUDE.md's thin-wrapper rule names exactly this shortcut as rejected; the next client must inherit real pagination, and the CLI exists to exercise the engine's contract. *Realigning the replica's default limit (100) to the engine's 50* — would silently change `--json` cache-read output; left as-is and noted here (the >100-row name-map completeness gap is a separate backlog concern). *`[`/`]` as page keys* — Monthly report owns them for month-window sliding; same key, different meaning violates the keymap contract, so `pgdn`/`pgup` + `.`/`,` (all previously unbound). *`j` auto-fetching past the fetched edge* (mockup step-3 option B) — holding `j` to skim would fire a fetch per keystroke at every boundary. *10-item CheckList pages* (strict "20 physical lines") — doubles page-flipping in the most keyboard-intensive flow; 20 items counts data rows like every other table.

## TUI is keyboard-only — mouse disabled via `run(mouse=False)` (2026-07-12)

**Context.** The user noticed `expense world` reacting to mouse clicks and drag-selections and asked to remove it. That behavior was never designed — we wrote zero mouse handlers (no `on_click`/`on_mouse_*`/`capture_mouse` anywhere under [expense/tui/](../expense/tui/)). It comes entirely from Textual's default: on launch the driver enables terminal mouse tracking (`\x1b[?1000h`/`1003h`/`1006h`), after which built-in widgets (`OptionList` menu, `Input` bars, `Footer`) act on clicks. A felt side effect: while Textual owns the mouse, the terminal's native text-selection / copy is suppressed.

**Decision.** Launch keyboard-only — `run_world` passes `mouse=False` to `.run()` ([app.py](../expense/tui/app.py)). Textual 8.2.7's driver short-circuits `_enable_mouse_support()` when the flag is false, so the tracking sequences are never written: the app ignores the mouse (clicks, drags, scroll wheel) and native select-to-copy works again. Nothing is lost — every affordance already has a full keyboard path, and the custom `CursorList`/`CheckList` widgets were keyboard-only from the start. Locked by [test_tui_mouse.py](../tests/unit/test_tui_mouse.py) (asserts `run_world` launches with `mouse=False`). Mouse-wheel scroll is the only casualty; keyboard scroll (`↑`/`↓`, `j`/`k`, `PageUp`/`PageDown`, `,`/`.`) is unaffected. This retires the "mouse" line from the [tui-plan.md](tui-plan.md) Phase-4 niceties list — mouse is now deliberately off, not a future add.

**Rejected.** *Leave Textual's default mouse on* — the behavior was unintended and, worse, blocks native terminal text-selection/copy, a real ergonomic loss in a read-heavy TUI. *Per-widget mouse handlers to swallow clicks* — brittle, wouldn't restore text selection (Textual still owns the mouse), and pointless when a single launch flag disables tracking at the source.
