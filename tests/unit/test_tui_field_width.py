"""Backlog 4.4 — the #field label column must fit every form label.

The three bar-cycle forms (quick-log, create forms, new reconciliation) share
app.tcss's `#field { width: N; padding: 0 1 0 0 }`. Textual's box model puts
the padding INSIDE the width and Static hard-crops with no ellipsis, so a
label longer than (width − right padding) silently loses its tail
("BEGIN BALANCE" → "BEGIN BALA"). This guard computes the longest label
straight from the forms' own definitions and pins the tcss value against it —
a future longer label fails here by name instead of shipping clipped.
"""

import re
from pathlib import Path

import expense.tui as tui_pkg
from expense.tui.screens.create_forms import (
    NewAccountScreen,
    NewCategoryScreen,
    NewHashtagScreen,
)
from expense.tui.screens.quick_log import _LABELS
from expense.tui.screens.reconciliations import _R_LABELS


def _field_rule() -> tuple[int, int]:
    """(width, right_padding) parsed from app.tcss's #field rule."""
    tcss = (Path(tui_pkg.__file__).parent / "app.tcss").read_text()
    block = re.search(r"#field\s*\{([^}]*)\}", tcss).group(1)
    width = int(re.search(r"width:\s*(\d+)", block).group(1))
    padding = re.search(r"padding:\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)", block)
    right_pad = int(padding.group(2)) if padding else 0
    return width, right_pad


def _all_form_labels() -> dict[str, str]:
    """Every string that can appear in the #field label, keyed by origin."""
    labels = {f"quick_log:{key}": text for key, text in _LABELS.items()}
    labels |= {f"reconciliations:{key}": text for key, text in _R_LABELS.items()}
    for screen in (NewHashtagScreen, NewCategoryScreen, NewAccountScreen):
        labels |= {f"{screen.__name__}:{f.key}": f.label for f in screen.FIELDS}
    return labels


def test_field_column_fits_every_label():
    width, right_pad = _field_rule()
    content = width - right_pad
    clipped = {k: v for k, v in _all_form_labels().items() if len(v) > content}
    assert not clipped, (
        f"#field width {width} leaves {content} content cells and clips: "
        + ", ".join(f"{k} {v!r} ({len(v)})" for k, v in clipped.items())
    )
