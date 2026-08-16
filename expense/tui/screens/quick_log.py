"""Log / edit a transaction — quick-add bar (Phase 2).

One input bar cycles through fields; a summary fills below. Entity fields
(account/category/hashtags) show a live-filtered suggestion list — pick
existing entities only.

CREATE (record=None): Date › Title › Amount › Account › Category ›
Hashtags › Note.

EDIT (record + resource): the same bar pre-filled. Sequence: Date › Title ›
Amount › Account › Category › Cleared › Hashtags › Note. `ctrl+s` PUTs only
the changed fields.

`enter` saves & advances · `ctrl+↑/↓` jump fields · `↑/↓` move the suggestion
highlight · `ctrl+s` submits. Sign explicit (− expense / + income); currency
derived from the account.
"""

import copy
import uuid
from datetime import date as date_cls
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from rich.console import Group, RenderableType
from rich.text import Text
from textual import work
from textual.widgets import Input

from expense.commands import accounts_cmd, categories_cmd, hashtags_cmd
from expense.commands._resource import (
    account_choices,
    format_cents,
    items_of,
    resolve_name,
)
from expense.dates import to_canonical_aware
from expense.errors import format_error
from expense.tui.screens._base import screen_fetch_kwargs
from expense.tui.screens._form import FormScreen, form_bindings

_LABELS = {
    "date": "DATE",
    "title": "TITLE",
    "amount": "AMOUNT",
    "account": "ACCOUNT",
    "category": "CATEGORY",
    "cleared": "CLEARED?",
    "hashtags": "HASHTAGS",
    "note": "NOTE",
}
_ENTITY = {"account", "category", "hashtags"}
_AMOUNTS = {"amount"}
_HINTS = {
    "date": "YYYY-MM-DD · enter to accept, or type a date",
    "title": "free text · enter to save",
    "amount": "signed decimal · − expense / + income · in the account's currency",
    "account": "pick an existing account · ↑↓ highlight · enter select",
    "category": "pick an existing category · ↑↓ highlight · enter select",
    "cleared": "type yes / no / unset · has it posted at the bank?",
    "hashtags": "type a tag · ↑↓ highlight · enter adds & stays · empty enter = done (optional)",
    "note": "optional · enter saves · (ctrl+s anytime)",
}
# engine field name for each form key
_ENGINE_FIELD = {
    "date": "date",
    "title": "title",
    "amount": "amount_cents",
    "account": "account_id",
    "category": "category_id",
    "cleared": "cleared",
    "hashtags": "hashtag_ids",
    "note": "description",
}


def parse_amount(text: str) -> int | None:
    """`-99.92` → -9992 cents. None if unparseable. Sign is explicit."""
    text = text.strip().replace(",", "")
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return int((value * 100).to_integral_value(rounding=ROUND_HALF_UP))


def amount_to_text(cents: int) -> str:
    """Cents → an editable decimal string (no grouping): -9992 → '-99.92'."""
    return str(Decimal(cents) / 100)


def _name_map(rows: list) -> dict[str, str]:
    """id → name from fetched rows (system + archived included, like the
    load_*_name_map helpers these replace for this form)."""
    return {
        r["id"]: r["name"]
        for r in rows
        if isinstance(r.get("id"), str) and isinstance(r.get("name"), str)
    }


