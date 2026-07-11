"""Step 9 gate — regression armor for the CLI surface.

Walks the Typer command tree and asserts:
  - every leaf command has a non-empty docstring
  - every docstring contains an `Example:` block (gate criterion 1)
  - every read command exposes a --json flag (gate criterion 2)
  - every destructive command (delete/archive/revert/clear) exposes --yes
    (the confirm-destructive convention)
  - every flag used in an `Example:` line exists on that command, and
    int-typed flags get int-looking values (copy-paste safety)

If a future PR adds a new command or wrapper (quick-add parser, etc.)
and forgets these conventions, this test will fail loudly.
"""

import inspect
import re
import shlex

import click
import pytest
from typer.main import get_command
from typer.testing import CliRunner

from expense.__main__ import app

READ_COMMAND_LEAVES: set[tuple[str, ...]] = {
    ("dashboard",),
    ("ping",),
    ("whoami",),
    ("sync",),
    ("config", "get"),
    ("auth", "bootstrap"),
    ("auth", "me"),
    ("auth", "profile"),
    ("auth", "settings"),
    ("reports", "monthly"),
    ("rates", "get"),
}


def _walk(typer_app, prefix=()):
    for cmd in typer_app.registered_commands:
        name = cmd.name or cmd.callback.__name__.rstrip("_")
        yield (*prefix, name), cmd.callback
    for grp in typer_app.registered_groups:
        yield from _walk(grp.typer_instance, (*prefix, grp.name))


_LEAVES = list(_walk(app))
_LEAF_IDS = [" ".join(path) for path, _ in _LEAVES]


def _is_read(path: tuple[str, ...]) -> bool:
    if path in READ_COMMAND_LEAVES:
        return True
    return path[-1] in {"list", "get"}


def test_typer_tree_walk_finds_expected_command_count():
    assert len(_LEAVES) >= 50, (
        f"Expected at least 50 leaf commands across the CLI; "
        f"walker found {len(_LEAVES)} — Typer introspection may be broken."
    )


@pytest.mark.parametrize(("path", "callback"), _LEAVES, ids=_LEAF_IDS)
def test_command_has_example_in_docstring(path, callback):
    cmd_name = " ".join(path)
    doc = inspect.getdoc(callback)
    assert doc, f"`expense {cmd_name}` has no docstring (gate criterion 1)"
    assert "Example:" in doc, (
        f"`expense {cmd_name}` docstring is missing an `Example:` block (Step 9 gate criterion 1)"
    )


_READ_LEAVES = [(path, cb) for path, cb in _LEAVES if _is_read(path)]
_READ_LEAF_IDS = [" ".join(path) for path, _ in _READ_LEAVES]


@pytest.mark.parametrize(("path", "callback"), _READ_LEAVES, ids=_READ_LEAF_IDS)
def test_read_command_has_json_flag(path, callback):
    sig = inspect.signature(callback)
    assert "json_output" in sig.parameters, (
        f"`expense {' '.join(path)}` is a read command but has no --json flag "
        f"(Step 9 gate criterion 2)"
    )


# --- Confirm-destructive convention ------------------------------------------
# CLAUDE.md non-negotiable: deletes, reverts, and clears prompt for confirmation
# unless --yes is passed. Matched by leaf name — a destructive command under a
# new name (e.g. `remove`) must be added to the set. `archive`/`unarchive`/
# `restore` are deliberately prompt-free — reversible toggles, not destruction
# (archive reclassified 2026-07-11; see decisions.md).

_DESTRUCTIVE_NAMES = {"delete", "revert", "clear"}
_DESTRUCTIVE_LEAVES = [(path, cb) for path, cb in _LEAVES if path[-1] in _DESTRUCTIVE_NAMES]
_DESTRUCTIVE_LEAF_IDS = [" ".join(path) for path, _ in _DESTRUCTIVE_LEAVES]


