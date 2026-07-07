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
