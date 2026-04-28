"""Open an external editor on a temp file and return the result.

First subprocess + tempfile pattern in this codebase. Used by
`expense reconcile reorder` for git-rebase-i-style bulk reordering.
Stdlib only.
"""

import os
import shlex
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile

import typer


def edit_text(initial_text: str, *, suffix: str = ".txt", editor: str | None = None) -> str | None:
    """Launch the user's $EDITOR on a temp file pre-populated with initial_text.

    Returns the saved text on success; returns None when the user aborts
    (editor exits non-zero, file is empty, or the file is unchanged).

    The temp file is cleaned up in all paths.

    `editor` overrides `$EDITOR` for a single invocation. If neither is set,
    falls back to `vi` and prints a one-time hint to stderr.
    """
    resolved_editor = editor or os.environ.get("EDITOR") or ""
    if not resolved_editor.strip():
        typer.echo(
            "Hint: $EDITOR is not set. Falling back to 'vi'. "
            "Set $EDITOR to your preferred editor (e.g. `export EDITOR=nano` "
            'or `export EDITOR="code -w"`) for a friendlier experience.',
            err=True,
        )
        resolved_editor = "vi"
    editor_argv = shlex.split(resolved_editor)

    with NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8") as tmp:
        tmp.write(initial_text)
        tmp_path = tmp.name

    try:
        try:
            result = subprocess.run([*editor_argv, tmp_path], check=False)
        except FileNotFoundError:
            typer.echo(
                f"Error: editor command not found: {resolved_editor!r}",
                err=True,
            )
            return None

        if result.returncode != 0:
            return None

        try:
            edited = Path(tmp_path).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

        if not edited.strip():
            return None
        if edited == initial_text:
            return None

        return edited
    finally:
        try:
            Path(tmp_path).unlink()
        except FileNotFoundError:
            pass
