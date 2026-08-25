"""One-line quick-add grammar — the parser behind the LOG bar.

CLI-specific input forgiveness (like dates.py and import_/): turns a single
typed line into the fields a transaction needs. Pure — no Textual, no HTTP, no
config — so the TUI screen and the flat `expense log "…"` command share one
grammar and one copy of every rule.

No business logic lives here. Names are matched against reference lists the
caller already holds; nothing is created, nothing is validated beyond shape.
The engine remains the only authority on whether a row is acceptable.

Design and the token table: docs/mockups/expense-world-quickadd-batch.html.
Why the grammar is client-side, and the three matching rules: docs/decisions.md.
"""
