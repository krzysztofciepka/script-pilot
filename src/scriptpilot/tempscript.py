from __future__ import annotations

import tempfile
from pathlib import Path

from scriptpilot.paths import EXTENSIONS


def materialize_draft(content: str, script_type: str) -> Path:
    """Write ``content`` to a tempfile with the extension for ``script_type``.

    The caller is responsible for unlinking the returned path
    (``Path.unlink(missing_ok=True)`` in a ``finally``).

    Raises ``KeyError`` if ``script_type`` isn't in ``paths.EXTENSIONS`` --
    a programmer error, not a user-facing condition.
    """
    suffix = EXTENSIONS[script_type]
    fd, name = tempfile.mkstemp(suffix=suffix, prefix="scriptpilot-draft-")
    path = Path(name)
    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path
