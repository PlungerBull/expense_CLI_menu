# TODO — the workpad

**The single open-work queue for this repo.** Nothing else tracks pending work — no
issue tracker, no scattered `TODO:` comments in code (there are none, and that is
deliberate: a comment nobody greps is not a queue).

Rules, unchanged from the backlog this file replaces
([decisions.md](decisions.md) "The open-work list holds only open work"):

- **Closed items get deleted**, not ticked and archived. Git history is the archive.
- Items marked **[UI]** change something the user sees and need an HTML mockup in
  [mockups/](mockups/) reviewed and explicitly picked before any code (CLAUDE.md
  "Mock every screen before building it" — showing is not approval).
- **Absolute dates only.** Never "recently".
- **Cite items by title, never by number.** Numbering is presentation — it shifts every
  time an item closes, and it has shifted twice already. Code and docs that point here
  quote the item's bolded title instead, so a renumber can never make them lie.

**Nothing here is a regression and nothing blocks daily use.** The flat CLI and the
TUI are both feature-complete against the engine; **1110 unit tests green
(2026-08-27)**, contract suite **12/12** against the disposable engine on `:8001`
(last run 2026-08-25). Exactly one item below is a genuine defect — the macOS field
keys, under **Bugs**; the rest are a missing capability, ergonomics, one engine-side
ask, and one cosmetic follow-up.

**The quick-add bar closed 2026-08-25** — all four phases: the grammar
([expense/quickadd/](../expense/quickadd/)), `expense log "<line>"`, the TUI LOG bar
([log_bar.py](../expense/tui/screens/log_bar.py)) and its save, with `+` now opening
it. Its why lives in [decisions.md](decisions.md) (four entries) and its design in
[mockups/expense-world-quickadd-batch.html](mockups/expense-world-quickadd-batch.html);
per the first rule above, the item itself is gone — git history is the archive.

---

## Bugs

1. **Field navigation in the edit form is broken on macOS.** `⌃↑` is Mission Control
   and `⌃↓` is Application Windows — the OS claims both before the terminal sees them,
   so `^↑ Prev field` / `^↓ Next field` have very likely never worked. Raised by the
   user 2026-08-20 ("normal arrows up and down should switch between fields"), then
   deferred with the rest of the form work. **The footer stopped advertising them
   2026-08-24** (with the plain `↑ ↓` rows, which the 2026-08-20 trim had missed) — the
   keys stay bound in [_form.py](../expense/tui/screens/_form.py), so what is left here
   is only choosing the replacement.
   `shift+↑` / `shift+↓` **are** bindable and were probed live (arrows are not
   printable, so the terminal sends a distinct `CSI 1;2A`). The open question is what
   plain `↑↓` should then do on the three fields that have a suggestion list —
   options **J** and **K** are drawn in
   [mockups/expense-world-plus-and-arrows.html](mockups/expense-world-plus-and-arrows.html)
   §4, neither picked. **[UI]** · *smallest item here; one answer unblocks it.*

   **A third candidate the mockup does not draw: `tab` / `shift+tab` (found 2026-08-27,
   during the movement-key sweep).** It is the only option that costs nothing —
   plain `↑↓` keep their single meaning (the suggestion list) and nothing is
   sacrificed, which is what J-vs-K was a choice *between*. Verified that day: every
   form has exactly one focusable widget (`Input#bar`), so Textual's screen-level
   `tab` → `app.focus_next` is a **no-op on every form today**; the key is free.
   `tab` is also already the de-facto region key elsewhere — Outstanding is the one
   screen with two focusable regions and `tab` moves between them, undesigned. Fits
   the rule set 2026-08-27 in [decisions.md](decisions.md) "One key per job".
   **One wrinkle to decide with it:** forms have no `?` card (a focused `Input`
   swallows printable keys), so a form key has no discovery surface — this may be the
   one case where an arrow-family key earns a footer slot (`⇥ Field` beside
   `esc Cancel  ^s Save`), against the standing "arrows never get a slot" rule from
   [tui.md](tui.md) §4.

## Missing capability

2. **The TUI cannot create an inbox draft.** Found 2026-08-20 while binding `+`. The
   Inbox screen only filters, promotes, deletes and edits; `expense inbox add` is the
   only way to put a draft in. `+` deliberately does **not** fill this hole — it opens
   the LOG bar on every screen that has it, and a line lands in the Inbox only when the
   grammar says it is too sparse to post, never because of where you were standing
   ([decisions.md](decisions.md) "What a half-written batch means"). The shape if it is
   closed: **`n New`**, already the convention on every other list screen
   (`_base.py` `ResourceListScreen`), and unbound on the Inbox today. **[UI]**

## Ergonomics

