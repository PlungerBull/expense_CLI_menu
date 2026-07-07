"""Log / edit a transaction — quick-add bar (Phase 2).

One input bar cycles through fields; a summary fills below. Entity fields
(account/category/hashtags/transfer-to) show a live-filtered suggestion list —
pick existing entities only.

CREATE (record=None): Date › Title › Amount › Account › Transfer to? › Category ›
Hashtags › Note. Filling "Transfer to?" makes it a transfer (… › To amount ›
Note; no category/hashtags — the engine assigns @Transfer/@Debt). To amount is
the opposite sign of Amount (auto-mirrored for same-currency accounts).

EDIT (record + resource): the same bar pre-filled. Sequence: Date › Title ›
Amount › Account › Category › Cleared › Hashtags › Note. Transfer legs lock
amount/account/date (shown faded, skipped). `ctrl+s` PUTs only the changed
fields.

`enter` saves & advances · `ctrl+↑/↓` jump fields · `↑/↓` move the suggestion
highlight · `ctrl+s` submits. Sign explicit (− expense / + income); currency
derived from the account.
"""

import copy
import io
import uuid
from datetime import date as date_cls
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from rich.console import Group, RenderableType
from rich.text import Text
from textual import work
from textual.widgets import Input

from expense.commands import accounts_cmd, categories_cmd, hashtags_cmd
from expense.commands._resource import (
    format_cents,
    items_of,
    load_account_name_map,
    load_category_name_map,
    load_hashtag_name_map,
)
from expense.dates import to_canonical_aware
from expense.errors import format_error
from expense.tui.screens._form import FormScreen, form_bindings

