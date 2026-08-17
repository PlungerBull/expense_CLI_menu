"""Create forms — new hashtag / category / account (Phase 2).

A lightweight bar-cycle form (same look as Log): cycle fields with the input
bar, pick choices from a suggestion list, `ctrl+s` (or enter on the last field)
POSTs. Reached with `n` on the Manage list screens.

New account covers both kinds: its first field is TYPE (`bank` / `person`,
prefilled `bank`), and a `person` picks `POST /people` instead of
`POST /accounts` — the People API, shipped 2026-08-14 (backlog 6.2). `is_person`
is never sent as a field; it is a 422 on both routes, and the endpoint is the
flag. Editing cannot change it, so TYPE is locked read-only on the edit form.
"""

import uuid

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text
from textual.widgets import Input

from expense.currencies import SUPPORTED_CURRENCIES
from expense.tui.screens._form import FormScreen

_PALETTE = [
    ("#4a90d9", "blue"),
    ("#5ab87a", "green"),
    ("#d96a5a", "red"),
    ("#b07cd9", "purple"),
    ("#d9a93a", "amber"),
    ("#5ab8a0", "teal"),
    ("#d9744a", "orange"),
    ("#8a8f98", "grey"),
]
_CURRENCIES = [(c, c) for c in SUPPORTED_CURRENCIES]
# Bank first: it is the prefilled default, so `enter` on an untouched TYPE field
# keeps `bank` and adding an ordinary account still costs one keypress.
_ACCOUNT_TYPES = [("bank", "bank"), ("person", "person")]


class Field:
    def __init__(self, key, label, kind="text", *, choices=None, required=False, hint=""):
        self.key = key
        self.label = label
        self.kind = kind  # "text" | "choice" | "color"
        self.choices = choices or []
        self.required = required
        self.hint = hint


class BarFormScreen(FormScreen):
    FIELDS: list = []
    NOUN = "item"

    # ---- FormScreen hooks (Field-driven) ----------------------------------
    def _sequence(self) -> list[str]:
        return [f.key for f in self.FIELDS]

    def _field(self, key: str) -> Field:
        return next(f for f in self.FIELDS if f.key == key)

    @property
    def _f(self) -> Field:
        return self.FIELDS[self._current]

    def _label(self, key: str) -> str:
        return self._field(key).label

    def _hint_for(self, key: str) -> str:
        return self._field(key).hint

    def _required(self) -> tuple[str, ...]:
        return tuple(f.key for f in self.FIELDS if f.required)

    def _suggests(self, key: str) -> bool:
        return self._field(key).kind in ("choice", "color")

    def _bar_value(self, key: str) -> str:
        f = self._field(key)
        return str(self._values.get(key, "")) if f.kind == "text" else ""

    def _recompute(self, text: str) -> None:
        f = self._f
        needle = text.strip().lower()
        if f.kind in ("choice", "color"):
            self._suggestions = [
                (v, d) for (v, d) in f.choices if needle in d.lower() or needle in v.lower()
            ]
        else:
            self._suggestions = []
        self._suggest_idx = 0

    # ---- commit ----------------------------------------------------------
    def on_input_submitted(self, event: Input.Submitted) -> None:
        f = self._f
        text = self.query_one("#bar", Input).value.strip()
        if f.kind == "text":
            if not text:
                if f.required:
                    self.notify(f"{f.label.title()} is required.", severity="error")
                    return
                self._values.pop(f.key, None)
            else:
                self._values[f.key] = text
            self._advance()
            return
        # choice / color
        if not text and not f.required:
            self._values.pop(f.key, None)
            self._advance()
            return
        picked = self._suggestions[self._suggest_idx] if self._suggestions else None
        if picked is None:
            self.notify(f"Pick a {f.label.lower()}.", severity="error")
            return
        self._values[f.key] = picked[0]
        self._advance()

    # ---- render ----------------------------------------------------------
    def _suggest_renderable(self) -> RenderableType:
        f = self._f
        if f.kind not in ("choice", "color"):
            return Text("")
        if not self._suggestions:
            return Text("  no match", style="dim")
        rows = []
        for i, (value, display) in enumerate(self._suggestions):
            if f.kind == "color":
                line = Text.assemble(("  ", ""), ("██ ", value), (display, ""))
            else:
                line = Text(f"  {display}")
            if i == self._suggest_idx:
                line.stylize("reverse")
            rows.append(line)
        return Group(*rows)

    def _summary_renderable(self) -> RenderableType:
        t = Table(box=None, pad_edge=False, show_header=False)
        t.add_column("k")
        t.add_column("v")
        for i, f in enumerate(self.FIELDS):
            locked = f.key in self._locked
            if f.key in self._values:
                if f.kind == "color":
                    hex_ = self._values[f.key]
                    value = Text.assemble(("██ ", hex_), (self._color_name(hex_), ""))
                else:
                    value = Text(str(self._values[f.key]))
            else:
                value = Text("—" + ("  *" if f.required else "  (optional)"), style="dim")
            if locked:  # edit forms lock immutable fields (e.g. account currency)
                value.append("  read-only", style="dim")
            label = Text(f.label.lower(), style="dim" if locked else "")
            if i == self._current and not locked:
                label.stylize("bold")
            t.add_row(label, value)
        return t

    @staticmethod
    def _color_name(hex_: str) -> str:
        return next((d for (v, d) in _PALETTE if v == hex_), hex_)

    # ---- submit ----------------------------------------------------------
    def _payload(self) -> dict:
        raise NotImplementedError

    def _done(self) -> None:
        self.notify(f"{self.NOUN.title()} created.")
        self.dismiss()


