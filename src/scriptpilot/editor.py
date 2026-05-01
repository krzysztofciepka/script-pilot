from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.app import App

from scriptpilot.models import AppConfig


class EditorError(Exception):
    """Raised when no usable editor is available or the editor cannot be launched."""


def resolve_editor(config: AppConfig) -> list[str]:
    """Resolve the editor command to use.

    Priority: ``config.editor`` -> ``$VISUAL`` -> ``$EDITOR`` -> ``vi``.
    Returns the argv list (split via ``shlex``). Raises ``EditorError`` if
    even ``vi`` is not on ``PATH``.
    """
    candidates: list[str] = []
    if config.editor and config.editor.strip():
        candidates.append(config.editor)
    visual = os.environ.get("VISUAL", "").strip()
    if visual:
        candidates.append(visual)
    editor_env = os.environ.get("EDITOR", "").strip()
    if editor_env:
        candidates.append(editor_env)
    candidates.append("vi")

    for cmd in candidates:
        parts = shlex.split(cmd)
        if not parts:
            continue
        if shutil.which(parts[0]) is not None:
            return parts

    raise EditorError(
        f"no editor found on PATH (tried: "
        f"{', '.join(c.split()[0] for c in candidates if c.split())})"
    )


def _run_editor(argv: list[str], path: Path) -> None:
    """Invoke ``argv + [path]`` synchronously. Raises ``EditorError`` if the
    binary can't be launched. Non-zero exit codes from the editor itself are
    tolerated -- the caller decides what to do with whatever is on disk.
    """
    try:
        subprocess.run([*argv, str(path)], check=False)
    except FileNotFoundError as e:
        raise EditorError(f"editor '{argv[0]}' not found on PATH") from e
    except OSError as e:
        raise EditorError(f"could not launch editor '{argv[0]}': {e}") from e


def edit_file(app: "App", config: AppConfig, path: Path) -> None:
    """Suspend the Textual app, run the resolved editor on ``path``, then resume.

    Raises ``EditorError`` if no editor is available or the editor can't be
    launched.
    """
    argv = resolve_editor(config)
    with app.suspend():
        _run_editor(argv, path)
