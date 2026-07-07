"""Doc link-rot guard (CLAUDE.md "Docs must outlive any one contributor").

Every relative markdown link in the top-level docs must resolve. Links into
the sibling engine repo (../expense_world_engine) are verified only when that
checkout is present — the sibling layout is a documented assumption (README
"Checkout layout"), not something CI can rely on.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_ROOT = REPO_ROOT.parent / "expense_world_engine"

DOC_FILES = sorted(
    [REPO_ROOT / "AGENTS.md", REPO_ROOT / "CLAUDE.md", REPO_ROOT / "README.md"]
    + list((REPO_ROOT / "docs").glob("*.md"))
)

_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_FENCED_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`\n]*`")


def _relative_targets(doc: Path) -> list[str]:
    text = _INLINE_CODE.sub("", _FENCED_BLOCK.sub("", doc.read_text()))
    targets = []
    for raw in _LINK.findall(text):
        target = raw.split("#", 1)[0]  # drop in-page anchors
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        targets.append(target)
    return targets


def test_expected_doc_set_present():
    names = {p.name for p in DOC_FILES}
    assert {"AGENTS.md", "CLAUDE.md", "README.md", "decisions.md", "cli-spec.md"} <= names


def test_relative_doc_links_resolve():
    broken = []
    for doc in DOC_FILES:
        for target in _relative_targets(doc):
            resolved = (doc.parent / target).resolve()
            if resolved.is_relative_to(REPO_ROOT):
                if not resolved.exists():
                    broken.append(f"{doc.relative_to(REPO_ROOT)} -> {target}")
            elif ENGINE_ROOT.exists() and not resolved.exists():
                broken.append(f"{doc.relative_to(REPO_ROOT)} -> {target} (engine repo)")
    assert not broken, "Broken relative links:\n  " + "\n  ".join(broken)
