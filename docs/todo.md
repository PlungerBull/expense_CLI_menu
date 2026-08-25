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
feature-complete against the engine; 1052 unit tests green (2026-08-25), contract
suite 12/12 against the disposable engine on `:8001` (last run 2026-08-20).

---

## Open — post-Step-9 ergonomics

Unblocked 2026-08-16 when the contract suite passed against a real engine, which was
their precondition. Land in roughly this order; none blocks another.

1. **Quick-add parser + the one-line batch logger.** One `LOG` bar replaces the
   bar-cycle create form; `↵` stages a parsed line into a list, `ctrl+s` writes the
   list, `↑↓` pick a staged row back up to edit. **Phases 1–2 have shipped** — the
   grammar, and `expense log "<line>"` on the flat CLI; the TUI screen is phases 3–4.
   This is the "low-friction capture" half of the dual-UX strategy; the TUI is the "discoverable
   management" half ([decisions.md](decisions.md)).

   **[UI] — picked 2026-08-25.** Option **D** of
   [mockups/expense-world-log-revamp.html](mockups/expense-world-log-revamp.html)
   ("one line") beat the receipt, the amount hero and the two-pane cockpit; the reason
   given was that a staged batch shows every row you are about to submit at a glance.
   Its worked-out design — nine states, the grammar, the keymap — is
   [mockups/expense-world-quickadd-batch.html](mockups/expense-world-quickadd-batch.html).
   Earlier speculative drawings, superseded but kept for the launcher question:
   [mockups/quick-add-bar.html](mockups/quick-add-bar.html),
   [mockups/quick-add-launcher-options.html](mockups/quick-add-launcher-options.html),
   [mockups/expense-world-log-quickadd.html](mockups/expense-world-log-quickadd.html)
   (states a–c are the bar-cycle form that ships today).

   **The grammar, as decided** — owner calls, so they are not re-litigated:
   - **A sign makes a number an amount**, anywhere in the line; **first sign wins**
     (`hoy +30 no -30` is +30). No sign, no amount — the digits are title text.
     Sign is literal, always: `+` income, `-` expense.
   - **`$` does both jobs**, split by the next character: `$` + digits is money
     (`-$1800` ≡ `-1800`; the currency always comes from the account, so `$` never
     says *which*), `$` + letters is an account (`$BCP PEN`). Safe because no account
     name starts with a digit.
   - **`@` category · `#` hashtag · `//` note.** `#` is the only repeatable token;
     for `$`, `@` and the date, first occurrence wins.
   - **Dates:** `dd/mm/yyyy` and `yyyy/mm/dd` (4-digit-first disambiguates, so they
     cannot collide), plus word forms in **both languages** — `hoy/ayer/mañana` and
     `today/yesterday/tomorrow`, unaccented spellings accepted. Omitted = today.
     Two-digit years are **accepted**, `yy` → `20yy`, because the resolved date is
     always echoed in words (*Tue 18 Aug 2026*) before the row is staged — a misread
     is visible rather than silent. (No industry rule fits a personal ledger: POSIX
     and Python `%y` send 69–99 to the 1900s, Excel splits at 29/30, ISO 8601 and
     RFC 3339 forbid two-digit years outright.)
   - **Routing happens at stage time, not at save time.** A row goes to the ledger
     only if it is complete *and* not dated ahead; everything else is addressed to the
     **Inbox**, and the list says so before you commit. `POST /inbox` takes sparse
     drafts (only `id` required) and has no future-date check — that is gated at
     promote — so a `mañana` row is a legal scheduled draft.
   - **Where it lives:** a pure module (`expense/quickadd/`), no Textual, no HTTP, so
     the TUI screen and a flat `expense log "…"` share one grammar
     ([decisions.md](decisions.md) — "the client owns what is fast to type").

   **No engine work needed.** `POST /transactions/batch` (atomic, client-supplied ids)
   already backs `expense import`, and `POST /inbox` takes the drafts. **One thing to
   raise with the engine coder, not a blocker:** the spec says the batch endpoint
   returns validation errors *with the index of the failing item*; it does not —
   [import_/apply.py](../expense/import_/apply.py) works around it by re-posting one
   row per batch. Either the spec describes something never built, or the shape drifted.

   **Not in scope:** the "recents" row (numbered last-N templates, option E of the
   revamp mockup) — declined 2026-08-25. The launcher hotkey
   ([mockups/quick-add-launcher-options.html](mockups/quick-add-launcher-options.html))
   is a separate question and stays parked.

   ---

   ### Phases — build one at a time, each lands on green CI

   **Phase 3 ships nothing the user can reach.** `+` keeps opening today's form until
   phase 4 flips it, so `main` stays usable throughout.

   **Phase 1 shipped 2026-08-25.** The grammar lives in
   [expense/quickadd/](../expense/quickadd/) — `parse.py` (tokenizer + name matching),
   `when.py` (dates), `money.py` (`parse_amount`/`amount_to_text`, moved out of
   [quick_log.py](../expense/tui/screens/quick_log.py)). Pure: no Textual, no HTTP, no
   config, no `typer`. `parse(line, *, accounts, categories, hashtags, today)` returns a
   `ParsedLine` with the resolved fields, the tokens that did **not** resolve (with their
   candidates), and a `Span` per token so a caller can colour the line without
   re-parsing. Covered by [test_quickadd_parse.py](../tests/unit/test_quickadd_parse.py).
   The three rules the mockup left open — contains-anywhere matching, dashed ISO dates,
   an unmatched `#tag` flagged rather than created — are in
   [decisions.md](decisions.md) "Three quick-add grammar rules".

   **Phase 2 shipped 2026-08-25.** `expense log "<line>"` is the grammar's first
   caller — a positional argument on the existing command, mutually exclusive with the
   four flags, plus `--dry-run` (the read-only way to test the grammar by hand) and
   `--yes`. Three pure pieces landed with it, all of which phases 3–4 reuse rather than
   reinvent: [route.py](../expense/quickadd/route.py) (ledger vs Inbox, and the phrases
   that say why — the staged list's `goes to` column), [payload.py](../expense/quickadd/payload.py)
   (both request bodies; the Inbox one is sparse, never an explicit null) and
   `format_date_words` in [when.py](../expense/quickadd/when.py). The TUI's reference-list
   fetch was extracted to `load_quickadd_refs` in
   [_resource.py](../expense/commands/_resource.py) so both surfaces suggest from one pool
   — and now page through every category and hashtag, which the TUI picker never did.
   Output block: option **A** of
   [mockups/expense-world-log-oneline.html](mockups/expense-world-log-oneline.html).
   The two behavioural calls — an incomplete or ambiguous line drafts to the Inbox, and
   the flat command always asks before writing — are in
   [decisions.md](decisions.md) "Two calls for the one-line `expense log`".

   **Phase 3 — the TUI screen, staging only.** New screen: the LOG bar, live token
   colouring off phase 1's spans, the completion picker rewriting the token in place
   (mockup panes 2–3), `↵` to stage, the staged list with its `goes to` column, routing
   decided **at stage time** (complete and not dated ahead → ledger, else inbox), `↑↓`
   doing double duty, `↵` lifting a row back into the bar, `ctrl+x` dropping one, `esc`
   confirming a discard. `ctrl+s` does nothing yet. Not reachable from `+`; pilot tests
   are the only way in. **Done when:** every mockup state 1–6 and 9 renders and the keys
   behave.

   **Phase 4 — the save, and the switch.** `ctrl+s` writes: one
   `POST /transactions/batch` for the ledger rows, then a `POST /inbox` per draft. The
   bodies come from [payload.py](../expense/quickadd/payload.py), already shared with
   phase 2 — do not build a second pair.
   Reuse the chunk + singleton-fallback pattern from
   [import_/apply.py](../expense/import_/apply.py) (extract it rather than copy it) so a
   422 can name its row. Then point `action_log_transaction`
   ([_base.py](../expense/tui/screens/_base.py), the single `+` binding every screen
   inherits) at the new screen, and retire `QuickAddLogScreen`'s **create** mode —
   `record=None`, `_create_payload`, and the `_required` branch — keeping its edit mode
   untouched, per [mockups/expense-world-two-doors.html](mockups/expense-world-two-doors.html).
   Update [cli-spec.md](cli-spec.md) (the new command shape), [tui.md](tui.md) (the new
   screen, the retired mode) and [decisions.md](decisions.md) (why the grammar is
   client-side). **Done when:** mockup states 7–8 render, the contract suite still
   passes, and `+` opens the bar.

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

7. **Field navigation in the edit form is broken on macOS.** `⌃↑` is Mission Control
   and `⌃↓` is Application Windows — the OS claims both before the terminal sees them,
   so `^↑ Prev field` / `^↓ Next field` have very likely never worked. Raised by the
   user 2026-08-20 ("normal arrows up and down should switch between fields"), then
   deferred with the rest of the form work. **The footer stopped advertising them
   2026-08-24** (with the plain `↑ ↓` rows, which the 2026-08-20 trim had missed) — the
   keys stay bound, so what is left here is only choosing the replacement.
   `shift+↑` / `shift+↓` **are** bindable and were probed live (arrows are not
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
