"""Step 9 gate — regression armor for the CLI surface.

Walks the Typer command tree and asserts:
  - every leaf command has a non-empty docstring
  - every docstring contains an `Example:` block (gate criterion 1)
  - every read command exposes a --json flag (gate criterion 2)

If a future PR adds a new command or wrapper (quick-add parser, etc.)
and forgets these conventions, this test will fail loudly.
"""

import inspect

import pytest
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


@pytest.mark.parametrize(("path", "callback"), _LEAVES, ids=_LEAF_IDS)
def test_read_command_has_json_flag(path, callback):
    if not _is_read(path):
        pytest.skip(f"`expense {' '.join(path)}` is not a read command")
    sig = inspect.signature(callback)
    assert "json_output" in sig.parameters, (
        f"`expense {' '.join(path)}` is a read command but has no --json flag "
        f"(Step 9 gate criterion 2)"
    )


def test_root_help_renders():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for group in ("config", "auth", "accounts", "dashboard"):
        assert group in result.stdout, f"`expense --help` is missing `{group}`"
