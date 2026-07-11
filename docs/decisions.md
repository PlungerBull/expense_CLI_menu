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

**Decision.** The TUI **offers `e` (rename/recolor) on system categories** and **hides only `a` (archive)**. Rationale, from the engine spec: system categories are resolved by an immutable `system_key` column, never by name, so renaming is pipeline-safe and explicitly allowed (`PUT` has no `is_system` guard — engine-spec §Categories) — the `system_key` machinery was built specifically to make renaming safe, including localization (`@Transfer` → `@Transferencia`). Archive and delete, by contrast, change availability and would break the transfer pipeline, so the engine `403`s them. Hiding `a` therefore *reflects* a guaranteed-`403`; offering `e` reflects a guaranteed success. Implemented via `ManageDetailScreen.check_action` in [manage_detail.py](../expense/tui/screens/manage_detail.py).

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