def test_destructive_walker_finds_known_commands():
    # Pin the count: a drop means a destructive command was renamed out of the
    # name set above and now evades the --yes guard — extend the set instead.
    assert len(_DESTRUCTIVE_LEAVES) == 8, sorted(_DESTRUCTIVE_LEAF_IDS)


@pytest.mark.parametrize(("path", "callback"), _DESTRUCTIVE_LEAVES, ids=_DESTRUCTIVE_LEAF_IDS)
def test_destructive_command_requires_yes(path, callback):
    sig = inspect.signature(callback)
    assert "yes" in sig.parameters, (
        f"`expense {' '.join(path)}` is destructive but exposes no --yes flag "
        f"(confirm-destructive convention)"
    )


# --- Example-line copy-paste safety -----------------------------------------
# Docstring examples must use flags the command actually declares. Flags like
# --account-id map to params named `account`, so validation goes through
# click's declared option strings, not Python parameter names.

_CLICK_ROOT = get_command(app)


def _click_leaves(cmd, prefix=()):
    if isinstance(cmd, click.Group):
        for name, sub in cmd.commands.items():
            yield from _click_leaves(sub, (*prefix, name))
    else:
        yield prefix, cmd


_CLICK_LEAVES = list(_click_leaves(_CLICK_ROOT))
_CLICK_LEAF_IDS = [" ".join(path) for path, _ in _CLICK_LEAVES]

# Examples may legitimately show root flags (e.g. --no-cache, --verbose).
_ROOT_FLAGS = {
    opt
    for param in _CLICK_ROOT.params
    for opt in (*param.opts, *param.secondary_opts)
    if opt.startswith("--")
}

_FLAG_RE = re.compile(r"--[a-zA-Z0-9][a-zA-Z0-9-]*")


def _example_blocks(doc: str):
    """Yield each `Example:` line joined with its indented continuation lines."""
    lines = doc.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("Example:"):
            block = [lines[i].strip()]
            i += 1
            while i < len(lines) and lines[i].strip() and lines[i][:1].isspace():
                block.append(lines[i].strip())
                i += 1
            yield " ".join(block)
        else:
            i += 1


def _example_tokens(block: str) -> list[str]:
    try:
        tokens = shlex.split(block)
    except ValueError:  # unbalanced quote in prose — fall back to whitespace split
        tokens = block.split()
    flat: list[str] = []
    for tok in tokens:
        if tok.startswith("--") and "=" in tok:
            flag, _, value = tok.partition("=")
            flat.extend([flag, value])
        else:
            flat.append(tok)
    return flat


@pytest.mark.parametrize(("path", "command"), _CLICK_LEAVES, ids=_CLICK_LEAF_IDS)
def test_docstring_example_flags_exist(path, command):
    cmd_name = " ".join(path)
    allowed = set(_ROOT_FLAGS)
    int_flags = set()
    for param in command.params:
        for opt in (*param.opts, *param.secondary_opts):
            if opt.startswith("--"):
                allowed.add(opt)
                if isinstance(param.type, click.types.IntParamType):
                    int_flags.add(opt)

    for block in _example_blocks(command.help or ""):
        for flag in _FLAG_RE.findall(block):
            assert flag in allowed, (
                f"`expense {cmd_name}` docstring example uses {flag}, "
                f"which is not a flag on that command: {block!r}"
            )
        tokens = _example_tokens(block)
        for pos, tok in enumerate(tokens):
            if tok not in int_flags:
                continue
            value = tokens[pos + 1] if pos + 1 < len(tokens) else ""
            if value.startswith("<") and value.endswith(">"):
                continue  # placeholder like <id>
            assert re.fullmatch(r"-?\d+", value), (
                f"`expense {cmd_name}` docstring example gives int-typed {tok} "
                f"the value {value!r}: {block!r}"
            )


def test_root_help_renders():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for group in ("config", "auth", "accounts", "dashboard"):
        assert group in result.stdout, f"`expense --help` is missing `{group}`"
