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
| ~~Cache-by-default, stateless as escape hatch~~ | Step 7b | **Reversed 2026-08-06** — see "Delete the local replica" below |
| PAT auth (Option B: `ewe_pat_` prefix, JWT fallthrough) | 2026-04-23 | [cli-spec.md](cli-spec.md) "Auth model" |
| Public GitHub repo → secrets never enter the repo | project inception | [CLAUDE.md](../CLAUDE.md) "Config isolation" |
| Sanctioned deviations from the principles (3 items) | 2026-07 | [cli-spec.md](cli-spec.md) "Sanctioned exceptions" |
| Sign is always literal — no default-to-expense magic | 2026-04-25 | full entry below |
| Dual-UX strategy (flat + TUI + quick-add) | 2026-04-25 | full entry below |
| Questionary menu deleted ahead of its gate | 2026-07-02 | full entry below |
| Mockup-first, and showing ≠ approval | 2026-05-24 (hardened) | full entry below |
| The open-work list holds only open work (the workpad is `todo.md`) | 2026-07-06 | full entry below |
| Manage detail: system categories are editable, not immutable *(archive half moot since 2026-08-06)* | 2026-07-07 | full entry below |
| Monthly report TUI is a sliding 4-month grid, not a single-month view *(the grid absorbed Outstanding Amounts 2026-08-29 — see "Overview")* | 2026-07-08 | full entry below |
| Overview — one screen for stock and flow, a band capped at 5 that always reads today | 2026-08-29 | full entry below |
| ~~`SyncContractError` + exit code 5 for /sync contract violations~~ *(**moot since 2026-08-06** — the error class went with the replica)* | 2026-07-08 | full entry below |
| TUI writes: FIFO queue in EngineWriteMixin, error drops the queue | 2026-07-08 | full entry below |
| Connection errors → exit code 6, off the click-usage collision on 2 | 2026-07-10 | full entry below |
| TUI paints the terminal's own background (ANSI mode) — one surface, no seam | 2026-07-11 | full entry below |
| Archive is a prompt-free toggle (accounts-only since 2026-08-06); Manage record detail deleted | 2026-07-11 | full entry below |
| Every data table pages at 20 rows (CLI human mode + TUI), two-tier design | 2026-07-11 | full entry below |
| TUI is keyboard-only — mouse disabled via `run(mouse=False)` | 2026-07-12 | full entry below |
| TUI rows-per-page adapt to the terminal — min(20, what fits) | 2026-07-13 | full entry below *(cap lifted on Transactions/Inbox 2026-08-29 — see below)* |
| The ledger fills the window — Transactions/Inbox drop the 20-row and 110-column caps | 2026-08-29 | full entry below |
| `expense world` clears the terminal scrollback at launch (`CSI 2J 3J H`) | 2026-07-13 | full entry below |
| Opening balances are an engine concept (`@Opening` system category), not a CLI convention | 2026-07-20 | full entry below |
| Local-first deployment — the one engine moves to the user's Mac; cloud mothballed until iOS | 2026-07-30 | full entry below |
| Delete the local replica — all reads live; `expense sync` and the cache retired | 2026-08-06 | full entry below |
| Transfers are two ordinary transactions — the feature is gone client-side | 2026-08-16 | full entry below |
| Reconciliation de-chaining — a batch is a statement period, ordered by its date | 2026-08-16 | full entry below |
| Home aggregates are nullable — `3 unrated` is a state, not a number | 2026-08-16 | full entry below |
| Contract tests verify against a disposable database, and refuse the real ledger | 2026-08-16 | full entry below |
| A settled person is folded, never hidden — and creating one is a TYPE field, not a `people` group | 2026-08-16 | full entry below |
| The inbox has no deleted view — `--include-deleted` is paired with `restore`, and the inbox has none | 2026-08-16 | full entry below |
| One word for hashtags — the engine's, everywhere | 2026-08-16 | full entry below |
| The light theme will detect the terminal, not ask the user | 2026-08-16 | full entry below |
| The command palette is removed, not populated — `?` is the one discoverability surface | 2026-08-17 | full entry below |
| The terminal supplies the palette — every colour is an ANSI slot, nothing is detected | 2026-08-19 | full entry below |
| A terminal too small is the user's to fix — no size guard; 80×24 correct, 60×20 lossy | 2026-08-20 | full entry below |
| Logging is a key, not a menu row — plain `+`, and the footer stops naming the arrow keys *(what `+` opens changed 2026-08-25 — see "What a half-written batch means")* | 2026-08-20 | full entry below |
| Three quick-add grammar rules — contains-matching, dashed dates, tags are never created | 2026-08-25 | full entry below |
| Two calls for the one-line `expense log` — incomplete drafts to the Inbox, and it always asks first | 2026-08-25 | full entry below |
| Four calls for the LOG bar — the raw line comes back, tags stay, totals are per currency, one wording for why | 2026-08-25 | full entry below |
| What a half-written batch means — the LOG bar's save, and `+` switching to it | 2026-08-25 | full entry below |
| One key per job — `j k h l , .` deleted, and the month window moves to `pgdn`/`pgup` | 2026-08-27 | full entry below |
| The LOG bar shows the named account's ledger — elastic, and it stays put | 2026-08-29 | full entry below |
| The legend, the two picker gaps, and day+month dates | 2026-08-29 | full entry below |

## What a half-written batch means (2026-08-25)

**Context.** Phase 4 of the quick-add bar gave the LOG bar its `ctrl+s` and pointed `+` at it. The write is deliberately two calls, not one: the complete rows go in a single atomic `POST /transactions/batch`, and each Inbox-bound row is a `POST /inbox` after it. That shape is what makes the interesting question possible — the engine can die *between* them — and [mockups/expense-world-quickadd-batch.html](mockups/expense-world-quickadd-batch.html) had only drawn the all-or-nothing case. Four questions were put to the user as rendered variants.

**Decision.** (1) **A successful save does not leave the screen.** The written rows stay, each with a `✓`, and are cleared the moment the next line is staged — so the list only ever shows rows you are about to write, and what a finished batch leaves behind is one sentence (`Nothing staged. 2 logged · 1 draft in the Inbox a moment ago.`). (2) **A partial failure ticks what landed and retries only the rest.** Rows the engine holds are done and are never re-sent; rows that failed keep their marker and carry the engine's own message under the table; `ctrl+s` covers only rows without a `✓`. This is safe because **`row_id` is minted at stage time and reused on every attempt** — a row whose response was lost replays under the id it already had, so the engine answers `409`, which the save reads as *written*, not as an error. Nothing can be written twice. (3) **`ctrl+s` leaves an unstaged line in the bar alone.** `↵` is the only thing that stages, so a save can never write something still being typed. (4) **The discard card's third answer, `ctrl+s save first`, saves and then leaves** — you pressed `esc`, so the intent was to go — **unless the save fails**, in which case the screen stays, because an error you cannot read is the same as no error at all.

Two consequences worth naming. A **saved row cannot be lifted back into the bar**: editing it would promise a change this screen cannot make, since the bar only ever creates. Correcting a written row is the edit form's job, which is precisely why that door stayed open ([mockups/expense-world-two-doors.html](mockups/expense-world-two-doors.html)). And `+` **still means one thing** on all three screens that bind it, the Inbox included: where a row lands is decided by the line you typed and shown in the `goes to` column before you commit, never by which screen you were standing on.

**Rejected.** For (1): *dismiss on success*, which throws away the confirmation the user actually wanted and makes a five-row batch a five-row leap of faith; *keep the ticked rows until you leave*, rejected because the list then mixes history with intent, and the per-currency total under it would describe a batch that no longer exists. For (2): *tick nothing until everything lands, and re-send the whole list on retry* — safe, because the frozen ids make the ledger rows replay as 409s, but it hides a partial failure behind a wall of conflicts and makes the engine do the de-duplication the screen could have done honestly; *fail the whole save on one bad row*, which is the thing the singleton fallback exists to prevent. For (3): *stage the bar's line automatically and save it too*, rejected because a save would then write a line the user had not finished — the one thing `↵` exists to gate; *refuse the save outright until the bar is empty*, rejected as punishing a correct instinct. For (4): *save and stay*, rejected because it answers a question the user did not ask — they pressed `esc`.

**Also settled here, without ceremony.** The row's **`date` is frozen at stage time** alongside its routing and its id: a batch typed at 23:59 and saved at 00:01 must not silently change day between what you read and what you wrote. And the batch mechanics — chunk, then one row per batch when the engine refuses without naming a row — were **extracted** from the `.xlsx` importer into [expense/batch_write.py](../expense/batch_write.py) rather than copied, so the LOG bar and `expense import` share one copy of a workaround that exists only because the engine does not send the per-item error index its spec promises.

## Four calls for the LOG bar (2026-08-25)

**Context.** Phase 3 of the quick-add bar built the TUI screen the whole item exists for: one `LOG` bar, `↵` stages a parsed line into a list, the list says where every row is going before anything is written. Its design was already picked — option **D** of [mockups/expense-world-log-revamp.html](mockups/expense-world-log-revamp.html), worked out in [mockups/expense-world-quickadd-batch.html](mockups/expense-world-quickadd-batch.html). Four details that mockup left ambiguous (one of them a disagreement with a second mockup) were put to the user as drawn variants.

