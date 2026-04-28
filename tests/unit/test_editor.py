"""Tests for expense._editor.edit_text — the $EDITOR helper used by `reconcile reorder`."""

import shlex
import sys
from pathlib import Path

import pytest

from expense import _editor


@pytest.fixture
def fake_editor(tmp_path):
    """Build a fake editor as a Python script. Returns (cmd, script_path)."""

    def _build(behavior: str, *, returncode: int = 0) -> str:
        script = tmp_path / "fake_editor.py"
        if behavior == "overwrite":
            body = (
                "import sys\n"
                "with open(sys.argv[1], 'w', encoding='utf-8') as f:\n"
                "    f.write('REORDERED CONTENT\\n')\n"
            )
        elif behavior == "noop":
            body = "import sys\n# leave the file unchanged\n"
        elif behavior == "empty":
            body = (
                "import sys\nwith open(sys.argv[1], 'w', encoding='utf-8') as f:\n    f.write('')\n"
            )
        elif behavior == "delete":
            body = "import sys, os\nos.remove(sys.argv[1])\n"
        elif behavior == "fail":
            body = f"import sys\nsys.exit({returncode})\n"
        else:
            raise ValueError(behavior)
        script.write_text(body, encoding="utf-8")
        return f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"

    return _build


def test_edit_text_returns_overwritten_content(fake_editor):
    cmd = fake_editor("overwrite")
    result = _editor.edit_text("INITIAL\n", editor=cmd)
    assert result == "REORDERED CONTENT\n"


def test_edit_text_returns_none_when_unchanged(fake_editor):
    cmd = fake_editor("noop")
    result = _editor.edit_text("INITIAL\n", editor=cmd)
    assert result is None


def test_edit_text_returns_none_when_emptied(fake_editor):
    cmd = fake_editor("empty")
    result = _editor.edit_text("INITIAL\n", editor=cmd)
    assert result is None


def test_edit_text_returns_none_when_editor_exits_nonzero(fake_editor):
    cmd = fake_editor("fail", returncode=1)
    result = _editor.edit_text("INITIAL\n", editor=cmd)
    assert result is None


def test_edit_text_returns_none_when_file_deleted(fake_editor):
    cmd = fake_editor("delete")
    result = _editor.edit_text("INITIAL\n", editor=cmd)
    assert result is None


def test_edit_text_handles_missing_editor_command(capsys):
    result = _editor.edit_text("INITIAL\n", editor="this-binary-does-not-exist-xyz")
    assert result is None
    err = capsys.readouterr().err
    assert "editor command not found" in err


def test_edit_text_warns_when_editor_unset(monkeypatch, capsys):
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.setattr("subprocess.run", lambda argv, check: _DummyResult(0))

    _ = _editor.edit_text("INITIAL\n", editor=None)
    err = capsys.readouterr().err
    assert "$EDITOR is not set" in err


class _DummyResult:
    def __init__(self, rc):
        self.returncode = rc


def test_edit_text_cleans_up_temp_file(monkeypatch, tmp_path):
    """The temp file must be unlinked on every exit path."""
    captured: list[str] = []

    def fake_run(argv, check):
        path = argv[-1]
        captured.append(path)
        Path(path).write_text("EDITED\n", encoding="utf-8")
        return _DummyResult(0)

    monkeypatch.setattr("subprocess.run", fake_run)

    result = _editor.edit_text("INITIAL\n", editor="fake")
    assert result == "EDITED\n"
    assert captured, "expected the editor to be invoked"
    assert not Path(captured[-1]).exists(), "temp file should be unlinked"


def test_edit_text_handles_multi_word_editor(monkeypatch, capsys):
    """`code -w` style editors are split via shlex."""
    captured_argv: list[list[str]] = []

    def fake_run(argv, check):
        captured_argv.append(list(argv))
        path = argv[-1]
        Path(path).write_text("AFTER\n", encoding="utf-8")
        return _DummyResult(0)

    monkeypatch.setattr("subprocess.run", fake_run)

    result = _editor.edit_text("BEFORE\n", editor="code -w --extra")
    assert result == "AFTER\n"
    assert captured_argv[0][:3] == ["code", "-w", "--extra"]
