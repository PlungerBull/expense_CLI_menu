# TODO — the workpad

**The single open-work queue for this repo.** Nothing else tracks pending work.

Rules, unchanged from the backlog this file replaces
([decisions.md](decisions.md) "The open-work list holds only open work"):

- **Closed items get deleted**, not ticked and archived. Git history is the archive.
- Items marked **[UI]** change something the user sees and need an HTML mockup in
  [mockups/](mockups/) reviewed and explicitly picked before any code (CLAUDE.md
  "Mock every screen before building it" — showing is not approval).
- **Absolute dates only.** Never "recently".

**Nothing here is urgent and nothing is broken.** The flat CLI and the TUI are both
feature-complete against the engine; 960 unit tests green, contract suite 12/12
against the disposable engine on `:8001` (2026-08-20).

---

## Open — post-Step-9 ergonomics

Unblocked 2026-08-16 when the contract suite passed against a real engine, which was
their precondition. Land in roughly this order; none blocks another.

1. **Quick-add natural-language parser.** `expense $20 today #food` → parse amount,
   sign, date, hashtag and title from free text, dispatch to the flat `log` command.
   **Sign stays literal** (`$20` = income, `-$20` = expense) — no default-to-expense
   magic, ever. This is the "low-friction capture" half of the dual-UX strategy; the
   TUI is the "discoverable management" half ([decisions.md](decisions.md)).
   **[UI]** — the *feel* is already drawn ahead of the grammar, all speculative with
   no pick recorded: [mockups/quick-add-bar.html](mockups/quick-add-bar.html) (token
   highlighting + resolved pills),
   [mockups/quick-add-launcher-options.html](mockups/quick-add-launcher-options.html)
   (what appears on the hotkey), and state **d** of
   [mockups/expense-world-log-quickadd.html](mockups/expense-world-log-quickadd.html)
   (one line parsed into every field — states a–c are the bar-cycle form that ships).

2. **Shell completions** — zsh, bash, fish. `expense <TAB>` shows commands,
   `expense auth <TAB>` shows subcommands. Lowest-effort discoverability win for the
   flat path.

3. **Human-name resolution for reference flags.** Accept either a UUID or a
   human-readable name on every `--account-id` / `--category-id` / `--hashtag-id` /
   `--reconciliation-id`. Client-side lookup via the existing list endpoints:
   case-insensitive exact match, ambiguous matches rejected with a "be more specific"
   error pointing at `expense <resource> list`; UUIDs pass through unchanged.
   Significant feature — deserves its own plan-mode session.

4. **"Move between accounts" convenience** — one command writing the two ordinary
   `POST /transactions` calls a transfer now consists of (out one account, in the
   other). The engine has had no transfer concept since 2026-08-10, so this is purely
   client-side sugar over two writes — which is also the argument *against* it, since
   the CLI's job is to exercise the engine's surface, not invent one. Explicitly **not**
   parity work. **[UI]** — needs a mockup covering naming, flags, and what the two
   legs' titles and categories default to. See [decisions.md](decisions.md) "Transfers
   are two ordinary transactions".

5. **`expense import csv`** — CSV variant of the shipped `.xlsx` importer. Only if a
   real migration needs it; the xlsx path already covered the original one.

6. **The TUI cannot create an inbox draft.** Found 2026-08-20 while binding `+`. The
   Inbox screen only filters, promotes, deletes and edits; `expense inbox add` is the
   only way to put a draft in. `+` deliberately does **not** fill this hole — it logs a
   posted transaction on every screen that has it, and one key writing to two endpoints
   depending on where you stand is the trap ([decisions.md](decisions.md)). The shape
   if it is closed: **`n New`**, already the convention on every other list screen
   (`_base.py` `ResourceListScreen`), and unbound on the Inbox today. **[UI]**

7. **Field navigation in the edit form is broken on macOS.** The form advertises
   `^↑ Prev field` / `^↓ Next field`, but `⌃↑` is Mission Control and `⌃↓` is
   Application Windows — the OS claims both before the terminal sees them, so the two
   keys have very likely never worked. Raised by the user 2026-08-20 ("normal arrows up
   and down should switch between fields"), then deferred with the rest of the form
   work. `shift+↑` / `shift+↓` **are** bindable and were probed live (arrows are not
   printable, so the terminal sends a distinct `CSI 1;2A`). The open question is what
   plain `↑↓` should then do on the three fields that have a suggestion list —
   options **J** and **K** are drawn in
   [mockups/expense-world-plus-and-arrows.html](mockups/expense-world-plus-and-arrows.html)
   §4, neither picked. **[UI]**

---

## Parked — no commitment

- **TUI live niceties.** Auto-refresh / watch mode, search-as-you-type, richer
  dashboards. Deliberately deferred as scope creep during the build; still deferred.
  Mouse stays **off** — see [tui.md](tui.md) §4.
- **Flat-CLI color conventions.** Rich-based output styling beyond what ships (color
  swatches, `NO_COLOR` honoured via `color_supported()`). No demand established.
- **`auth pat create` / `auth pat revoke`.** PATs are issued out-of-band; a future web
  dashboard is expected to issue them. See [cli-spec.md](cli-spec.md) "Auth model".