**Decision.** (1) **A staged row comes back as the raw line you typed.** `↑↓` pick a row, `↵` lifts it into the bar, and what appears is the exact text that made it — the mockup's blurb ("the row came back as the line that made it") rather than its drawing, which showed a canonical re-render with the names spelled out. Nothing is invented on the round trip, so the line and the row can never disagree. (2) **The staged table keeps its `tags` column** — the batch mockup's eight-column set, which supersedes the seven columns [mockups/expense-world-two-doors.html](mockups/expense-world-two-doors.html) draws. (3) **The batch totals per currency.** One line is one movement in one account and therefore one currency (the user's framing), but a *batch* can hold a PEN row and a USD row, so the summary prints one figure per currency and never adds them: `3 to the ledger · -45.20 PEN · -96.00 USD`. With a single currency staged — the normal case — it reads exactly as the mockup drew it. (4) **The Inbox footnote reuses [route.py](../expense/quickadd/route.py)'s own phrases**, prefixed with the row number: `2 to the Inbox — row 3: the line names no account · row 5: it is dated ahead`. The flat `expense log` prints the same strings; there is one wording for one rule, in one place.

**Rejected.** For (1): *rebuild the line from the row* — resolved names spelled in full plus a bare sigil parked at the end for whatever is missing, which is closer to what pane 6 actually draws. It reads better on the screen and is a second formatter to keep in step with the grammar forever; a re-render that drifts from the parser loses text the user typed, and that is the one thing a capture bar must not do. For (2): *drop the tags column*, buying ~13 columns for the title and account cells on a narrow terminal — rejected because tags are half of why a line is typed rather than clicked, and the marker and row number were merged into one cell (`• 1`) instead, which bought the width back. For (3): *no figure at all when the batch is mixed*, and *never a figure* — both refuse to answer the question the summary exists to answer, and both are silently different from the single-currency case. For (4): *the count alone*, letting the row's own red `— account?` cell carry the why — genuinely tempting, and rejected because a row can be Inbox-bound for a reason with no cell of its own (dated ahead shows only as a red date); *a second, shorter wording* written for this footer to match the mockup literally (`row 3 has no account`) — rejected as a phrase table that would drift from route.py's the first time either changed.

**Also settled here, without ceremony.** The date cell shows the **year whenever it is not the current one** (`18 Aug`, but `18 Aug 2024`). Two-digit years are accepted by the grammar only because the resolved date is always echoed before the row is committed ("Three quick-add grammar rules" below); in the TUI that echo *is* the staged list, and a bare `18 Aug` would hide exactly the digit in question.

## Two calls for the one-line `expense log` (2026-08-25)

**Context.** Phase 2 of the quick-add bar gave the phase-1 grammar its first caller: `expense log "tottus -38.60 $signature @korakuen hoy"`. The grammar was already settled and the batch mockup already answered these questions *for the TUI*; the flat command is a different shape — one line, one shot, no staged list — so both were put to the user again as plain questions.

**Decision.** (1) **An incomplete line becomes an Inbox draft, not an error** — the routing rule holds on both surfaces ([quickadd/route.py](../expense/quickadd/route.py) is the one copy): complete and not dated ahead goes to `POST /transactions`, everything else to `POST /inbox`. **An ambiguous name counts as no name** — `$sig` matching two accounts drafts the row exactly as a missing `$` would, though the candidates are printed anyway, because the way out is to answer `n` and type more of the name. (2) **The command always asks before writing**, `--yes` skips. It echoes the parsed row first — the date spelled out in words, the account and category by name — and waits for y/N.

The second call is the load-bearing one. The grammar is forgiving on purpose: `18/8/26` is a date, `hoy` is today, `$sig` finds an account from a fragment. Two-digit years were accepted at all *because* the resolved date is always echoed before the row is committed — in the TUI that echo is the staged list, and nothing reaches the engine until `ctrl+s`. The flat command has no staging step, so the prompt is where that guarantee lives. It is deliberately **flat-CLI only**: it sits in [log_cmd.py](../expense/commands/log_cmd.py), never in `expense/quickadd/`, so the TUI is not asked to confirm twice.

**Rejected.** For (1): *refuse and name what is missing*, which reads well in a shell (press ↑, fix, retype) but splits one routing rule into two behaviours across two surfaces, and makes the flat command the only place a captured line can be lost; *refuse unless `--inbox`*, same objection plus a flag to remember. For the ambiguity half: *always refuse on an ambiguous name*, rejected as a second rule for what is already one thing — an unresolved reference — and unnecessary once the candidates are printed either way. For (2): *write, then echo* with `--dry-run` as the look-first path, rejected because a misread would already be in the ledger and `--dry-run` is opt-in, i.e. the check would be skipped exactly when someone is typing fast; *prompt only when something was inferred* (a two-digit year, a `contains` match rather than an exact one), rejected as an unpredictable prompt — the user cannot tell before pressing enter whether this line will stop, and a confirmation that appears sometimes trains you to dismiss it.

**Also settled here, without ceremony:** the flat form's output block is option **A** of [mockups/expense-world-log-oneline.html](mockups/expense-world-log-oneline.html) (two lines — title with the amount right-aligned, then everything else dot-separated), picked 2026-08-25 over a labelled field list.

## Three quick-add grammar rules (2026-08-25)

**Context.** Phase 1 of the quick-add bar turned the grammar into a real module, [expense/quickadd/](../expense/quickadd/). Most of the grammar was already settled — the sigils, first-sign-wins, `//` after a space, both languages — but writing the parser surfaced three questions the todo and [mockups/expense-world-quickadd-batch.html](mockups/expense-world-quickadd-batch.html) never answered. All three are user-visible behaviour, so all three were put to the user as plain questions.

**Decision.** (1) **Reference names match on "contains, anywhere."** `$sig` matches any account whose name contains "sig"; exactly one hit resolves, zero or several leave the token unresolved carrying its candidates for a picker. An exact casefold name still wins outright before contains is tried, and longer phrases are tried before shorter ones, so `#caja` is `CAJA` and `#caja chica` is `CAJA CHICA`. (2) **Dashed ISO dates are accepted** — `2026-08-18` alongside `18/08/2026`, `2026/08/18` and the word forms — because that is the shape `--date` takes on every shipped command. Dashes stay ISO-only: `18-08-2026` is not a date, which keeps the dashed form unambiguous. (3) **An unmatched `#tag` is flagged, never created.** It stays unresolved, which addresses the row to the Inbox at stage time, exactly as a missing account does.

**Rejected.** For (1): *whole-name-only* matching, which is the most predictable but leaves the flat `expense log "…"` of phase 2 with no completion to lean on and forces the user to type "BCP Signature USD" in full; and *starts-with*, which quietly fails the common case of typing the distinctive middle word of a long account name. Contains also matches what every existing TUI picker already does ([quick_log.py](../expense/tui/screens/quick_log.py) `_recompute`, [create_forms.py](../expense/tui/screens/create_forms.py)), so the bar behaves like the rest of the app. For (2): *slash forms only*, as drawn — rejected as a trap, since a user who types dashed dates everywhere else would silently get title text. For (3): *create-on-save*, the resolve-or-create behaviour [import_/apply.py](../expense/import_/apply.py) uses — rejected because a typo in a capture bar would become a permanent new tag; and *swallow as title text*, rejected because it loses the tag without saying so. Note also that the earlier [mockups/expense-world-log-revamp.html](mockups/expense-world-log-revamp.html) option D draws `@account` / `/category`; the batch mockup supersedes it with `$account` / `@category`, and the parser follows the batch mockup.

## Sign is always literal — no default-to-expense magic (2026-04-25)

**Context.** The engine's `debit_as_negative` convention (negative = expense, positive = income) is central to how the whole system reasons about money. While designing the capture UX (structured `log`, future quick-add parser), the tempting default existed: treat a bare unsigned amount as an expense, since most entries are expenses.

**Decision.** The sign is always explicit, end-to-end, in every UX layer: `$20` = income, `-$20` = expense. An unsigned amount where the sign is ambiguous gets a prompt or an error — never a guess. The rule surfaces in [cli-spec.md](cli-spec.md) "Principles" and the quick-add entry under "To Be Defined". The single sanctioned exception was the TUI transfer "To amount" field (magnitude entry, sign auto-set opposite the Amount leg per the engine's zero-sum rule). **Superseded 2026-08-16:** the exception died with the engine's transfer-feature removal (2026-08-10); the rule now holds everywhere with no exceptions.

**Rejected.** Default-to-expense for quick-add, offered explicitly and declined by the user. Reasons: a magic default is hidden behavior that diverges from what the engine actually stores; it confuses the user about what was recorded; and it complicates the future parser with intent inference. When a new command or parser takes an amount, require the sign or reject the input.

## Dual-UX strategy — flat commands + TUI + quick-add (2026-04-25)

**Context.** For a multi-command CLI, discoverability friction is real for infrequent management tasks ("which flag archives an account?"), but for daily capture, flat commands beat any menu (`expense log -20 …` beats walking six prompts). One interaction mode can't serve both.

**Decision.** Three surfaces over one implementation, each matched to an actual need: (1) **flat commands** — canonical, scriptable, the contract-validator surface, always the source of truth for behavior; (2) an **interactive surface** for management and first-time discovery — originally the questionary `expense menu`, replaced by the Textual TUI `expense world` (see next entry); (3) a **quick-add parser** for daily capture (still open — [todo.md](todo.md)). Every interactive action delegates to the shared fetch/write layer — no parallel logic. `expense` with no args keeps printing group help; the interactive surface is opt-in.

**Rejected.** Interactive-first UX (slower for capture, unscriptable); folding flat commands under the interactive surface (kills scripting, testing, and the parser's dispatch target); building the interactive layer before Step 9 (UI over a moving action surface is wasted work). This mirrors Todoist's architecture — quick-add bar for capture, menus for everything else — per the lessons docs in the engine repo.

## Questionary menu deleted ahead of its gate (2026-07-02, Step 10.X)

**Context.** The questionary `expense menu` shipped at Step 9.5 as the first interactive surface. The Textual TUI (`expense world`, Step 10) superseded it while still short of full parity; the original plan deleted the menu only after TUI P2+P3 completion.

**Decision.** Delete early: `expense/menu/`, its test suite, the Typer command, and the `questionary` dependency all removed at Step 10.X. Nothing was lost because the flat commands are the complete contract-validator surface — the menu was a convenience layer, not a capability. Keeping two interactive surfaces alive meant maintaining every new feature twice for no product value, since the TUI was already the committed direction. <!-- [user to confirm: the double-maintenance motivation matches your recollection of the 2026-07-02 call] -->

**Rejected.** Waiting for full TUI parity (pays double maintenance during the overlap); keeping the menu as a fallback (two half-loved surfaces instead of one good one).

## Mockup-first, and showing ≠ approval (hardened 2026-05-24)

**Context.** The rule "mock every screen before building it" existed from the Step 9.5 table work. On 2026-05-24 it grew teeth: three Reports-view mockups were produced for the user to choose between, and before a pick was made, a vague follow-up ("where were we?") was taken as a go-ahead — Option A got implemented unilaterally. The user expected the render to *be* the deliverable; implementation needed its own green light.

**Decision.** Every user-facing view or table change starts with an HTML mockup in [mockups/](mockups/), **and presenting mockups is never authorization** — implementation waits for an explicit pick, even in auto-accept mode, even when a follow-up sounds like consent. A prior session's approval is not a standing license: the user re-reads the mockup each time a screen is picked up, because specific observations only come from re-reading. Full rule in [CLAUDE.md](../CLAUDE.md) "Mock every screen before building it"; the CLI-table variant (propose columns + sign-off) in [cli-spec.md](cli-spec.md) "Output conventions".

**Rejected.** Treating an earlier approval as durable (screens drift, and so do the user's observations); inferring layout or columns from the engine response shape (scannability is the user's product judgment, not a derivable fact).

## The open-work list holds only open work (2026-07-06; the file has been `polish-backlog.md` → `backlog.md` → [todo.md](todo.md), the last rename on 2026-08-20 when the closed engine-rework phases were deleted with it)

**Context.** When the 2026-07-02 quality review was fully worked off, the choice was append the new review below the closed one, or replace.

**Decision.** Replace. A fully-closed review's content is deleted; the file header notes the commit holding the last full copy (the 2026-07-02 review lives at `2d42482`). It is a working list, not an archive — git history is the archive ("If the previous data is finished, we might be better deleting the information", 2026-07-06).

**Rejected.** Append-and-keep (the file becomes noise; closed items get re-read forever); a separate archive doc (a second home for facts git already keeps).

## Manage detail: system categories are editable, not immutable (2026-07-07)

> **Superseded in part (2026-08-15).** The engine's 2026-08-06 schema slimming deleted category/hashtag archive entirely, so the hide-`a`-on-system-categories mechanics below are moot — categories no longer have an `a` binding at all (archive is accounts-only; the toggle moved to `AccountsScreen`). The surviving half of this decision — system categories **are renameable** via `e`, never TUI-immutable — still governs.
>
> **Superseded in part, again (2026-08-16).** `@Transfer` and `@Debt` — the categories this entry reasons from — were deleted with the engine's transfer-feature removal (2026-08-10). The rule survives unchanged but now applies to a single system category, `@Opening`; the "would break the transfer pipeline" rationale below is historical.

**Context.** Building the Manage edit flow (`enter`→detail→`e` edit / `a` archive; see [tui.md](tui.md)), the question was how to treat system categories (`@Transfer`, `@Debt`). The initial instinct — and a first recommendation — was to make them fully read-only in the TUI (hide `e` and `a`), assuming "system = untouchable." The engine's actual contract is the opposite on the axis that matters.

**Decision.** The TUI **offers `e` (rename/recolor) on system categories** and **hides only `a` (archive)**. Rationale, from the engine spec: system categories are resolved by an immutable `system_key` column, never by name, so renaming is pipeline-safe and explicitly allowed (`PUT` has no `is_system` guard — engine-spec §Categories) — the `system_key` machinery was built specifically to make renaming safe, including localization (`@Transfer` → `@Transferencia`). Archive and delete, by contrast, change availability and would break the transfer pipeline, so the engine `403`s them. Hiding `a` therefore *reflects* a guaranteed-`403`; offering `e` reflects a guaranteed success. Implemented via `ResourceListScreen.check_action` in [_base.py](../expense/tui/screens/_base.py) (originally on the record detail's `ManageDetailScreen`, which was deleted 2026-07-11 — see the archive-toggle entry below; the system-category rule carried over unchanged).

**Rejected.** (1) **Hide `e` on system categories** (make them TUI-immutable) — rejected as client-invented business logic: the engine permits the rename, so a client silently forbidding it is exactly the split-brain the thin-wrapper rule exists to prevent. (2) **Ask the engine to `403` `PUT` on system categories** "for consistency" with archive/delete — rejected: that's a *false* consistency (existence vs. presentation are different axes) and would throw away the deliberately-engineered rename/localization capability. The engine is internally consistent as-is; only the CLI's `_SYSTEM_HINT` copy ("cannot be modified") was imprecise and was corrected. Distinction credited to the user's review of the first recommendation.

## Monthly report TUI is a sliding 4-month grid, not a single-month view (2026-07-08)

> *2026-08-29: Outstanding Amounts was merged into this screen — see "Overview" below.
> The rejection of a single-month view **stands**; what changed is that the duplicate this
> entry named out loud was deleted, instead of being left one navigation step away.*

**Context.** The Monthly report screen was the last unwired home-menu entry ([tui.md](tui.md)). The first mockup proposed a single-month view (categories + hashtag breakdown + totals, `[`/`]` to change month) — a natural mirror of the flat `reports monthly --date`. The user rejected it on review: a single month of category spend is what **Outstanding Amounts already shows**; a second screen rendering the same shape one navigation-step away adds no information, just a month picker.

**Decision.** The screen is a **4-month grid** — categories as rows, the last four months as columns (window ends at the current month), home-currency cells, net-only footer; `[`/`]` slide the window one month older/newer, no clamp. *(keys superseded 2026-08-27 — see "One key per job")* **Picked 2026-07-08 (option A of two drawn):** rows expand `▼/▶` into their hashtag combos across all four columns, reusing the Outstanding tree keymap; collapsed by default so the grid first reads like the CLI range table. One engine call per window (`GET /v1/reports/monthly` with from/to via the shared `fetch_range`); the grid merge (`build_range_grid`) is shared with the flat range renderer.

**Rejected.** (1) **Single-month view** — duplicates Outstanding Amounts; the report's value over the dashboard is the *time axis*, so the screen must show it. (2) **Single-month + a range-view toggle** — two layouts to build and maintain when the sliding window already covers the trend need with one. (3) **`←`/`→` for month navigation** — collides with the tree's expand/collapse bindings, hence `[`/`]`. *(Still true, and still why `←`/`→` were not chosen when the window moved to `pgdn`/`pgup` on 2026-08-27.)* (4) **Option B (flat, always-expanded grid)** — offered in the mockup, not picked; long months can't fold their hashtag noise.

## `SyncContractError` + exit code 5 for /sync contract violations (2026-07-08)

> **Moot 2026-08-06.** `SyncContractError` and exit code 5 were deleted with the
> local replica — there is no `/sync` response left to violate a contract. See
> "Delete the local replica" below. The surviving exit-code family is **1**
> (engine rejected the request), **3** (config), **6** (connection), with **2**
> left to click alone; 4 (cache) and 5 (sync contract) are retired and should
> not be reused. The reasoning below is kept because the *principle* it set —
> a new meaning gets a fresh code, never an overloaded one — is still the rule.

**Context.** Two cache-sync guards raised bare `RuntimeError`: `_derive_user_id` when a /sync response has null settings and every resource empty (reachable by installing a PAT and running any list command before `auth bootstrap`), and `_fetch` when the engine omits `sync_token`. `handle_errors` catches only the domain errors, so both escaped as raw tracebacks — the exact freshman path the CLI exists to smooth.

**Decision.** A new domain error, `SyncContractError` ("the engine responded but violated its own contract"), registered in the `_ENVELOPE_ERRORS` table in [expense/errors.py](../expense/errors.py) with envelope code `SYNC_CONTRACT` and **exit code 5** — a new family alongside 1 (engine rejected the request), 2 (connection), 3 (config), 4 (cache). The user-facing message carries the remedy ("run 'expense auth bootstrap' first"), so the TUI toast inherits the hint via `format_error`'s fallback.

**Rejected.** Exit 1 (folding it into "engine error" hides that the *contract* broke, not a request — scripts couldn't tell a broken engine build from a validation error); exit 2 (already double-booked: connection errors share it with click's usage errors, then an open nit — since closed by moving connection to exit 6, see below — and adding a third meaning would have made it worse); keeping `RuntimeError` and catching it broadly in `handle_errors` (would swallow genuine client bugs, which must keep crashing loudly).

## TUI writes: FIFO queue in EngineWriteMixin, error drops the queue (2026-07-08)

**Context.** `run_write` was a thread worker with `exclusive=True`, but thread cancellation is cooperative and never checked — rapid repeated writes (double-pressed archive, fast checklist toggles) fired overlapping, unordered PUTs. The checklist screen had fixed this locally with its own queue + inflight flag; every other screen still raced, and every write ran its own `refresh_after_write` delta — a 15–30-toggle reconciliation burst meant 2 engine round-trips per toggle against Render.

**Decision.** The mixin owns a per-screen FIFO: `run_write` enqueues, exactly one request is in flight, order is preserved. **A failed write drops the queued remainder** — those intents were decided against a screen state the engine just contradicted; the error callback resyncs (user decision 2026-07-08, generalizing the tested toggle behavior). `run_write(refresh=False)` coalesces the replica refresh into one delta sync when the queue drains — including after an error drain, since earlier skipped-refresh successes already changed engine state. The checklist's local queue was deleted; its serialization tests pass unchanged against the mixin.

**Rejected.** Per-screen queues à la `_pump_toggles` (N copies of the same race fix, each one edit from drift); cancelling in-flight writes on supersede (cooperative cancellation can't actually stop a thread mid-request, and aborting engine writes mid-flight is worse than finishing them — the idempotency key already covers retries); continuing the queue past a failure (later writes may depend on the failed one, and it would silently change the tested toggle-error contract).

## Connection errors get exit code 6, off the click collision on 2 (2026-07-10)

**Context.** `EngineConnectionError` mapped to exit **2** — the same code click/Typer emit for usage errors (bad flags, missing args). A script or CI run couldn't tell "engine unreachable" from "you called it wrong." The `SyncContractError` decision above had already flagged this as an open nit when it took 5 rather than overload 2.

**Decision.** Move `EngineConnectionError` to **exit code 6** in the `_ENVELOPE_ERRORS` table ([expense/errors.py](../expense/errors.py)) — one row; `render()` and `handle_errors` inherit it automatically. The family was then 1 (engine rejected) · 3 (config) · 4 (cache) · 5 (sync contract) · **6 (connection)**, with **2 left to click alone**. Same principle as the exit-5 call: a new meaning gets a fresh code, never an overloaded one. *(**Since 2026-08-06** the replica's deletion retired 4 and 5, so the live family is 1 · 3 · 6 — `expense/errors.py` `_ENVELOPE_ERRORS` is the source of truth. The retired codes stay retired rather than being recycled.)*

**Rejected.** Reusing 2 with a distinguishing message (scripts branch on the code, not prose); renumbering the family so connection sits contiguous with 1–5 (churns four codes and their tests for cosmetics — appending 6 is the minimal, non-breaking move).

## TUI paints the terminal's own background — ANSI mode (2026-07-11)

**Context.** On the `expense world` home screen the user saw three stacked background shades. Investigation confirmed the app paints exactly one fill — `$background = #0e0e11` — plus the selection bar. The "third" shade is the terminal emulator's own **window padding**, drawn in the Terminal profile's background (near-black). Because `#0e0e11` is a hair lighter than the terminal's black, the app content reads as a lighter panel inside a darker frame — a seam the app can't paint over, only *match*. Mockup + rejected-alternatives render: [mockups/tui-ansi-transparent-background.html](mockups/tui-ansi-transparent-background.html).

**Decision.** Run the TUI in **ANSI mode** — `ExpenseApp` passes `ansi_color=True` ([app.py](../expense/tui/app.py)). Textual then emits the terminal's default background (SGR 49) instead of a fixed hex, so the app fill and the window padding become one continuous surface that **follows whatever dark terminal it runs in**. Scope is deliberate: **adaptive background, pinned foreground.** The theme stays non-ANSI, so every design token keeps its authored hex (net/spent red, owed green, grey selection bar, `$surface` separators, footer); only the base fill and inherited text color go through the terminal, and [app.tcss](../expense/tui/app.tcss) pins the foreground back to `$foreground` under `Screen:ansi`. The base fills (`Screen`, `#menu`) carry `ansi_default` — the id-level `#menu` rule out-specifies Textual's `Screen:ansi`, so a hardcoded fill there would just relocate the seam to the menu edge (guarded by `test_base_fills_are_terminal_transparent`). `ModalScreen:ansi` is overridden to keep the dim scrim Textual otherwise drops. This is correct on any **dark** terminal and identical to before on a near-black one; it does **not** make the app readable on a **light** terminal — the fixed muted/semantic hexes assume a dark ground. That, plus a true light theme, was the open light/`NO_COLOR` item — **closed 2026-08-19 by deleting its premise**, see "The terminal supplies the palette" below.

**Rejected.** *Match a fixed hex* (`background="#000000"`) — exact and one line, but pinned to a single Terminal profile; on any other terminal the frame comes back. *Do nothing / fix the terminal profile* — punts a code-owned problem onto every machine's config. *Full native-ANSI theme* (`theme.ansi=True`, semantic colors → `ansi_*`) — truly terminal-agnostic including light terminals, but throws away the tuned sign-color palette and restyles foreground/scrollbars/footer app-wide; that belongs to the dedicated light/`NO_COLOR` theme work, not a seam fix. **This rejection was reversed 2026-08-19** — the native-ANSI theme is now what ships, and giving up the tuned palette turned out to be the price worth paying. The reasoning above was right about the *cost* and wrong that the cost was too high; see "The terminal supplies the palette". Everything else in this entry still governs: the ground work below is the foundation the reversal builds on, not something it undid.

## Archive is a prompt-free toggle; Manage record detail deleted (2026-07-11)

> **Scope narrowed (2026-08-15).** The 2026-08-06 engine schema slimming removed category/hashtag archive (routes 404, `is_archived` gone), so "everywhere" below now means **accounts only** — the sole archivable resource. The decision itself (reversible toggle → no confirm, no `--yes`) is unchanged and governs the accounts toggle; the deleted-record-detail half is unaffected.

**Context.** `enter` on an Accounts/Categories/Hashtags row opened a record detail (`manage_detail.py`, Option B of 2026-07-07) whose field rows repeated the list's own columns one-for-one — its only value was hosting `e` (edit) and `a` (archive). The user flagged the redundancy ("I can see everything on the previous menu") and, reviewing alternatives, chose to make the list the whole surface. That reopened the archive-confirmation question: archive is fully reversible (`unarchive` restores, transactions untouched), so what does a confirm modal buy?

**Decision.** Two moves, decided together. **(1) The record detail is deleted**; the Manage lists act in place (`ResourceListScreen` in [_base.py](../expense/tui/screens/_base.py)): `e` pushes the prefilled edit bar-form, `a` archives/unarchives the cursor row, `enter` is a no-op. The cursor is preserved on the acted-on row across the post-write reload so a second `a` reliably undoes the first. **(2) Archive is reclassified as a reversible toggle, not a destructive operation — everywhere.** The TUI toggle runs with no confirm modal (toast only), and the flat CLI `archive` commands dropped both the confirmation prompt and the `--yes` flag, matching the always-prompt-free `unarchive`. Only delete/revert/clear remain confirm-gated (CLAUDE.md "Confirm destructive operations", [test_command_surface.py](../tests/unit/test_command_surface.py) armor). Chosen 2026-07-11 as "Alt A minus the confirm", superseding the earlier sketch that kept a record-detail screen.

**Rejected.** *Inline cell edit* — spreadsheet-style per-cell editing in the table; liked in principle but it introduces a second edit idiom used by only three screens, plus a bespoke cell-editor widget. *Below-table menu/action-bar/docked panel* — three flavours sketched; all add chrome to teach two keys the footer already teaches. *Keeping the confirm modal on archive* — the original 2026-07-07 worry was `a` firing on a stray list row, but the cursor row is reverse-highlighted, the toast names the outcome, and a mis-archive is one keypress from undone; a confirm on a reversible toggle is pure friction (and the rest of the app — Inbox `p`/`d` — already acts on the cursor row). *`enter` as an edit alias* — declined by the user; only `e` edits, keeping `enter` strictly non-mutating.

## Every data table pages at 20 rows — CLI human mode + TUI, two tiers (2026-07-11)

> **Amended 2026-07-13:** the TUI tier's fixed 20 became **min(20, what fits
> the terminal)** — see "TUI rows-per-page adapt to the terminal" below. The
> CLI tier (human-mode `--limit 20` default) is unchanged.
>
> **Amended 2026-08-29:** the 20 is no longer universal in the TUI — Transactions
> and Inbox page at what fits, up to the engine's `limit` ceiling. See "The ledger
> fills the window" below. Every other screen, and the CLI tier, still page at 20.

**Context.** User request: no table shows more than 20 rows; the rest paginates. Before this, the TUI drew whole payloads into one Rich table (a fixed first-50 for Transactions/Activity/Rates — pages 2+ unreachable — and *everything* for Manage/Reconciliations), and CLI `list` commands printed whatever the source returned (engine default 50, replica default 100). The engine/cache already shared the offset envelope `{items, total, limit, offset}` and the CLI already had `--limit`/`--offset` + `render_pagination_hint` — the standard mostly had to be wired, not built.

**Decision.** A single 20-row page standard, `DEFAULT_PAGE_ROWS` in [_resource.py](../expense/commands/_resource.py) (one copy for CLI and TUI). **TUI, two tiers:** unbounded datasets (Transactions, Inbox, Activity, Rates) are *fetch-paged* — `PagedListMixin` sends real `limit=20&offset=20·page`, `pgdn`/`.` and `pgup`/`,` refetch, `j`/`k` clamp at the fetched edge (paging is a deliberate keypress) *(keys superseded 2026-08-27 — see "One key per job")*; full-data screens (Manage lists, Reconciliations panes, the recon CheckList at 20 items = 40 lines) are *display-windowed* — fetch untouched where guard-pinned, the 20-row window follows the cursor so `j`/`k` walk through and cursor-restore-after-write lands on the right page. Every list became its own quiet-border panel (dossier pick L2 + treatment A): border title absorbs the old title/legend row, border subtitle carries `rows 21-40 of 133 · page 2 of 7`; page keys hide on a single page. Manage Categories/Hashtags switched to `fetch_all_pages` (they silently truncated at the replica's 100 before). **CLI:** human mode defaults to `limit=20` via `effective_limit` and the existing hint takes over; explicit flags win; `--json` sends no default and stays byte-verbatim. `accounts list` gained `--limit`/`--offset` (`queries.list_accounts` is dual-shape: flag-less keeps the flat list internal consumers rely on). **Exempt:** Outstanding's category tree and (pick still open) its static tables, the Monthly grid, System kv-tables, Home. Mockup + recorded picks: [mockups/expense-world-pagination.html](mockups/expense-world-pagination.html).

**Rejected.** *Client-side slicing for envelope-backed reads* — CLAUDE.md's thin-wrapper rule names exactly this shortcut as rejected; the next client must inherit real pagination, and the CLI exists to exercise the engine's contract. *Realigning the replica's default limit (100) to the engine's 50* — would silently change `--json` cache-read output; left as-is and noted here (the >100-row name-map completeness gap is a separate backlog concern). *`[`/`]` as page keys* — Monthly report owns them for month-window sliding; same key, different meaning violates the keymap contract, so `pgdn`/`pgup` + `.`/`,` (all previously unbound). *`j` auto-fetching past the fetched edge* (mockup step-3 option B) — holding `j` to skim would fire a fetch per keystroke at every boundary. *10-item CheckList pages* (strict "20 physical lines") — doubles page-flipping in the most keyboard-intensive flow; 20 items counts data rows like every other table.

## TUI is keyboard-only — mouse disabled via `run(mouse=False)` (2026-07-12)

**Context.** The user noticed `expense world` reacting to mouse clicks and drag-selections and asked to remove it. That behavior was never designed — we wrote zero mouse handlers (no `on_click`/`on_mouse_*`/`capture_mouse` anywhere under [expense/tui/](../expense/tui/)). It comes entirely from Textual's default: on launch the driver enables terminal mouse tracking (`\x1b[?1000h`/`1003h`/`1006h`), after which built-in widgets (`OptionList` menu, `Input` bars, `Footer`) act on clicks. A felt side effect: while Textual owns the mouse, the terminal's native text-selection / copy is suppressed.

**Decision.** Launch keyboard-only — `run_world` passes `mouse=False` to `.run()` ([app.py](../expense/tui/app.py)). Textual 8.2.7's driver short-circuits `_enable_mouse_support()` when the flag is false, so the tracking sequences are never written: the app ignores the mouse (clicks, drags, scroll wheel) and native select-to-copy works again. Nothing is lost — every affordance already has a full keyboard path, and the custom `CursorList`/`CheckList` widgets were keyboard-only from the start. Locked by [test_tui_mouse.py](../tests/unit/test_tui_mouse.py) (asserts `run_world` launches with `mouse=False`). Mouse-wheel scroll is the only casualty; keyboard scroll (`↑`/`↓`, `PageUp`/`PageDown`) is unaffected. This retires the "mouse" line from the parked live-niceties list ([todo.md](todo.md)) — mouse is now deliberately off, not a future add.

**Rejected.** *Leave Textual's default mouse on* — the behavior was unintended and, worse, blocks native terminal text-selection/copy, a real ergonomic loss in a read-heavy TUI. *Per-widget mouse handlers to swallow clicks* — brittle, wouldn't restore text selection (Textual still owns the mouse), and pointless when a single launch flag disables tracking at the source.

## TUI rows-per-page adapt to the terminal — min(20, what fits) (2026-07-13)

> **Amended 2026-08-29:** the 20 is now a per-screen knob (`PAGE_ROWS_CAP`) and
> Transactions/Inbox raise it to the engine's ceiling, so "grow-to-fit on tall
> terminals" — rejected below — is the behaviour on those two screens. The frame
> arithmetic this entry relies on was also off by 2 lines. See "The ledger fills
> the window" below.

**Context.** In a 120×30 terminal the fixed 20-row page needed 31 lines (chrome takes 11: breadcrumb 4, content padding 2, panel frame 4, footer 1) — the panel's bottom border and the `rows … · page …` subtitle clipped off-screen, and Textual grew a scrollbar on `#content` that nothing could operate: the mouse is off (2026-07-12 decision) and arrows move the row cursor, not the container. The user asked for row counts that follow the window (2026-07-12 screenshots; mockup [expense-world-adaptive-rows.html](mockups/expense-world-adaptive-rows.html)).

**Decision.** **The page IS the screenful, capped at 20** (mockup picks A + CAP 20, 2026-07-13 — the cap keeps the 2026-07-11 "no more than 20 rows" literal; on tall terminals the panel just ends). `SectionScreen.measure_list_rows` ([\_base.py](../expense/tui/screens/_base.py)) measures `#content`'s real height per screen (legends and split panes declare their extra lines), floor 5, `DEFAULT_PAGE_ROWS` as cap and pre-layout fallback; the first load waits for the first layout pass (`call_after_refresh`) so the measure is real. Fetch-paged screens (`PagedListMixin`) send `limit = what fits` — engine contract intact (`limit ∈ [1,200]`), the border subtitle stays truthful — and a resize refetches with the offset re-anchored so the old first visible row stays on screen; window-mode lists (`CursorList`/`CheckList.set_page_size`) re-slice around the cursor, the Reconciliations panes split the space equally, the recon checklist counts fit÷2 items. The dead scrollbar is gone structurally: the panel always fits, so `#content` never overflows. CLI human mode is untouched (stdout has no viewport — still `--limit 20`).

**Rejected.** *Fixed 20-row fetch + a sliding render window inside the page* (mockup option B) — preserves the literal 20 but a "page" no longer matches a screenful: the subtitle needs a third clause (`↓7 below`) and `pgdn` jumps past rows never seen. *Grow-to-fit on tall terminals* (mockup STEP 3 alternative) — declined by the user; cap 20 keeps pages stable across windows. *Cursor-follow scrolling of `#content`* — keeps 20 rows rendered and scrolls the container; the panel title and column headers scroll off-screen and the undraggable scrollbar remains. *Re-enabling the mouse* — reverts the keyboard-only decision and kills native select-to-copy for one scrollbar.

## The ledger fills the window — Transactions/Inbox drop the 20-row and 110-column caps (2026-08-29)

**Context.** In a large terminal the two screens you actually sit in — Transactions and Inbox — held a 110×20 card in the corner of the window and left the rest blank; growing the terminal changed nothing. Two caps did it: `CARD_WIDTH = 110` on both screens, and the app-wide `min(20, what fits)` page size from the 2026-07-13 entry above, whose "grow-to-fit on tall terminals" alternative was declined *then* and asked for *now* by the user ("if i grow the terminal window, the window should grow with it"). Measuring the fix also exposed an old arithmetic bug: `LIST_FRAME_LINES = 4` counted the panel border, column header and header rule but **not** the blank top and bottom edge lines Rich's `box.SIMPLE` draws inside the border, so every list whose fitted size fell below the 20 cap overflowed `#content` by exactly 2 lines — the bottom border and the `rows … · page …` subtitle clipped off-screen and the undraggable scrollbar the 2026-07-13 decision set out to delete came back. It was invisible only because the cap hid it on tall terminals; measured at 120×30 and 180×45.

**Decision.** The cap becomes a per-screen knob, `SectionScreen.PAGE_ROWS_CAP`, defaulting to `DEFAULT_PAGE_ROWS` (20) so **every other screen is untouched** — narrow cards and stable 20-row pages included, which is what keeps short lists tidy on a wide screen. Transactions and Inbox set `PAGE_ROWS_CAP = ENGINE_PAGE_CAP` (200, the engine's own `limit` ceiling, so the fetch contract cannot be broken by a tall window) and `CARD_WIDTH = None` (the card's `width: 1fr` then spans `#content`; the Rich table is `expand=True` and re-lays out on resize). The page still IS the screenful and a resize still refetches with the offset re-anchored — only the ceiling moved. `LIST_FRAME_LINES` is corrected to 6, which is a fix for every list, not just these two: panels now close, subtitles render, and `#content` genuinely never overflows. Guarded by `test_transactions_panel_fills_and_fits_the_viewport` (card spans the full width, panel height ≤ viewport, no scrollbar, at three sizes) and `test_transactions_page_stops_at_the_engine_cap`.

**Rejected.** *Lift the caps app-wide* — offered and declined by the user: Hashtags at 48 columns and Categories at 60 are narrow **because** two short columns spread across 200 columns read worse, not better. *Rows only, keep the 110-column card* — leaves the blank right half the complaint was about. *Fix `LIST_FRAME_LINES` by adding a scrollbar-aware fudge* — the frame is knowable exactly; counting it wrong twice is not a strategy. *Raise the cap to a bigger number (50, 100)* — a second arbitrary literal to re-litigate later; the engine's own ceiling is the only non-arbitrary bound.

## `expense world` clears the terminal scrollback at launch — `CSI 2J 3J H` (2026-07-13)

**Context.** The app runs in the alternate screen (Textual enters it unconditionally), but macOS Terminal.app — unlike iTerm2 — lets the viewport scroll into scrollback *while* a fullscreen app runs. With mouse tracking off (2026-07-12 decision) every wheel/scrollbar gesture goes to the terminal, so pre-launch prompt text (plus the blank rest of that screen page — "the gap") slides in above the running app. Any keypress snaps back, but it reads as a rendering bug (2026-07-12 screenshot). The user picked the clean launch (mockup [expense-world-adaptive-rows.html](mockups/expense-world-adaptive-rows.html) STEP 5).

**Decision.** `run_world` emits `\x1b[2J\x1b[3J\x1b[H` (clear screen, clear scrollback, home) once, after the TTY guard and before Textual takes over ([app.py](../expense/tui/app.py)) — scrolling up during the app then reveals nothing. `3J` is supported by Terminal.app (where it originated), iTerm2, kitty, VTE, Windows Terminal; terminals without it ignore it harmlessly. **Accepted cost, explicitly confirmed by the user:** the tab's *entire* scrollback history is wiped on every launch — not just the page above the app. On exit the visible pre-launch screen still restores (alt-screen restore); only scrolled-off history is lost. Locked by [test_tui_mouse.py](../tests/unit/test_tui_mouse.py).

**Rejected.** *Do nothing + document "press any key to snap back"* — with adaptive rows there is no reason left to touch the terminal scrollbar, but accidental trackpad scrolls still produce the floating-prompt artifact; the user wanted it gone. *Re-enabling mouse tracking so the app swallows wheel events* — reverts the keyboard-only decision. *Clearing only the visible screen (`2J` without `3J`)* — the scrollback above it still scrolls in; doesn't fix the artifact.

## The cursor is reverse video — applied as a Rich style, never as CSS (2026-08-20)

**Context.** The user reported that moving through the home menu showed no selection at all: "there is no selection effect so I don't know where I am selecting." Confirmed at the render layer — the highlighted row emitted `default on default`, byte-identical to every unselected row. The cause was a hole opened by the 2026-08-19 ANSI palette decision: `theme.py` deliberately gives the block cursor **no colour of its own** (`block-cursor-foreground` and `block-cursor-background` are both `ansi_default`) and takes all its contrast from `block-cursor-text-style: reverse`, on the reasoning that reverse video is correct on any ground by construction and so needs no light/dark split. That reasoning is still right. What was not known is that Textual 8.2.7 **drops `reverse`** in `get_visual_style()` when both colours are `ansi_default` — so the CSS cursor path renders nothing. An explicit override in `app.tcss` is dropped identically. Scope was exactly one screen: the home menu is the only list built on Textual's `OptionList`; `CursorList`/`CheckList` set the Rich style directly (`style="reverse"`) and emit SGR 7 correctly.

**Decision.** Keep reverse video as the app-wide "you are here" gesture — one vocabulary for the menu and the data lists — and apply it where it survives. `CURSOR_STYLE` is now a shared constant in [cursor_list.py](../expense/tui/widgets/cursor_list.py); `CursorOptionList` subclasses `OptionList` and applies it to the finished strip in `render_line`, skipping disabled options (the group headers). Five treatments were probed against the real widget and mocked on three real terminal profiles ([mockups/expense-world-menu-cursor.html](mockups/expense-world-menu-cursor.html)); the user picked A, the option that keeps one gesture. `test_tui_menu_cursor.py` asserts on the **rendered strip**, not on the resolved style — `get_component_styles` reported `text_style: reverse` throughout the bug, so a style-level assertion would have passed the whole time. That is the durable lesson: for a theme whose colours are the terminal's, only the rendered output is evidence.

**Rejected.** *Give the cursor a real background (accent bar, dim grey bar)* — both render, and the accent bar is the most conventional TUI selection; rejected because it names two fixed colours instead of borrowing the terminal's, weakening the ANSI proposition, and because it gives the menu a different gesture from every other list. *Bold accent text or bold+underline* — colour-light and legible, but `PENDING_STYLE` already owns bold as "draft/pending", so bold would carry two meanings. *Fixing it in `app.tcss`* — measured, not assumed: the override is dropped too, so there is no CSS spelling of this. *Rebuilding option content on every highlight change* — would put the reverse in the option's own Rich `Text`, which works, but re-renders the whole list per keypress to express a fact about one row.

## Opening balances are an engine concept (`@Opening` system category), not a CLI convention (2026-07-20)

**Context.** The user's real spreadsheet carries `SALDO INICIAL` rows — account starting balances. The engine had no opening-balance concept: `POST /accounts` takes no balance field, so the only route was an ordinary income transaction under a user-invented category, which permanently inflates reported income in the seed month with no way for the engine or any client to recognize it. The engine's `lessons-todoist.md` §7 shows "account initialisation with opening balance" was contemplated at design time but never shipped. Per this repo's own rule ("no CLI-only shortcuts — the pattern has to generalize to the next client"), a CLI-local naming convention was the wrong altitude: web/iOS onboarding hits the same problem on day one.

**Decision.** Engine-side (engine roadmap Step 9.4, engine commit `865ab0a`): `POST /v1/accounts/{id}/opening-balance` seeds the balance as an ordinary transaction under a third system category (`system_key = 'opening_balance'`, default name `@Opening`, renamable), and flow reports exclude it entirely — the `@Opening` row is hidden from category panels and its transactions contribute nothing to inflow/outflow/net, so visible rows sum exactly to net and no phantom income appears. One active opening per account (409); client-supplied `transaction_id` gives importer re-runs deterministic dedup. CLI-side: `expense accounts opening-balance` wraps the endpoint (contract-validator rule), and the importer routes rows marked `SALDO INICIAL` (case/whitespace-insensitive) to it — those rows skip the category/hashtag requirement, dedupe per (account, currency) keeping the first line, and surface distinctly in the dry-run. *(Widened 2026-08-20: the marker is read from the **title or the category** column. The real spreadsheet turned out to file its opening rows under a `SALDO INICIAL` category while giving them descriptive titles like `REGULARIZACION SALDOS`, so a title-only rule silently imported a -27,608 PEN adjustment as ordinary spending. Reading both columns costs nothing — the marker cells are discarded either way, so the category never materializes.)* Engine shipped first; the CLI stayed a thin wrapper throughout. A dedicated endpoint (not a param on `POST /accounts`) because the user's accounts already existed in production — creation-time-only seeding couldn't serve the import, and the CLI cannot mint system categories itself (`POST /categories` has no `is_system` input).

**Rejected.** *Plain user category (`Saldo Inicial`) + convention* — invisible to the engine forever, so reports could never exclude it, and N users would invent N unfindable names; no migration recovers that. *Routing through `@Transfer`* — transfers are zero-sum across two owned accounts; an opening balance has no source account and is income-shaped, not transfer-shaped. *(Moot since 2026-08-10: `@Transfer` was deleted with the engine's transfer feature.)* *`opening_balance_cents` param on `POST /accounts` as the v1 mechanism* — never fires for accounts that already exist, which is exactly the import case; kept as a possible future onboarding nicety on top of the endpoint. *Excluding from totals but keeping the `@Opening` row visible in panels* — visible rows would sum to `net + opening`, contradicting the totals line; hiding the row is the self-consistent option (user-confirmed).

## Local-first deployment — the one engine moves to the user's Mac; cloud mothballed until iOS (2026-07-30)

**Context.** The product is single-user for the foreseeable future (the 10k-user target is a someday-maybe, no longer a near-term design driver), and the cloud deployment made daily use slow: Render's free tier spins the engine down after idle, so the first command of a session eats a 30–60 s wake-up; `dashboard`/`reports` (engine-only reads — they were never served from the replica, whose drift policy is recorded in [cli-runtime.md](cli-runtime.md) "Read semantics") feel it hardest. Separately, the daily FX cron was never wired on Render (paid-only resource, deferred in engine `TODO.md` since 2026-04-28), leaving cross-currency PEN/USD writes blocked by `422 RATE_UNAVAILABLE` — and the user's ledger is exactly PEN+USD (engine migration `015_lock_currencies_to_pen_usd.sql`).

**Decision.** Move the *deployment*, not the architecture: the same engine runs on the user's Mac (launchd service) against local Homebrew Postgres, with a small stand-in for the Supabase-auth surface (PAT auth is engine-native and unchanged); the FX fetch (`app.jobs.fetch_exchange_rates`; provider swapped to fawazahmed0/currency-api during execution — Frankfurter turned out to serve ECB rates only, which exclude PEN, and the 15 pre-existing `rate=3.75` rows were wrong-by-~10% placeholders, deleted) runs as a daily launchd task — going local *unblocks* the feature the cloud never finished; a nightly `pg_dump` to iCloud Drive replaces Supabase as the durability layer (non-negotiable — with one machine, the backup *is* the ledger's survival); Supabase/Render are mothballed after a final full export. Every architectural invariant survives verbatim: exactly one engine as sole write authority, clients hold zero business logic, server-first writes with no offline queue, the §3b replica standard untouched — the CLI's only change is the `engine_url` in `~/.expense-config`. Reactivation on iOS day is a relocation: restore the latest dump into Supabase, redeploy the engine to a host, repoint clients; iOS then follows §3b (thin client + Todoist-style command outbox, engine still the only judge). Build order and specifics: engine `docs/roadmap.md` Step 11; ops procedures live as deployment profiles in the engine repo — `deploy/local/README.md` (active) and `deploy/cloud/README.md` (mothballed + reactivation checklist). A profile is a folder, not a repo: schema, logic, and sync protocol change together (every feature touches all three), so splitting "the scalable part" into its own repo was rejected as a false seam — only deployment config varies, and the engine is already stateless/env-configured precisely so deployments can swap without code changes.

**Rejected.** *Keep the cloud and keep it warm* (paid tier / scheduled ping) — fixes latency but leaves FX unwired without paid cron, still requires internet for every command, and rents complexity the solo phase doesn't need. *Local-first writes in the CLI with a last-write-wins queue (the Todoist client pattern)* — the engine's rulebook is thick where Todoist's is thin: writes trigger computed side effects (FX home-amount twins, transfer-pair creation and leg-locking, completed-reconciliation field freezes, chained-balance cascades), so optimistic local acceptance means either duplicating the engine per client or "saved" entries bouncing after the fact — acceptable for a to-do, not for a ledger; stays iOS-only per §3b where offline capture justifies it. *Porting the engine to SQLite ("just a local file")* — the validated core is written against Postgres (advisory locks, partial unique indexes); a port rewrites the money-handling layer and permanently forks local from the cloud future. *YNAB-style engine-in-every-client* — YNAB makes fat clients survivable by being merge-friendly by design (single-currency budgets, derived values recomputed never stored, warnings not locks); this product made the opposite trades deliberately, so multi-device merging would fight every one of them.

## Delete the local replica — all reads live (2026-08-06)

**Context.** The engine's deletion program (engine repo `docs/rework/`, WP4) removed `GET /v1/sync` and its `sync_checkpoints` table: it served an offline-capable client that never shipped, and it carried the engine's last dropped-writes bug (a write overlapping a sync could be permanently missing from a client's replica). The CLI was that endpoint's only caller — its cache-by-default read path (Step 7b, per the retired engine §3b replica standard) hydrated `~/.expense-cache.sqlite3` from `/sync` before every default-mode read. The invalidating event was 2026-07-30's local relocation (see the entry above): with the engine on loopback, a read is sub-millisecond, and the replica's only remaining value — hiding cloud latency — was gone, while its costs stayed: staleness windows after out-of-band writes, `current_balance_home_cents: null` drift on cached accounts, a dedicated error family (exit codes 4/5), and ~1,200 source LOC plus ~2,300 test LOC.

**Decision.** Delete the cache layer whole: `expense/cache/`, `expense sync`, the `--no-cache` / `--no-sync-after` root flags, `EXPENSE_STATELESS` / `EXPENSE_NO_SYNC_AFTER` / `EXPENSE_CACHE` env vars, `client_id` in `~/.expense-config` (the `X-Client-Id` header existed only for sync checkpoints; old config files still load — unknown keys are ignored), the TUI Sync screen, post-write refresh, and exit codes 4/5. The former stateless path is now the only path: every read is a live engine GET, and renderers resolve display names via live reference-list fetches that degrade to short ids on failure. Writes are unchanged (engine-direct, idempotency keys, bounded same-key retry). Sequencing: this landed *before* the engine deleted `/sync`, so the CLI never pointed at a 404.

**Rejected.** *Keep the cache, repopulate it via full REST fetches instead of `/sync`* — keeps every consistency cost and rebuilds, client-side, exactly the delta machinery the engine just deleted, for zero latency benefit on loopback. *Keep `--no-cache` as a vestigial no-op flag* — a flag that does nothing is a lie in the help text. *Wait and delete the cache together with a future mobile client decision* — the CLI would meanwhile break the moment engine WP4 landed, and rebuilding sync later is ~1–2 days of additive engine work on substrate (`version`, `updated_at`, tombstones, client UUIDs) that deliberately survives.

## Transfers are two ordinary transactions (2026-08-16)

**Context.** The engine deleted its transfer feature on 2026-08-10 (the auto-paired legs, the `transfer` request field, `transfer_transaction_id`, the leg-edit/delete cascades and the `@Transfer` system category all went at once). Every client surface built on it — `expense log --transfer/--to-account-id/--to-amount`, the TUI quick-log's conditional transfer branch, the batch-create transfer rejection, the transfer-pair edit guard, and several 422 hint strings — was dead weight or actively wrong.

**Decision.** Remove all of it rather than emulate it. A move between accounts is recorded as two ordinary transactions, each with its own explicit sign and its own category. This retires the sign convention's one sanctioned exception (the TUI's transfer "to amount" took a magnitude and auto-set the opposite sign); the rule is now literal everywhere, no exceptions. Local pre-checks that duplicated engine validation went too — the engine owns batch validation and its own error text.

**Rejected.** *A client-side "move between accounts" convenience that writes the two transactions for you* — not parity work, it is a new UX with its own failure mode (one leg lands, the other 422s, and the client has no transaction to make it atomic). Parked in [todo.md](todo.md) behind a mockup. *Keeping the flags as deprecation stubs that print a pointer* — a flag that only ever errors is help-text noise; the flat commands are a contract-validator surface, so they should show exactly what the engine supports.

## Reconciliation de-chaining — a batch is a statement period, ordered by its date (2026-08-16)

**Context.** The engine deleted reconciliation chaining at the root on 2026-08-06: the cascade that re-derived a batch's beginning balance from the batch above it had no status predicate, so editing an upstream *draft* silently rewrote a *completed* batch's opening figure. `beginning_balance_source`, `chained_from_reconciliation_id`, `sort_order` and `PUT /accounts/{id}/reconciliations/order` went with it; `beginning_balance_cents` became required and `difference_cents` — the add-up check — was added. The client had not followed: every TUI create 422'd (the form defaulted to `source: "chained"`), and `reconcile move` / `reconcile reorder` 404'd on every call.

**Decision.** Follow the engine's model rather than preserve the old UX. Both balances are typed off the paper statement — one straight form, no chained/manual fork, no `--source` / `--sort-order`. `--date-start` becomes **required on create** even though the engine still accepts a null: a batch's start date is now the only thing that positions it, so an undated batch is one the user cannot order, and refusing it up front beats silently sorting it last. `move` and `reorder` are deleted outright — repositioning is `reconcile update <id> --date-start <date>` — taking `expense/_editor.py` (the `$EDITOR` shell-out, reorder's only consumer) with them. `difference_cents` surfaces on both list surfaces and the TUI working screen: sign-colored when the batch is off, a dim em dash when it balances, and always a literal number in the flat CLI table, which gets piped.

**Rejected.** *Rely purely on server order in the TUI browse, deleting the client sort* — the browse does **one unscoped fetch** and slices per account client-side, and only *account-scoped* reads come back in statement-date order (the cross-account list is `created_at DESC`), so this would have left the pane in creation order. The per-account slice mirrors the documented server key instead. *Refetch account-scoped on every account-cursor move* — correct ordering for free, but it turns an instant `↑↓` into a network round trip per keystroke. *Keep `move`/`reorder` as stubs that explain the new model* — same reasoning as the transfer flags above. *Keep a client-side "chained" convenience that prefills the begin from the previous batch's end* — that is the deleted engine feature reimplemented in the client, and it would re-create the exact bug the engine removed (a stale prefill against a completed neighbor).

## Home aggregates are nullable — `3 unrated` is a state, not a number (2026-08-16)

**Context.** The engine's 2026-08-05 read-time-currency change did three things at once. It **deleted** the native cross-account aggregates (`spent_cents` per category and hashtag combo; `inflow_cents`/`outflow_cents`/`net_cents` on month totals) — `GROUP BY category_id` has no currency partition, so a category holding $15 and S/25 reported `4000`, a number in no currency. It made every surviving `_home_cents` aggregate **nullable**, paired with an `unconverted_count`: when any row in a group falls on a date with no resolvable rate the engine refuses to report a partial total. And it dropped `/dashboard`'s `archived_categories` / `archived_hashtags` panels. The client had not followed, and this was the last live-broken surface: `expense dashboard` printed `(null)` for the spend of **every** category — that column is its only amount — the TUI Outstanding tree was entirely blank, every Totals block printed `(null)` in its left half, and `--include-archived` rendered two panels that could never fill again.

**Decision.** One amount column everywhere, named `Home`, and a `null` renders as **`3 unrated`** — the count, in the cell — never `0.00` and never a native-currency fallback (that fallback is the exact deleted bug: `COALESCE(amount_home_cents, amount_cents)` read USD cents as PEN cents, a 3.58× understatement). One shared pair of helpers, `format_aggregate` / `has_aggregate` in [_resource.py](../expense/commands/_resource.py), backs the CLI and the TUI alike, with `aggregate_cell` as the palette-colored TUI wrapper. Month-grid cells became dicts carrying the count, because `None` alone cannot distinguish *no activity* from *the engine refused to price this* — the conflation that made an unpriceable January indistinguishable from a month you spent nothing. Two rules go beyond what the engine forced, both user decisions of 2026-08-16: **a category or hashtag with nothing spent is not drawn at all** — the engine returns every non-deleted category whether or not it has activity, and a report is not a category list (`expense categories list` still shows every one; `--json` is untouched) — and **the TUI home header hides every figure behind the error**, showing only `4 UNRATED` until the rates are fixed, counting unpriced transactions and unpriceable people together as one list of work.

**Rejected.** *Leaving the `owed to you` figure alone* (sketch option I) — the engine change did not force it, but the header was silently dropping people whose balance could not be priced, so the number looked right and was too low; a wrong figure that looks right is worse than a visible error, which is the same reasoning that killed the `COALESCE` fallback. *Marking only the broken figures and keeping the rest* (option G, a `+` suffix on a partial total) and *one warning badge beside the surviving figures* (option H) — both still put a half-true number on screen. *A one-character marker with the count in a table footnote* (option B) — it buys no width, since the column is still as wide as the amounts, and it loses which row the count belongs to. *`n/a (3)`* (option A) — 2 characters narrower than `3 unrated` but an abbreviation to learn, and the count reads second. *Keeping the `Spent`/`Home` column pair with `Spent` blanked* — that is the deleted number given a permanent empty column.

## Contract tests verify against a disposable database, and refuse the real ledger (2026-08-16)

**Context.** Phases 1–4 repaired the client blind. `tests/unit` is respx-mocked, so it validates the CLI against fixtures the repo itself wrote — it stayed green through the entire 2026-08 rework while pinning fields the engine had deleted. The only thing that sees the real contract is `tests/contract`, and it had drifted badly: three of its five modules signed in as the developer through `~/.expense-config` and wrote to the one true ledger, two still defaulted to the Render host switched off 2026-07-30, and its cleanup is soft-delete — so every run permanently buried tombstones in real data. That was not theoretical: leftover rows from a 2026-07-30 run had already pushed an account listing past its 50-row page and made a test flaky, and on 2026-08-16 a mis-scoped gate ran the suite against the real ledger and left four live junk accounts behind.

**Decision.** The suite runs against `expense_world_test` — the database `deploy/local/create-test-db.sh` already built for the engine's own tests — through a **second, manually-started engine on `:8001`**. Same engine code, so it is still a real contract test; different database, so nothing it writes can reach the ledger and the debris is disposable. `deploy/local/seed-test-user.sh` (engine repo, beside the script that builds the database) seeds a practice user, one PAT and a copy of `exchange_rates`, which is global reference data carrying no `user_id`. And the suite **refuses to start** when it would write to the real ledger — `EXPENSE_ALLOW_REAL_LEDGER=1` to override — implemented as a `pytest_sessionstart` hook rather than a fixture, with the `PYTEST_LIVE` gate as a `pytest_collection_modifyitems` hook rather than a `pytestmark` (a `pytestmark` in a conftest does not apply to other modules — that mistake is what caused the 2026-08-16 incident). Three guard shapes were drawn on 2026-08-16 — a printed warning, an abort-on-fixture, and refuse-the-session; the last is what shipped.

**Rejected.** *Printing a warning banner instead of refusing* (sketch options A and B) — both only help someone who is reading the output, and the moment this matters is the moment nobody is watching; the incident happened during an automated verification step, not an interactive session. *Keeping the real ledger as the target and accepting the tombstones* — that is the status quo whose debris had already caused one flaky test. *A separate PAT for a separate user in the same database* — real isolation between users, but the junk still accumulates in the production database forever. *Folding the fixture-drift check into `pytest tests/unit`* — the unit suite blocks real sockets on purpose ([tests/unit/conftest.py](../tests/unit/conftest.py)), and that hermeticity is worth more than the convenience; it ships as [scripts/check_fixture_drift.py](../scripts/check_fixture_drift.py) instead.

## A settled person is folded, never hidden — and creating one is a TYPE field, not a `people` group (2026-08-16)

**Context.** The engine shipped `POST /people` on 2026-08-14, closing a gap that had been open since `sql/003`: `is_person` existed and every *read* surface for people was shipped and tested — `accounts list --include-people`, the dashboard `people` panel, the TUI Outstanding table, the home banner's `owed` figure — but no endpoint could ever set the flag, so the People panel was structurally empty. A shipped, tested section that could never contain anything. Three client questions came with it: what creates a person, where archived people go, and what happens to a person once her debt clears and her balance reads `0`. All three were drawn before any code and answered by the user on 2026-08-16 — the answers are the Decision below.

**Decision — creation.** `expense accounts create-person` (pick B), and in the TUI a **TYPE field** (`bank` / `person`) as the first field of the existing New Account form, **prefilled to `bank`** (pick L). `is_person` is never sent on either surface: it is a `422` on `POST /accounts` *and* on `POST /people`, so the endpoint **is** the flag. Both choices follow from the same engine fact — `POST /people` is the only people route there will ever be, because `is_person` is settable only at creation; rename, recolor, archive, unarchive, delete, restore and fetch are all account routes that have always accepted person rows. The TUI's edit form therefore locks TYPE read-only, exactly as it already locks `currency`.

**Decision — settled people.** Folded behind a count, never dropped: `▸ 3 settled` on the typed dashboard (pick G), and the same fold made interactive in `expense world` — `PeopleView`, reusing the categories tree's carets and keys (pick J). "Settled" is **exactly zero in the person's own currency**, never the home-converted figure, and never an unknown balance; `split_settled` / `settled_label` in [_resource.py](../expense/commands/_resource.py) are the single copy. Archived people are their own panel after `archived_accounts`, both at the bottom (pick D), and are not folded.

**Why the fold rather than a filter.** The engine was asked to hide settled people and refused (owner decision, 2026-08-13), for three reasons the client inherits: "she paid me back" and "I never recorded the loan" would look identical; people would flicker in and out of the list as rows land; and a coincidental net zero (lent 200, borrowed 200) is *two live debts*, not nothing. Decluttering is explicitly delegated to clients, and the count line is what keeps the delegation honest — the panel never silently omits someone. Note this is deliberately the **opposite** of the Phase 4 flow rule (`has_aggregate`, "rows with nothing spent are not drawn"): reports group over what happened, balance surfaces enumerate what exists.

**Rejected.** *`expense people create` as its own group* (sketch A) — a group named `people` promises a set of people commands, and there is exactly one forever; every reach for `people list` would read as a missing feature rather than a deliberate absence. *`expense accounts create --person`* (sketch C) — one command silently posting to two endpoints with different `sort_order` scoping and a different opening-balance rule, which is the pattern this repo has removed everywhere else. *Merging archived people into `archived_accounts`* (not offered) — ruled out by the engine's own record: an archived person among the archived cards. *Archived people under the live People panel* (sketch E) — splits the two archive panels and puts one flag's effect in two distant places. *Printing every settled person* (sketch F/K) — after a year of small loans the two people you actually owe are buried among a dozen zeros, and on the TUI screen the panel sits above the month's spending and pushes it down. *Naming them on the fold line, `▸ 3 settled (Ana, Beto, Caro)`* (sketch H) — the line grows with the count and eventually needs its own truncation, reintroducing the same hiding by another door. *A second key `p` for a new person* (sketch M) and *a chooser screen in front of `n`* (sketch N) — a second key on a screen already using `n`/`e`/`a`, and a whole extra screen plus a new widget kind in front of the page's most common action; the prefilled TYPE field costs a keypress you were already pressing.

## The inbox has no deleted view — `--include-deleted` is paired with `restore`, and the inbox has none (2026-08-16)

**Context.** Six `list` commands accepted `--include-deleted`; four rendered a `Deleted` column and two — `inbox` and `transactions` — did not, so a deleted row came back looking exactly like a live one and the only way to tell was re-running with `--json` and reading `deleted_at`. That was the backlog item. Reviewing it surfaced the sharper question the item had not asked: *why does the flag exist at all?* It exists to feed `restore` — you list deleted rows to find the id you want back. Every resource carrying the flag has a `restore` command **except the inbox**, whose restore route the engine removed on 2026-08-14 (`inbox delete` is documented as final). So `inbox list --include-deleted` could only ever surface dismissed drafts that cannot be restored, edited or promoted.

**Decision.** Two different answers for the two lists, because they are not the same case. **`transactions list`** keeps the flag and gains a `Deleted` column, rendered **only when the flag is passed** and placed **last**, matching accounts/categories/hashtags. **`inbox list` loses the flag entirely** — the parameter is gone from the command and from `fetch_inbox`, so the CLI never sends `?include_deleted=true` to `/inbox`, even though the engine still honours it. The user's framing settled it: deleted rows should not be shown without a reason, and for the inbox there is no reason left.

**Why keyed to the flag, not to the data.** A third option was drawn — show the column only when a deleted row is actually present — and rejected: it makes the same command print a different header on different days depending on what happens to be in the ledger. Keying it to the command line keeps a given invocation's column set stable. `--json` is unaffected by any of this; it passes the engine body through whole, `deleted_at` included, on every list.

**On the contract-validator rule.** Dropping a parameter the engine supports cuts against "the CLI exercises every engine endpoint", so it is recorded rather than silent: `?include_deleted=true` on `GET /inbox` is the one query parameter no CLI surface sends. It is a parameter, not an endpoint, and the same parameter stays exercised on five other resources — but if a future client needs the inbox's deleted view, this entry is why it is missing here.

**Rejected.** *A `Deleted` column on the inbox too* — decorates a flag with no purpose. *Leaving the inbox untouched* — keeps a flag whose rows are inert, which is the thing being complained about. *Always-on `Deleted` columns everywhere for consistency* — puts a column reading `no` on every ordinary listing you ever run, to serve a recovery view you reach for rarely.

## One word for hashtags — the engine's, everywhere (2026-08-16)

**Context.** The tag column was labelled `Tags` in `inbox list` and `Hashtags` in `transactions list`, while [cli-spec.md](cli-spec.md) claimed both said `Tags` — three sources, three stories. The inbox code even carried a comment claiming it matched `transactions list`, which it did not. Noticed because Phase 8 had to edit those exact two header dicts.

**Decision.** One word, and it is the engine's: **`Hashtags`**. The engine names the resource `/hashtags`, the field `hashtag_ids` and the filter `?hashtag_id=` — "tags" appears in its spec only as loose prose. Where the client and the engine disagree on a name, the engine wins, so clients two and three inherit one vocabulary instead of a per-surface dialect. Applied to all four surfaces: both CLI tables and both TUI screens (`transactions.py`, `inbox.py`), plus the spec line and the misleading comment.

This **reverses the label half of the 2026-08-16 hashtag-column sign-off**, which chose `Tags` for the inbox. The *position* it chose — last on both lists, before the status marker in the TUI — is untouched; only the word changed.

**Rejected.** *Aligning on `Tags` and correcting the engine's vocabulary in the client* — shorter and friendlier, and it is what the spec already claimed, but it puts the client's word in front of the engine's on every screen while the wire format keeps saying `hashtag_ids`; the next client would have to make the same choice again with nothing to point at. *Leaving both and correcting the spec to admit the difference* — cheapest, changes nothing you see, and permanently ships two names for one thing.

## The light theme will detect the terminal, not ask the user (2026-08-16)

> ⛔ **Reversed 2026-08-19 — never implemented.** See "The terminal supplies the
> palette" below: the app now takes its colours from the terminal's own ANSI
> slots, so there is nothing to detect. The `OSC 11` query, the `COLORFGBG`
> fallback, the `select()` timeout and the second hand-tuned palette are all
> deleted from the plan. Retained as the record of what was considered and why
> the cheaper answer was missed for three days: every option below argues about
> *how to choose between two palettes we author*, and none asks whether we
> should author them at all.

**Context.** The TUI runs in ANSI mode, so the base surface is already the terminal's own (2026-07-11, "TUI paints the terminal's own background"). What is still missing is the other half: one dark-tuned *foreground* palette, hard-coded at mount, unreadable on a light terminal. The open backlog item pairs a light theme with a `NO_COLOR` path. The implementation stays open; only the approach is settled here, so whoever picks it up is not re-deciding it.

**Decision.** **Auto-detect.** On startup the app asks the terminal what its background colour is — the `OSC 11` query, with `COLORFGBG` as fallback and dark as the final default — computes luminance, and selects the palette that reads on it. No setting to manage, and it follows the user between terminals.

**What makes it non-trivial, recorded so the estimate is honest.** **Textual ships no such detection** (verified in 8.2.7: no `OSC 11` query, no `COLORFGBG` read anywhere in the package). `App.ansi_theme_dark` / `ansi_theme_light` sound related and are not — they pick an ANSI→truecolor conversion table from *your* theme's `dark` flag, never from the terminal. So the query is hand-written, and it must run in `run_world` **before** Textual takes the tty, with a `select()` timeout, because a terminal that never answers must not hang the app. Two existing guards constrain the result: `test_base_fills_are_terminal_transparent` (a light theme must not paint a base surface — that is the seam rule, unchanged) and `test_theme_change_rebuilds_section_screens` (setting `self.theme` after screens are up must rebuild without re-fetching). `NO_COLOR` remains a third mode, not the light theme — a full native-ANSI `Theme(ansi=True)`, already parked in the ANSI-mode entry above.

**Rejected.** *A remembered setting in `~/.expense-config`* — simpler, predictable, no terminal interrogation and no timeout; rejected because it is one more thing to configure and it does not follow you between terminals, which is the whole point of a surface that already adapts. *Deriving light/dark from `theme.dark`* — circular: that is the value being chosen. *Shipping the light palette with no selector, switchable only via `ctrl+p`* — leaves the default broken on a light terminal, which is the actual complaint.

## The command palette is removed, not populated — `?` is the one discoverability surface (2026-08-17)

**Context.** Two Phase 8 items sat next to each other: a `?` help overlay that did not exist, and "populate the Textual command palette". Auditing them first turned up two things that reframed both. **The palette was already advertised** — Textual's `Footer` renders a `^p palette` key on the right by default, gated on `ENABLE_COMMAND_PALETTE`, so it was discoverable and merely empty of our commands. And **a keys panel already existed**: Textual 8.2.7 ships `HelpPanel` + `action_show_help_panel`, reachable via `ctrl+p → Keys`. So the real question was never "build from nothing" — it was *curate, or accept Textual's*. Both were captured against our own binding set rather than argued from memory.

**Decision.** **Remove the palette** (`ENABLE_COMMAND_PALETTE = False`) and give `?` a card we own — variant C, a two-column `HelpModal`. What the palette actually offered was five commands: `Quit` (`^q` already does it), `Maximize` and `Screenshot` (Textual dev affordances), a `Theme` picker over **22 registered themes when we ship exactly one** (`THEMES = [EXPENSE_DARK]`; the other 21 are Textual's built-ins we never designed against), and `Keys` — the one useful entry, which is precisely what `?` replaces, curated and themed. Removing it also drops the `^p palette` strip from every footer for free, because `Footer` gates that key on the same flag; no footer code was touched. Nothing depended on it: the only two references in the repo were prose, a docstring in `theme.py` and one in `test_tui_theme.py`.

The card's content is **derived, not hand-listed** — it walks the screen's and the focused widget's MRO and keeps only BINDINGS declared by classes under `expense.tui`. That filter is what keeps Textual's `home`/`end`/`tab`/`Copy selected text`/`Page Left` out **without a suppression list that would rot** as Textual changes. Three consequences worth knowing: `Binding.tooltip` carries the card's fuller wording while `description` stays the terse footer label, so one declaration serves both audiences; a `show=False` inverse folds onto its partner's row (`j / ↓  Down  (k / ↑ up)`) instead of becoming the blank-description row Textual's own panel prints; and a widget key the screen cannot service is **dropped**, so the Manage lists are not told `⏎ Open` when `enter` is a literal no-op there (§4.1 contract). `tests/unit/test_tui_help.py` is the guard — a binding declared with neither description nor tooltip fails the suite, which is the drift that made the footer misleading in the first place (four of the Accounts screen's own five keys never reach it).

`?` is bound per screen root via `HelpBindingMixin`, **never on the App** — letters bubble up from lists, so an app-level `?` would fire from inside a `ConfirmModal`, the same reason there is no app-level `q`. Forms get **no help key at all**: a focused `Input` swallows printable keys, so `?` there types a question mark. That is the wanted behaviour (forms already show `^s`/`esc` in their footer), and it is pinned by a test so a later app-level binding cannot quietly take the key away.

**Rejected.** *Binding `?` to Textual's built-in `action_show_help_panel`* — about three lines and it ships today; rejected because it lists seven rows of internals we never bound, prints `show=False` aliases as rows with an empty description, groups nothing, states none of the cross-screen conventions, docks right and squeezes the content to 33 columns, and is styled by Textual rather than through `resolve_palette`. *Populating the palette with a `Provider`* — navigation-only, or navigation plus the active screen's actions; more work than removal and it keeps both the theme picker and the footer strip. *A palette listing every screen's actions* — drawn in the mockup (§3, variant K) specifically to show why it cannot work: an action from a screen you are not on needs navigation **and** a selected record first, and some entries have no binding anywhere, so the list either lies or needs a per-action availability rule. *A one-column card (B)* — same content, roughly double the height, no room for the conventions block. *A full Help screen (D)* — the only shape that can carry the whole app's keymap at once, but it replaces the view instead of hovering over it, so you cannot read it against the list you were looking at.

**Knock-on.** The entry above, "The light theme will detect the terminal", lists as a rejected alternative *"shipping the light palette with no selector, switchable only via `ctrl+p`"*. That escape hatch no longer exists — which strengthens rather than weakens the auto-detect decision it was rejected in favour of.

## The terminal supplies the palette — every colour is an ANSI slot (2026-08-19)

**Context.** 2026-07-11 made the *ground* the terminal's own and stated, in this
file and twice in its mockup, that it did not make the app readable on a **light**
terminal — the foreground hexes assume a dark ground. 2026-08-16 answered that
with detection: query the terminal's background over `OSC 11`, compute luminance,
pick between two palettes we author. While scoping that build the user asked the
obvious question nobody had: *why detect at all — why not just use the terminal's
own colours?*

**Decision.** **Nothing is detected.** Every colour in
[theme.py](../expense/tui/theme.py) is an ANSI **slot** — `ansi_green`,
`ansi_red`, `ansi_blue`, `ansi_bright_black`, `ansi_default` — on a single
`Theme(ansi=True)`. `green` is not a colour, it is slot 2, and the terminal
decides what goes in it: a dark profile fills it bright enough to survive black, a
light profile darkens it to survive white. The person who configured the terminal
already made this decision and every other TUI on their machine already honours
it. Result: correct on dark, light, Solarized, Gruvbox, high-contrast — a wider
target than the light/dark binary detection could ever reach — for a `removeprefix`
instead of a hand-written terminal query. Picks from
[mockups/expense-world-ansi-palette.html](mockups/expense-world-ansi-palette.html):
**C** pending is `bold` with no colour (slot-3 yellow is the one slot that
reliably fails on white, and the app already speaks bold/dim/reverse in ~40
places); **D** accent `ansi_blue`; **F** structural rules `ansi_bright_black` via
`$secondary`; **H** modal card opaque, dim scrim kept; **K** `NO_COLOR` dropped as
a separate mode — the terminal owns colour now, and the flat CLI honours the
variable on its own.

**The cost, which is real.** The app no longer looks the same on every machine,
and on a stock profile the sign colours are louder than the sage-and-rose that
were approved in 4.2. That trade was put up first in the mockup, before any
option, and accepted deliberately.

**Three things only a render caught.** `$surface`/`$panel` *generate* to
`transparent` under an ANSI theme, so the header rule, the quiet list border and
the modal card were all invisible or see-through — hence `$secondary` for rules
and a literal `ansi_default` for the card. Alpha is **dropped** on `ansi_default`,
so the modal scrim silently became an opaque fill that *wiped* the screen behind
it — a bug every unit test passed; the scrim is now a literal `black 60%` and
`test_modal_scrim_dims_rather_than_wipes` asserts on composited output. And an
`ansi=True` theme must ship Textual's full `variables` block (its own `Screen` CSS
references `$ansi-background`); ours resolves cursors as **reverse video** rather
than adopting either built-in's light- or dark-specific colours — refusing the
same binary in the one place Textual still assumes it.

**Rejected.** *Detection* — see the superseded entry above; it authors and
maintains two palettes to approximate what the terminal already knows exactly.
*A stored setting* — rejected there too, and even more clearly now. *Keeping the
tuned palette on dark and adding ANSI only for light* — two code paths, the
brittle detection back again, and the light path still unowned by any design.
*Registering Textual's own `ansi-dark`/`ansi-light`* — they disagree on `warning`
and `accent` precisely because they encode the light/dark split this decision
refuses; adopting them would reintroduce the choice through the back door.

## A terminal too small is the user's to fix (2026-08-20)

**Context.** The last open TUI decision asked whether to refuse or fall back below
some minimum size. The docs recorded it as half-answered — *"the app degrades
rather than refuses, `PAGE_ROWS_FLOOR = 5`"* — so closing it started as a
formality. Measuring it first showed the premise was wrong twice, and that is the
part worth keeping. Captures and the sweep:
[mockups/expense-world-min-terminal-size.html](mockups/expense-world-min-terminal-size.html).

**What the app actually does.** It is fully correct at **80×24** and comes apart
below that, silently, in two unrelated ways. *Horizontally*, every row keeps being
drawn while the columns collapse: truncation starts around **w=75**, by w=50 the
title is a bare `…` and the amount `-…`, and by w≤40 the date goes too. This is the
dangerous one — the panel closes, the footer is intact, nothing looks broken, and
the app is confident and wrong. *Vertically*, rows are clipped rather than
reflowed, and **the threshold moves with the page size**: a 4-row page keeps its
bottom border down to h=18, a full 8-row page has already lost it at h=20. At h≤10
there are no data rows at all, while the footer still offers to page through them.
Neither failure is announced.

*(Measured twice. The first write-up of this entry asserted "clean to 80×22" and
"columns collapse from w=50"; re-probing showed truncation actually starts at ~75
and the height threshold is not a constant at all. Numbers above are the second,
verified pass — worth recording because the whole point of the entry is that the
previous claim went unchecked for four days.)*

**Decision.** **No guard.** No launch-time refusal, no in-app notice screen, no
warning banner. The terminal is the user's to size, every TUI degrades somehow, and
this has never been hit in real use — a size guard would be code, tests and a new
screen state bought against a problem nobody has. **80×24 is documented as the size where
everything is correct, and 60×20 as still-workable-but-lossy** (columns ellipsised,
every row present) — but nothing enforces either. What *does* change is the record: tui-plan §9 #5
and the `PAGE_ROWS_FLOOR` comment both asserted a protection that does not exist,
and both now state the measured behaviour instead.

**`PAGE_ROWS_FLOOR` is not what its name suggests.** It is a floor on the page size
we *request*, not on what the viewport can show. Below a ~18-line terminal it
guarantees rows are fetched and then clipped off the bottom — it prevents nothing.
Width has no floor of any kind: no constant, no clamp. Both facts are now written
at the constant itself.

**Rejected.** *Refuse at launch* (a size check beside the tty guard in `run_world`)
— four lines and the cheapest to build, but it refuses terminals that are still
readable and says nothing in the commoner case, shrinking the window *after* launch.
*An in-app notice screen* that replaces the content below the threshold and restores
on resize — the best of the three, and the one to build if this ever becomes a real
complaint; rejected now only on cost, since it needs a new screen state and its own
tests. *A persistent warning line* — cheap and takes nothing away, but it spends a
row on the screen with fewest to spare and leaves the misleading render underneath
it. If this is revisited, revisit the notice screen; the threshold to wire it to is
already measured.

---

## Logging is a key, not a menu row — plain `+`, and the footer stops naming the arrow keys (2026-08-20)

**Context.** Two asks landed together, both about the same thing: the surfaces you
pass through on the way to writing a transaction down. `Log a transaction` was the
first row of the home menu, which made the most frequent action in the product
also the one with the most steps — open the app, move the cursor, press enter. And
every list footer opened with `↓ Navigate`, spending its leftmost slot on the one
key nobody has ever needed told (*"its obvious and it just occupies space
unnecessarily"*). Mockup and the measurements behind it:
[mockups/expense-world-plus-and-arrows.html](mockups/expense-world-plus-and-arrows.html).

**Decision.** The menu row is **deleted** and replaced by **plain `+`**
(`LogTransactionMixin`, [_base.py](../expense/tui/screens/_base.py)), bound on
Home, Transactions and Inbox — the three screens where "and now write one down" is
the obvious next thought. It always opens the same empty form posting to
`/transactions`: one key, one meaning, on every screen that has it. Separately,
the `Navigate` binding on `CursorList`, `CheckList`, `CategoriesView` and
`MonthGridView` becomes `show=False` — the keys are untouched and the `?` card
still lists them, which is where a key that needs explaining belongs.

**Rejected — `shift`+`+`, because a terminal cannot send it.** The first proposal
was a modified key, to be safe against collisions. It is not bindable: for a
printable key the shift is already baked into the character the terminal emits (on
a US layout the main-row `+` *is* shift+`=`), so no modifier survives to be
reported. Textual states it in `keys.py` (`key_to_character`: *"Keys with
modifiers don't come from printable keys"*). Plain `+` needed no defending anyway —
probed on the live app, `active_bindings` had no `plus` entry on any screen,
pressing it did nothing, and none of the three hosts has a text input for a stray
`+` to fall into. It also arrives from the numpad and the main row as the same
byte, so one binding catches both.

**Rejected — `+` creating an inbox draft when pressed inside the Inbox.** Tempting,
because **the TUI still cannot create an inbox draft at all** — the Inbox screen
only filters, promotes, deletes and edits, and `expense inbox add` is the only way
in. But making one key write to two different endpoints depending on where you
stand is the one thing you cannot tell by looking at the key. The gap is real and
deliberately left open ([todo.md](todo.md)); the shape it should take if it is ever
closed is `n New`, which is already the convention on every other list screen
(`_base.py` `ResourceListScreen`).

**Not done — the arrow keys inside the edit form.** The same session asked for
plain `↑↓` to move between fields, then for `shift+↑↓`, then deferred the whole
item. Two findings are worth keeping for whoever picks it up. `shift+up` /
`shift+down` **are** bindable — arrows are not printable, so the terminal sends a
distinct sequence (`CSI 1;2A`), Textual maps it, and a live probe with a focused
`Input` fired both without typing anything into the bar. And the form's existing
`^↑ Prev field` / `^↓ Next field` are almost certainly **dead keys on macOS**:
`⌃↑` is Mission Control and `⌃↓` is Application Windows, claimed by the OS before
the terminal sees them. The form has been advertising two keys that never worked.

**Half of it shipped 2026-08-24: the form footer stopped advertising them** — along
with the plain `↑ ↓` rows, which the 2026-08-20 footer trim had applied to the list,
tree and checklist widgets but missed on the forms. The footer now reads
`esc Cancel  ^s Save` and nothing else. All four keys stay **bound**
(`Binding(..., show=False)` in `form_bindings`), which is the call worth recording:
*un-advertise, do not unbind.* They genuinely work for anyone who has turned Mission
Control's shortcuts off in System Settings, and no replacement has been picked yet —
so deleting them would remove working behaviour to fix a labelling problem.
*Rejected: deleting the two bindings outright* (loses that behaviour for no gain, and
orphans `action_field`, which the replacement key will want). Guard:
`test_form_navigation_keys_are_not_advertised`. What remains open is only the J/K
choice above.

---

## One key per job — `j k h l , .` deleted, and the month window moves to `pgdn`/`pgup` (2026-08-27)

**Context.** The user asked for a conflict sweep of every TUI shortcut, then for an
inventory: *"Where do we use J K H L and why do we have pgdn , []??? ... i want to keep
it ULTRA SIMPLISTIC and then using it ill come up with more shortcuts."* The sweep found
no live conflict, but it found ten movement keys doing the work of four. Read out of
source and drawn per key family in
[mockups/expense-world-movement-keys.html](mockups/expense-world-movement-keys.html),
the test applied to each was: **if it vanished tomorrow, what becomes unreachable?**

**Decision.** Two groups, opposite answers.

*Deleted — six keys, zero capability lost.* `j`/`k` were a second name for `↓`/`↑`,
`h`/`l` for `←`/`→`, `,`/`.` for `pgup`/`pgdn` — same action, same line of code, and
none of them printed their own letter in the footer. The reason to remove them is not
tidiness: a widget alias silently outranks a screen binding, so `j k h l` were
*unusable* as command letters on any list screen. Deleting them hands four letters back
to the command namespace, which is what the user asked the inventory for.

*Kept — `pgdn`/`pgup` are load-bearing.* On the four fetch-paged screens the arrows
clamp at the fetched edge on purpose (2026-07-13, below), so no arrow reaches page 2.
The user confirmed an external keyboard with real PgDn/PgUp keys, which is what makes
`,`/`.` safe to drop — on a MacBook they would have been the only *single-key* paging
(`fn+↓`/`fn+↑` otherwise) and deleting them would have made paging harder, not simpler.

*Moved — the month window rides the page keys.* `[`/`]` were the app's only
one-screen, one-job binding, and they existed only because the Monthly grid had already
spent `←`/`→` on expand/collapse. `pgdn`/`pgup` are unbound on that screen (the grid is
not a paged list) and already mean *"the next window of data"* — a month slide is that
same idea with 4 months instead of 20 rows. `pgdn` goes **older**, matching a
newest-first ledger where paging down walks back in time. Guarded by
`test_no_duplicate_movement_key_aliases` and `test_square_brackets_are_not_bound_anywhere`
in [test_tui_help.py](../tests/unit/test_tui_help.py).

**Rejected.** *`←`/`→` for the month window* (option A) — freeing them is genuinely
cheap, because expand/collapse already has a complete second door in `enter`/`space` on
all three tree views. But that grid *looks* like a tree: rows carry `▼/▶`, and a hand
pressing `→` on a `▶` row expects it to open, not to slide the whole window. Same
gesture, very different result. *`shift+←`/`shift+→` for the window* (option B) — works
and retrains nothing, but adds a third tier of arrow keys for one screen, and `⇧←` is
not discoverable by accident. *Keeping the vim aliases as "free" extras* — they are only
free until something wants the letter, and then the failure is silent. *Deleting
`pgdn`/`pgup` in favour of arrows that auto-page at the edge* — already rejected
2026-07-13 ("holding `j` to skim would fire a fetch per keystroke at every boundary");
that reasoning is unchanged. Note this entry is the mirror image of that day's
*`[`/`]` as page keys* rejection: the objection then was "same key, different meaning",
and it does not apply here — the report has no list, so `pgdn`/`pgup` acquire no second
meaning, they acquire their **only** one.

## The LOG bar shows the named account's ledger — elastic, and it stays put (2026-08-29)

**The ask.** *"Once i write a bank account, the lower part of the screen should show the
transactions table filtered to that bank account, so i can see where we are there."*
Sketched as [mockups/expense-world-log-account-peek.html](mockups/expense-world-log-account-peek.html);
three calls came back from it, and they are the entry.

**It is elastic (pick A), not a fixed strip.** `#peek` is `height: 1fr` and every widget
above it is `height: auto`, so Textual hands the panel exactly the rows the staged list
is not using and `AccountPeek` draws that many — a dozen or more while you type the first
line, fewer as the batch grows, none once the list fills the terminal. The panel
re-renders on its own `Resize`, which is what makes "as many as fit" a fact rather than
an estimate. The empty-state invitation ("Nothing staged…" and the example line) stands
down while the panel is up: the hint line already says what `↵` does, and those four rows
are better spent on the ledger.

**The account is the bar's, never a staged row's** — the user's own correction, and the
reason `_peek_target()` is written as four explicit cases. A picker open on an account
shows the *highlighted candidate*, so arrowing through `$sig` previews each account's
ledger and the disambiguation answers itself. An account token that resolves to nothing
shows no panel at all: that row is bound for the Inbox and there is no ledger to show.

**And it stays put (pick i).** `↵` clears the bar, so mid-batch there is no active
account — the panel keeps the last one the bar named until the bar names another. The
strict reading (no account in the bar, no peek) was drawn and rejected: it blinks the
panel off at every `↵`, which is exactly the moment you are typing a run of lines against
one account.

**No balance.** It was in the first draft — in the panel title, and again as a projected
`→ S/ 12,345.75 after this batch` that counted the staged rows in. The user cut both
("balance is not needed at all"), which also deleted the whole question of whether a
screen whose premise is *nothing is written until `ctrl+s`* may show a number that is not
true yet. The panel names the account and counts the rows; that is all.

**Cost: one debounced `GET /transactions?account_id=…` per account named**, cached for
the life of the screen, on the read the Transactions screen already makes. Names come
from the `QuickAddRefs` the grammar already loaded, so there is no second fetch. A peek
that cannot load says so in its own border and does not retry — it is a courtesy, and a
courtesy never interrupts the typing. A save invalidates the accounts it wrote to, so
the rows you just logged appear where they belong.

**Rejected.** *A fixed window (pick B)* — twelve rows always, in the same place, so the
eye learns one spot; it costs the staging list twelve rows even when it wants them, and
the panel is least useful exactly when the batch is long. *A one-line summary (pick C)* —
balance, month-so-far, last movement, no table at all; it died with the balance, and it
answered "where do I stand" without answering "did I already log this?", which is the
question you actually have while typing. *Making the panel navigable* — `↑↓` already
belong to the staged list, and a second cursor on the screen would have to be won and
released. It is a window, not a table you work in.

## The legend, the two picker gaps, and day+month dates (2026-08-29)

Three things the user raised while using the LOG bar. Drawn together in
[mockups/expense-world-log-legend-and-picker.html](mockups/expense-world-log-legend-and-picker.html);
a fourth ask in the same session (hashtags filtered to the category) is **not** built — see
the end of this entry.

**The legend is a fixed row, and `↵ stages the line` rides on it (pick A).** The grammar
was already on screen — as the `#hint` fallback — but only while the bar was empty, so it
vanished the moment you started typing, which is the moment you need it. It is now its own
permanent row: `$account · @category · #tag · ±amount · //note · when     ↵ stages the
line`. It **never changes**, which is the point: it describes the grammar, not the moment,
so nothing below it ever moves. Everything that *does* change — the amount echo, the
resolved date in words, how many names a token matches, loading/writing — stays on the
`#hint` row above it, and that row no longer repeats the grammar. This is also the first
place `//note` is written down anywhere the user can see it while typing.

*Rejected:* **B**, the four-row key block that spells out what `//` and the date words are —
it is the only shape that teaches rather than reminds, but four rows come straight out of
the account peek below it. That table now lives in this mockup instead. **C**, the live
checklist (each key lit while the line has that token) — a genuinely better idea and the
one recommended, declined in favour of a row that is the same every time you look at it.

**Two picker gaps, both real, both fixed.** Reproduced against the real ledger; note that
what was *not* broken is narrowing — `$BCP S` correctly cuts six accounts to two.
(1) **A bare sigil offered nothing.** `#` alone is one character, so the parser read it as
a title word and no picker opened: you had to guess a first letter before the app would
tell you what exists. A bare sigil now stands unresolved carrying *every* candidate, which
is exactly a picker's input, and it gets its own phrase (`"#" names no hashtag yet`) —
because that same string is the Inbox reason if the line is staged with the sigil still
bare. Consequence accepted: a stray `$` in a line is no longer silent title text, it is a
visible unfinished token. (2) **Accents hid names.** Matching was case-blind but not
accent-blind, so `#banos` found no `BAÑOS` and the row went to the Inbox for a tag the
user has. Folding is now one function, [quickadd/names.py](../expense/quickadd/names.py)
`fold()`, applied to the typed side and the stored side alike — so `#baños` still matches
itself — and it is shared by all three pickers that had their own `.lower()`: the grammar,
the edit form and the create forms.

**Day + month means this year.** `28Aug`, `28/Aug`, `28-Aug`, `28agosto`, `28ago`, `1set`,
`15DEC` — the separator is optional, the month is any prefix of its name from three letters
up in either language, and an explicit year still wins (`28Aug26`, `28/ago/2025`). Prefix
matching needs no abbreviation table and is unambiguous by construction: no three-letter
prefix reaches two different months (`mar` is March and marzo; `may` is may and mayo).

*Rejected:* **a bare numeric `28/08`**, the obvious sibling — because `1/2` and `1/4` are
things people write in a title, and a fraction silently becoming February is exactly the
class of error the grammar is built to avoid. The month must be letters. *(Open, not
decided: the spaced form `28 Aug`, which needs lookahead in the date branch rather than a
regex.)* Note the consequence of "this year" in January: `28Dec` will resolve to *this*
December, a future date, which routes the row to the Inbox as dated-ahead. That is visible
— the resolved date is echoed in words before anything is staged — and the user asked for
the current year explicitly.

**Not built: hashtags filtered to the category.** The engine has no link between a hashtag
and a category — tags are a flat global list joined only to transactions — so nothing in
the API can answer "tags used with `@SALUD`". The only source is the user's own history,
and reading all of it is the engine's job: a client would have to page thousands of rows
and guess from a window of them, wrongly, and web and iOS would each have to guess the same
way. It is on [todo.md](todo.md) as an engine ask (`GET /categories/{id}/hashtags`, most-used
first) with two drawn shapes — ranked or filtered — in the mockup, so the ask can go out
with a picture attached.


## Overview — one screen for stock and flow, a band capped at 5 that always reads today (2026-08-29)

**Context.** Reports had two entries. Outstanding Amounts drew bank accounts, people, a
category→hashtag tree for the current month and an inflow/outflow/net block; the Monthly
report drew a sliding four-month grid of the same categories. The 2026-07-08 entry above
had already named the overlap out loud — it rejected a single-month report *because
Outstanding Amounts already was one* — and then left both screens standing. The user
asked whether they could be one ("can we mix the amount outstanding with the monthly
report into a single one? maybe we do an upper pannel with outstanding amounts.."). Six
layouts were drawn and, unusually, **prototyped in real Textual against the real ledger**
rather than only sketched — which is how three of the decisions below were made:
[mockups/expense-world-reports-merge.html](mockups/expense-world-reports-merge.html),
picked §12.

**Decision.** One screen, **Overview** ([overview.py](../expense/tui/screens/overview.py),
`reports.py` renamed). A band of two `1fr` halves — Accounts left, People right — sits
above the unchanged four-month grid, which gains `inflow` / `outflow` / `net` rows from
the same [`build_range_grid`](../expense/commands/reports_cmd.py) the flat range table
renders, so `expense reports monthly --from/--to` gained the same two rows: one copy,
both surfaces. Outstanding's category tree, accounts table and totals table are
**deleted, not moved** — the grid's newest column already was that tree with three months
of context attached. Four things the prototype settled that a drawing could not: **(1)
the panels are lean** (`box=None`, no header row) — drawn boxed the way `outstanding.py`
drew them, the band costs 12 lines instead of 8 and `net` falls below the fold at 120×34,
so you see inflow and outflow and not the number they add up to; **(2) the left half
needs a 4-column gutter** — without it both `1fr` halves render `5,018.93Majo`, the
amount column butted into the neighbouring names; **(3) `pgdn`/`pgup` must be
`priority=True`** — `#content` is a `VerticalScroll`, and once the band made the card
taller than a short terminal the scroll container began handling those keys itself, so
the month window silently stopped moving on exactly the terminals where the card
overflows; **(4) each panel draws at most 5 rows, hard, with no fold** — the user's call
("i wont always have the 6 accounts un-archived… I can also always go to the accounts tab
and see all accounts there"), in the engine's own order, truncating **drawing only**:
nothing filters the fetch and the flat `dashboard` still prints every row. The title
reads `Overview · balances today · flow <first> → <last>` permanently, because the band
is always today's balances even when `pgdn` walks the grid back a year and there is no
balances-as-of-date endpoint — the label is the whole mitigation. `fetch()` makes both
failable reads in one worker and **either failure fails the whole screen** through the
existing error card; a half-populated Overview is a screen that looks right and is not.
Measured: fits whole at 120×34; at 100×30 nothing truncates and only `net` sits one line
below the fold, so **100×31 is the minimum for the entire report at once**.

**Rejected.** (1) **A `▶ n more` fold on a capped panel**, the way `▸ 3 settled` folds a
settled person — drawn in §12 and argued for on exactly that precedent; the user declined
it, and the distinction holds: an account is one tab away on its own screen, whereas a
settled person exists nowhere else. *(The settled fold is untouched and is still never
capped — expanding it shows every one of them.)* (2) **Ordering the cap by size** so it
always hides the least money — a sort, not a computation, so it was inside the rules, but
the engine's order is what every other list shows and a screen-local re-sort would make
the same accounts read in two orders on two screens. (3) **A left rail** (option C, the
one the user preferred longest) — it needs ~120 columns with the rail fixed at 38, and
the rail scrolls away leaving 38 dead columns unless the screen overrides `compose()` to
pin it; the user's own verdict retired it: *"this design is better suited for a proper
app"*, which is exactly right — it assumes horizontal room a terminal does not reliably
have, and it belongs to the web and iOS clients. (4) **Two stacked full-width panels**
(option F) — a 12-line band against A's 8, for space the grid wants. (5) **A one-line
folding strip** (option B) — the closed line has to summarise the accounts in one number,
and a mixed-currency sum is a number in no currency (the same reason the engine deleted
its native totals column on 2026-08-05). (6) **Native amounts on one line per kind**
(option E) — measured at 174 columns for six accounts. (7) **Dimming the band while the
window is off the current month, or asking the engine for balances-as-of-date** — the
first invents a state the data does not have, the second is engine work for a label's
worth of value. (8) **A partial render when one of the two reads fails.** (9) **Caching
the dashboard across `pgdn`/`pgup`** and refetching only on `r` — it forks the refresh
path in two and makes "the screen I just logged into" stale in one of them; revisit only
if the third round-trip is ever felt.