class NewHashtagScreen(BarFormScreen):
    crumb = ("Manage", "Hashtags", "New")
    RESOURCE = "hashtags"
    NOUN = "hashtag"
    FIELDS = [Field("name", "NAME", required=True, hint="lowercase, no “#” · enter creates")]

    def _payload(self) -> dict:
        return {"id": str(uuid.uuid4()), "name": self._values["name"].lstrip("#")}


class NewCategoryScreen(BarFormScreen):
    crumb = ("Manage", "Categories", "New")
    RESOURCE = "categories"
    NOUN = "category"
    FIELDS = [
        Field("name", "NAME", required=True, hint="enter to save"),
        Field("color", "COLOR", "color", choices=_PALETTE, required=True, hint="pick a swatch"),
    ]

    def _payload(self) -> dict:
        return {
            "id": str(uuid.uuid4()),
            "name": self._values["name"],
            "color": self._values["color"],
        }


class NewAccountScreen(BarFormScreen):
    """New bank account *or* person — one form, one key, a TYPE field on top.

    A person is a bank account with `is_person = true`, and the two take exactly
    the same fields; the only difference is which endpoint the save goes to
    (`POST /accounts` vs `POST /people`). So the choice is a field rather than a
    second screen or a second key (sketch pick L, 2026-08-16), and it is
    **prefilled to `bank`** — `n`, `enter`, name… still adds an ordinary account
    without an extra decision.

    `is_person` is never sent in the body: `POST /accounts` rejects it and
    `POST /people` implies it, so on either route the field is a 422. The endpoint
    *is* the flag.
    """

    crumb = ("Manage", "Accounts", "New")
    RESOURCE = "accounts"
    NOUN = "account"
    FIELDS = [
        Field(
            "type",
            "TYPE",
            "choice",
            choices=_ACCOUNT_TYPES,
            required=True,
            hint="bank or person · enter keeps bank",
        ),
        Field("name", "NAME", required=True, hint="enter to save"),
        Field(
            "currency", "CURRENCY", "choice", choices=_CURRENCIES, required=True, hint="PEN or USD"
        ),
        Field("color", "COLOR", "color", choices=_PALETTE, hint="optional · empty enter to skip"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._values["type"] = "bank"

    @property
    def _is_person(self) -> bool:
        return self._values.get("type") == "person"

    def _submit_request(self) -> tuple[str, str, dict, str]:
        # The one place the TYPE field is read. `/people` is the only people
        # route there is — everything after creation is an account route.
        resource = "people" if self._is_person else self.RESOURCE
        return ("POST", f"/{resource}", self._payload(), "Creating…")

    def _done(self) -> None:
        self.notify("Person created." if self._is_person else "Account created.")
        self.dismiss()

    def _payload(self) -> dict:
        payload = {
            "id": str(uuid.uuid4()),
            "name": self._values["name"],
            "currency_code": self._values["currency"],
        }
        if self._values.get("color"):
            payload["color"] = self._values["color"]
        return payload


# --------------------------------------------------------------------------- #
# Edit forms — same bar-form, prefilled, PUT instead of POST. Reached with `e`
# on a Manage list row (ResourceListScreen). Currency is immutable
# (engine rejects it), so account edit locks it to a read-only summary row.
# --------------------------------------------------------------------------- #
class EditHashtagScreen(NewHashtagScreen):
    def __init__(self, record: dict) -> None:
        super().__init__()
        self._id = record["id"]
        self._values = {"name": (record.get("name") or "").lstrip("#")}
        self.crumb = ("Manage", "Hashtags", record.get("name") or "—", "Edit")

    def _submit_request(self) -> tuple[str, str, dict, str]:
        return ("PUT", f"/hashtags/{self._id}", self._payload(), "Saving…")

    def _payload(self) -> dict:
        return {"name": self._values["name"].lstrip("#")}

    def _done(self) -> None:
        self.notify("Saved.")
        self.dismiss()


class EditCategoryScreen(NewCategoryScreen):
    def __init__(self, record: dict) -> None:
        super().__init__()
        self._id = record["id"]
        self._values = {"name": record.get("name") or ""}
        if record.get("color"):
            self._values["color"] = record["color"]
        self.crumb = ("Manage", "Categories", record.get("name") or "—", "Edit")

    def _submit_request(self) -> tuple[str, str, dict, str]:
        return ("PUT", f"/categories/{self._id}", self._payload(), "Saving…")

    def _payload(self) -> dict:
        payload = {"name": self._values["name"]}
        if self._values.get("color"):
            payload["color"] = self._values["color"]
        return payload

    def _done(self) -> None:
        self.notify("Saved.")
        self.dismiss()


class EditAccountScreen(NewAccountScreen):
    def __init__(self, record: dict) -> None:
        super().__init__()
        self._id = record["id"]
        # Both immutable after creation. `currency` the engine rejects outright;
        # `type` has no update path at all — `is_person` is settable only at the
        # moment of creation, which is the entire reason `POST /people` exists.
        self._locked = {"currency", "type"}
        self._values = {
            "type": "person" if record.get("is_person") else "bank",
            "name": record.get("name") or "",
            "currency": record.get("currency_code") or "",
        }
        if record.get("color"):
            self._values["color"] = record["color"]
        self.crumb = ("Manage", "Accounts", record.get("name") or "—", "Edit")

    def _submit_request(self) -> tuple[str, str, dict, str]:
        return ("PUT", f"/accounts/{self._id}", self._payload(), "Saving…")

    def _payload(self) -> dict:
        payload = {"name": self._values["name"]}
        if self._values.get("color"):
            payload["color"] = self._values["color"]
        return payload

    def _done(self) -> None:
        self.notify("Saved.")
        self.dismiss()
