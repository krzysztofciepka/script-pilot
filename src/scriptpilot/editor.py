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