class QuickAddLogScreen(FormScreen):
    BINDINGS = form_bindings("Save")

    def __init__(self, *, record: dict | None = None, resource: str | None = None) -> None:
        super().__init__()
        self._mode = "edit" if record else "create"
        self._resource = resource or "transactions"
        self._record = record or {}
        self._accounts: list = []
        self._categories: list = []
        self._hashtags: list = []
        self._original: dict = {}

        if self._mode == "edit":
            self.crumb = (
                ("Capture & ledger", "Inbox", "Edit draft")
                if self._resource == "inbox"
                else ("Capture & ledger", "Transactions", "Edit")
            )
            self._prefill(self._record)
        else:
            self.crumb = ("Capture & ledger", "Log a transaction")
            self._values = {"date": date_cls.today().isoformat()}
            self._display = {"date": self._values["date"]}

    # ---- edit pre-fill ---------------------------------------------------
    def _prefill(self, rec: dict) -> None:
        self._values = {}
        self._display = {}
        date = (rec.get("date") or "")[:10]
        if date:
            self._values["date"] = self._display["date"] = date
        if rec.get("title"):
            self._values["title"] = self._display["title"] = rec["title"]
        if rec.get("amount_cents") is not None:
            self._values["amount"] = rec["amount_cents"]
            self._display["amount"] = format_cents(rec["amount_cents"])
        if rec.get("account_id"):
            self._values["account"] = rec["account_id"]
            self._display["account"] = rec["account_id"][:8]  # resolved once entities load
        if rec.get("category_id"):
            self._values["category"] = rec["category_id"]
            self._display["category"] = rec["category_id"][:8]
        cleared = rec.get("cleared")
        if cleared is not None:
            self._values["cleared"] = cleared
            self._display["cleared"] = "yes" if cleared else "no"
        tags = rec.get("hashtag_ids") or []
        if tags:
            self._values["hashtags"] = list(tags)
            # resolve_name: short-id placeholder until entities load, and a
            # null id renders "—" instead of TypeError-ing (backlog 6.2e)
            self._display["hashtags"] = " ".join("#" + resolve_name(t, {}) for t in tags)
        if rec.get("description"):
            self._values["note"] = self._display["note"] = rec["description"]
        # deep: _commit_hashtag appends to _values["hashtags"] in place — a shallow
        # copy would alias the list and the edit diff would never see the change.
        self._original = copy.deepcopy(self._values)
        # no client-side field locks: reconciliation locks rely on the
        # engine's 422 (not reliably detectable from the row).

    # ---- field sequence --------------------------------------------------
    def _sequence(self) -> list[str]:
        if self._mode == "edit":
            seq = ["date", "title", "amount", "account", "category", "cleared"]
            if self._resource == "transactions":  # inbox drafts have no hashtags
                seq.append("hashtags")
            seq.append("note")
            return seq
        return ["date", "title", "amount", "account", "category", "hashtags", "note"]

    def _required(self) -> tuple[str, ...]:
        if self._mode == "edit":
            return ()  # diff-based; the record is already valid
        return ("title", "amount", "account", "category")

    def _after_mount(self) -> None:
        self._load_entities()

    @work(thread=True, exclusive=True)
    def _load_entities(self) -> None:
        from expense import config as config_module

        try:
            cfg = config_module.ensure_loaded()
            kw = screen_fetch_kwargs(self.app)
            # one superset accounts fetch (include_archived) feeds both the
            # active-only suggestion pool and the full name map (backlog 6.5b);
            # categories/hashtags lost archive in the 2026-08-06 schema
            # slimming, so their single fetch is already the full set
            accts = items_of(
                accounts_cmd.fetch_accounts(cfg, include_people=True, include_archived=True, **kw)
            )
            cats = items_of(categories_cmd.fetch_categories(cfg, **kw))
            tags = items_of(hashtags_cmd.fetch_hashtags(cfg, **kw))
            maps = tuple(_name_map(rows) for rows in (accts, cats, tags))
        except Exception as exc:  # surface engine/config errors in-app, don't crash
            self.app.call_from_thread(self.notify, format_error(exc), severity="error")
            return
        active_accts = [a for a in accts if not a.get("is_archived")]
        accounts = account_choices(active_accts)
        categories = [
            (c["id"], c.get("name") or "(unnamed)")
            for c in cats
            if c.get("id") and not c.get("is_system")
        ]
        hashtags = [(t["id"], t.get("name") or "(unnamed)") for t in tags if t.get("id")]
        self.app.call_from_thread(self._set_entities, accounts, categories, hashtags, maps)

    def _set_entities(self, accounts, categories, hashtags, maps) -> None:
        self._accounts, self._categories, self._hashtags = accounts, categories, hashtags
        self._acc_names, self._cat_names, self._tag_names_map = maps
        if self._mode == "edit":  # resolve pre-filled ids → names
            # resolve_name (shared) renders a null reference as "—" instead of
            # crashing on None[:8] (backlog 6.2e)
            if "account" in self._values:
                self._display["account"] = resolve_name(self._values["account"], self._acc_names)
            if "category" in self._values:
                self._display["category"] = resolve_name(self._values["category"], self._cat_names)
            if self._values.get("hashtags"):
                self._display["hashtags"] = " ".join(
                    "#" + resolve_name(t, self._tag_names_map) for t in self._values["hashtags"]
                )
        self._recompute(self.query_one("#bar", Input).value)
        self._refresh_view()

    # ---- FormScreen hooks --------------------------------------------------
    def _label(self, key: str) -> str:
        return _LABELS[key]

    def _hint_for(self, key: str) -> str:
        return _HINTS.get(key, "")

    def _suggests(self, key: str) -> bool:
        return key in _ENTITY

    def _bar_value(self, key: str) -> str:
        if key in _AMOUNTS and key in self._values:
            return amount_to_text(self._values[key])
        if key == "cleared":
            return self._display.get("cleared", "unset")
        if key in ("date", "title", "note"):
            return str(self._values.get(key, "") or "")
        return ""  # entity fields re-pick from scratch

    # ---- suggestions -----------------------------------------------------
    def _recompute_suggestions(self, text: str) -> None:
        # historic name kept — test drivers (and muscle memory) call it directly
        self._recompute(text)

    def _recompute(self, text: str) -> None:
        key = self._key
        needle = text.strip().lower()
        if key == "account":
            pool = [(i, n, c) for (i, n, c) in self._accounts if needle in n.lower()]
        elif key == "category":
            pool = [(i, n) for (i, n) in self._categories if needle in n.lower()]
        elif key == "hashtags":
            needle = needle.lstrip("#")
            chosen = set(self._values.get("hashtags", []))
            pool = [(i, n) for (i, n) in self._hashtags if needle in n.lower() and i not in chosen]
        else:
            pool = []
        self._suggestions = pool
        self._suggest_idx = 0

    def _picked(self):
        return self._suggestions[self._suggest_idx] if self._suggestions else None

    # ---- commit ----------------------------------------------------------
    def on_input_submitted(self, event: Input.Submitted) -> None:
        key = self._key
        text = self.query_one("#bar", Input).value.strip()

        if key == "date":
            self._values["date"] = text or date_cls.today().isoformat()
            self._display["date"] = self._values["date"]
            self._advance()
        elif key == "title":
            if not text:
                self.notify("Title is required.", severity="error")
                return
            self._values["title"] = self._display["title"] = text
            self._advance()
        elif key == "amount":
            cents = parse_amount(text)
            if cents is None:
                self.notify("Amount: a signed decimal, e.g. -99.92", severity="error")
                return
            # Mid-form ergonomics guard; mirrors the engine's 422
            # amount_cents "Must not be zero." (engine-spec.md POST
            # /transactions). Deliberately kept client-side — backlog 2.5.
            if cents == 0:
                self.notify("Amount must be non-zero.", severity="error")
                return
            self._values["amount"] = cents
            self._display["amount"] = format_cents(cents)
            self._advance()
        elif key in ("account", "category"):
            picked = self._picked()
            if picked is None:
                self.notify(f"No {key} matches “{text}”.", severity="error")
                return
            self._values[key] = picked[0]
            self._display[key] = picked[1]
            self._advance()
        elif key == "cleared":
            self._commit_cleared(text)
        elif key == "hashtags":
            self._commit_hashtag(text)
            return
        elif key == "note":
            if text:
                self._values["note"] = self._display["note"] = text
            self.action_submit()  # note is last → enter submits
            return
        self._refresh_view()

    def _commit_cleared(self, text: str) -> None:
        t = text.strip().lower()
        if t in ("", "unset", "u", "none"):
            self._values["cleared"] = None
            self._display["cleared"] = "unset"
        elif t in ("yes", "y", "true", "1", "cleared"):
            self._values["cleared"] = True
            self._display["cleared"] = "yes"
        elif t in ("no", "n", "false", "0"):
            self._values["cleared"] = False
            self._display["cleared"] = "no"
        else:
            self.notify("Cleared: type yes / no / unset.", severity="error")
            return
        self._advance()

    def _commit_hashtag(self, text: str) -> None:
        if not text:
            self._advance()
            self._refresh_view()
            return
        picked = self._picked()
        if picked is None:
            self.notify(f"No hashtag matches “{text}”.", severity="error")
            return
        self._values.setdefault("hashtags", []).append(picked[0])
        self._display["hashtags"] = " ".join("#" + n for n in self._tag_display_names())
        self.query_one("#bar", Input).value = ""
        self._recompute("")
        self._refresh_view()

    def _tag_display_names(self) -> list[str]:
        names = getattr(self, "_tag_names_map", {}) or dict(self._hashtags)
        return [resolve_name(i, names) for i in self._values.get("hashtags", [])]

    # ---- render ----------------------------------------------------------
    def _suggest_renderable(self) -> RenderableType:
        if self._key not in _ENTITY:
            return Text("")
        if not self._suggestions:
            return Text("  no matches — pick something that exists", style="dim")
        window = 8
        total = len(self._suggestions)
        start = 0
        if total > window:
            start = max(0, min(self._suggest_idx - window // 2, total - window))
        rows: list = []
        if start > 0:
            rows.append(Text(f"  ↑ {start} more", style="dim"))
        for idx in range(start, min(start + window, total)):
            ent = self._suggestions[idx]
            extra = f"  {ent[2]}" if len(ent) > 2 else ""
            line = Text(f"  {ent[1]}{extra}")
            if idx == self._suggest_idx:
                line.stylize("reverse")
            rows.append(line)
        remaining = total - min(start + window, total)
        if remaining > 0:
            rows.append(Text(f"  ↓ {remaining} more", style="dim"))
        return Group(*rows)

    # ---- submit ----------------------------------------------------------
    def _submit_request(self) -> tuple[str, str, dict, str] | None:
        if self._mode == "edit":
            payload = self._edit_payload()
            if not payload:
                self.notify("No changes to save.")
                return None
            return ("PUT", f"/{self._resource}/{self._record['id']}", payload, "Saving…")
        payload = self._create_payload()
        return ("POST", "/transactions", payload, "Creating transaction…")

    def _create_payload(self) -> dict:
        date = to_canonical_aware(self._values.get("date") or date_cls.today().isoformat())
        payload = {
            "id": str(uuid.uuid4()),
            "title": self._values["title"],
            "amount_cents": self._values["amount"],
            "account_id": self._values["account"],
            "category_id": self._values["category"],
            "date": date,
        }
        if self._values.get("hashtags"):
            payload["hashtag_ids"] = self._values["hashtags"]
        if self._values.get("note"):
            payload["description"] = self._values["note"]
        return payload

    def _edit_payload(self) -> dict:
        payload: dict = {}
        for key, engine_field in _ENGINE_FIELD.items():
            if key in self._locked or self._values.get(key) == self._original.get(key):
                continue
            new = self._values.get(key)
            if key == "date":
                payload["date"] = to_canonical_aware(new) if new else None
            elif key == "note":
                payload["description"] = new or None
            elif key == "hashtags":
                payload["hashtag_ids"] = new or []
            else:
                payload[engine_field] = new
        return payload

    def _done(self) -> None:
        if self._mode == "edit":
            self.notify("Saved.")
        else:
            self.notify("Transaction created.")
        self.dismiss()