_LABELS = {
    "date": "DATE",
    "title": "TITLE",
    "amount": "AMOUNT",
    "account": "ACCOUNT",
    "transfer_to": "TRANSFER TO?",
    "to_amount": "TO AMOUNT",
    "category": "CATEGORY",
    "cleared": "CLEARED?",
    "hashtags": "HASHTAGS",
    "note": "NOTE",
}
_ENTITY = {"account", "transfer_to", "category", "hashtags"}
_AMOUNTS = {"amount", "to_amount"}
_HINTS = {
    "date": "YYYY-MM-DD · enter to accept, or type a date",
    "title": "free text · enter to save",
    "amount": "signed decimal · − expense / + income · in the account's currency",
    "account": "pick an existing account · ↑↓ highlight · enter select",
    "transfer_to": "optional · pick a destination account → transfer · empty enter = skip",
    "to_amount": (
        "magnitude only — sign is auto-set opposite of Amount (engine transfer rule) "
        "· same currency is auto-filled"
    ),
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
            self._display["hashtags"] = " ".join("#" + t[:6] for t in tags)
        if rec.get("description"):
            self._values["note"] = self._display["note"] = rec["description"]
        # deep: _commit_hashtag appends to _values["hashtags"] in place — a shallow
        # copy would alias the list and the edit diff would never see the change.
        self._original = copy.deepcopy(self._values)
        # transfer legs lock amount/account/date (engine read-only); reconciliation
        # locks rely on the engine's 422 (not reliably detectable from the row).
        if rec.get("transfer_transaction_id"):
            self._locked = {"amount", "account", "date"}

    # ---- field sequence --------------------------------------------------
    def _is_transfer(self) -> bool:
        return self._mode == "create" and bool(self._values.get("transfer_to"))

    def _sequence(self) -> list[str]:
        if self._mode == "edit":
            seq = ["date", "title", "amount", "account", "category", "cleared"]
            if self._resource == "transactions":  # inbox drafts have no hashtags
                seq.append("hashtags")
            seq.append("note")
            return seq
        seq = ["date", "title", "amount", "account", "transfer_to"]
        tail = ["to_amount", "note"] if self._is_transfer() else ["category", "hashtags", "note"]
        return seq + tail

    def _required(self) -> tuple[str, ...]:
        if self._mode == "edit":
            return ()  # diff-based; the record is already valid
        if self._is_transfer():
            return ("title", "amount", "account", "transfer_to", "to_amount")
        return ("title", "amount", "account", "category")

    def _after_mount(self) -> None:
        self._load_entities()

    @work(thread=True, exclusive=True)
    def _load_entities(self) -> None:
        from expense import config as config_module

        try:
            cfg = config_module.ensure_loaded()
            kw = dict(
                no_cache=self.app._no_cache,
                verbose=self.app._verbose,
                cold_start_notice=False,
                notice_stream=io.StringIO(),
            )
            accts = items_of(accounts_cmd.fetch_accounts(cfg, include_people=True, **kw))
            cats = items_of(categories_cmd.fetch_categories(cfg, **kw))
            tags = items_of(hashtags_cmd.fetch_hashtags(cfg, **kw))
            # full maps (incl system/archived) for resolving pre-filled edit values
            maps = (load_account_name_map(), load_category_name_map(), load_hashtag_name_map())
        except Exception as exc:  # surface engine/config errors in-app, don't crash
            self.app.call_from_thread(self.notify, format_error(exc), severity="error")
            return
        accounts = [
            (a["id"], a.get("name") or "(unnamed)", a.get("currency_code") or "?")
            for a in accts
            if a.get("id")
        ]
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
            if "account" in self._values:
                self._display["account"] = self._resolve(self._values["account"], self._acc_names)
            if "category" in self._values:
                self._display["category"] = self._resolve(self._values["category"], self._cat_names)
            if self._values.get("hashtags"):
                self._display["hashtags"] = " ".join(
                    "#" + self._resolve(t, self._tag_names_map) for t in self._values["hashtags"]
                )
        self._recompute(self.query_one("#bar", Input).value)
        self._refresh_view()

    @staticmethod
    def _resolve(id_: str, names: dict) -> str:
        return names.get(id_, id_[:8])

    def _account_currency(self, account_id) -> str | None:
        return next((c for (i, n, c) in self._accounts if i == account_id), None)

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
        if key in ("account", "transfer_to"):
            src = self._values.get("account") if key == "transfer_to" else None
            pool = [(i, n, c) for (i, n, c) in self._accounts if needle in n.lower() and i != src]
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
        elif key == "transfer_to":
            self._commit_transfer_to(text)
        elif key == "to_amount":
            self._commit_to_amount(text)
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

    def _commit_transfer_to(self, text: str) -> None:
        if not text:
            for k in ("transfer_to", "to_amount"):
                self._values.pop(k, None)
                self._display.pop(k, None)
            self._advance()
            return
        picked = self._picked()
        if picked is None:
            self.notify(f"No account matches “{text}”.", severity="error")
            return
        # Mirrors the engine's 422 transfer.account_id "Must be a different
        # account." (engine app/helpers/transfers.py — enforced but
        # undocumented in engine-spec.md; spec gap flagged in backlog 2.5).
        # Deliberately kept client-side.
        if picked[0] == self._values.get("account"):
            self.notify("Transfer destination must differ from the source.", severity="error")
            return
        self._values["transfer_to"] = picked[0]
        self._display["transfer_to"] = picked[1]
        from_cur = self._account_currency(self._values.get("account"))
        to_cur = picked[2] if len(picked) > 2 else None
        amount = self._values.get("amount")
        if amount is not None and from_cur and to_cur and from_cur == to_cur:
            self._values["to_amount"] = -amount
            self._display["to_amount"] = format_cents(-amount)
        else:
            self._values.pop("to_amount", None)
            self._display.pop("to_amount", None)
        self._advance()

    def _commit_to_amount(self, text: str) -> None:
        raw = parse_amount(text) if text else self._values.get("to_amount")
        if raw is None:
            self.notify("Enter the destination amount, e.g. 500 or 270.50", severity="error")
            return
        # Mirrors the engine's 422 transfer.amount_cents "Must not be zero."
        if raw == 0:
            self.notify("Amount must be non-zero.", severity="error")
            return
        amount = self._values.get("amount", 0)
        magnitude = abs(raw)
        # SANCTIONED EXCEPTION (cli-spec.md "Sanctioned exceptions", backlog
        # 2.1): deliberate client-side mirror of the engine's zero-sum
        # transfer rule — both legs same sign → 422 (engine
        # app/helpers/transfers.py; engine-spec.md Transfers §6). The field
        # takes a magnitude, the sign is always the opposite of Amount, and
        # the computed signed value is shown in the summary before submit.
        self._values["to_amount"] = magnitude if amount < 0 else -magnitude
        self._display["to_amount"] = format_cents(self._values["to_amount"])
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
        return [names.get(i, i[:8]) for i in self._values.get("hashtags", [])]

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
        busy = "Creating transfer…" if self._is_transfer() else "Creating transaction…"
        return ("POST", "/transactions", payload, busy)

    def _create_payload(self) -> dict:
        date = to_canonical_aware(self._values.get("date") or date_cls.today().isoformat())
        if self._is_transfer():
            payload = {
                "id": str(uuid.uuid4()),
                "title": self._values["title"],
                "amount_cents": self._values["amount"],
                "account_id": self._values["account"],
                "date": date,  # no category_id — engine assigns @Transfer / @Debt
                "transfer": {
                    "id": str(uuid.uuid4()),
                    "account_id": self._values["transfer_to"],
                    "amount_cents": self._values["to_amount"],
                },
            }
        else:
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
            self.notify("Transfer created." if self._is_transfer() else "Transaction created.")
        self.dismiss()