3. **Shell completions** — zsh, bash, fish. `expense <TAB>` shows commands,
   `expense auth <TAB>` shows subcommands. Lowest-effort discoverability win for the
   flat path; no design questions open.

4. **Human-name resolution for reference flags.** Accept either a UUID or a
   human-readable name on every `--account-id` / `--category-id` / `--hashtag-id` /
   `--reconciliation-id`. Client-side lookup via the existing list endpoints:
   case-insensitive exact match, ambiguous matches rejected with a "be more specific"
   error pointing at `expense <resource> list`; UUIDs pass through unchanged.
   Significant feature — **deserves its own plan-mode session.** Note the quick-add
   grammar already solved the same problem its own way (contains-anywhere matching over
   `load_quickadd_refs`, [quickadd/parse.py](../expense/quickadd/parse.py)); decide
   deliberately whether the flag path reuses that matcher or keeps its stricter
   exact-match rule, rather than ending up with two by accident.

5. **"Move between accounts" convenience** — one command writing the two ordinary
   `POST /transactions` calls a transfer now consists of (out one account, in the
   other). The engine has had no transfer concept since 2026-08-10, so this is purely
   client-side sugar over two writes — which is also the argument *against* it, since
   the CLI's job is to exercise the engine's surface, not invent one. Explicitly **not**
   parity work. **[UI]** — needs a mockup covering naming, flags, and what the two
   legs' titles and categories default to. See [decisions.md](decisions.md) "Transfers
   are two ordinary transactions".

6. **`expense import csv`** — CSV variant of the shipped `.xlsx` importer. **Conditional:
   only if a real migration needs it**; the xlsx path already covered the original one.
   Cheaper now than when it was written down — the write half is shared
   ([batch_write.py](../expense/batch_write.py)), so only a reader would be new.

## Cosmetic — safe to leave

7. **`QuickAddLogScreen` is an edit-only screen with a create-era name.** Its create
   mode was retired 2026-08-25 when `+` moved to the LOG bar
   ([mockups/expense-world-two-doors.html](mockups/expense-world-two-doors.html)); the
   class, and the module `quick_log.py`, still carry the name of the door that closed.
   A rename is mechanical (≈6 source + 5 test files) and touches nothing behavioural,
   which is exactly why it was **not** folded into the phase-4 commit — it would have
   buried a real diff under noise. `EditFormScreen` / `edit_form.py` is the obvious
   target. If the module is renamed, [tui.md](tui.md) links to it and
   `test_relative_doc_links_resolve` will catch a miss.

## Engine-side asks — raise with the engine coder, do not fix here

*(This repo never writes the engine repo. These are contract gaps found by using the
engine, which is what this CLI exists to do — see CLAUDE.md "Product scope and role".)*

8. **`POST /transactions/batch` does not return the failing item's index.**
   `engine-spec.md` says it "returns an array of created transaction objects and an
   array of any validation errors (**with the index of the failing item**)"; it does
   not. Either the spec describes an intention that was never built, or the shape
   drifted. **Not a blocker and not urgent** — the workaround is written, shared and
   tested ([batch_write.py](../expense/batch_write.py): a refused chunk is re-posted one
   row per batch so the bad row names itself) — but it is exactly the kind of gap this
   CLI exists to surface before web and iOS inherit it. Found by `expense import`; now
   also relied on by the TUI's LOG bar, so **two** surfaces depend on the workaround.
   Related wire-shape note for the same conversation: the spec's error paths say
   `fields.items[i]…`, implying an `items` key, while every caller sends
   `{"transactions": [...]}` — worth confirming which is authoritative.

---

## Parked — no commitment

- **The quick-add launcher hotkey.** A global chord that opens the LOG bar from outside
  the TUI ([mockups/quick-add-launcher-options.html](mockups/quick-add-launcher-options.html),
  which also records the ⌘E conflict). Deliberately left open when the quick-add item
  closed 2026-08-25 — the bar is reachable by `+` and the flat `expense log "<line>"`,
  so this is convenience, not access.
- **The quick-add "recents" row** — numbered last-N templates, option E of
  [mockups/expense-world-log-revamp.html](mockups/expense-world-log-revamp.html).
  **Declined 2026-08-25**, kept here only so it is not re-proposed as new.
- **TUI live niceties.** Auto-refresh / watch mode, search-as-you-type, richer
  dashboards. Deliberately deferred as scope creep during the build; still deferred.
  Mouse stays **off** — see [tui.md](tui.md) §4.
- **Flat-CLI color conventions.** Rich-based output styling beyond what ships (color
  swatches, `NO_COLOR` honoured via `color_supported()`). No demand established.
- **`auth pat create` / `auth pat revoke`.** PATs are issued out-of-band; a future web
  dashboard is expected to issue them. See [cli-spec.md](cli-spec.md) "Auth model".
