from __future__ import annotations

import shutil
import subprocess
import sys


class ClipboardUnavailable(Exception):
    """No clipboard backend (pyperclip, wl-copy, xclip, pbcopy) was found or worked."""


def copy(text: str) -> None:
    """Copy text to the system clipboard.

    Tries pyperclip first (if importable), then shell-based backends:
    wl-copy (Wayland), xclip -selection clipboard (X11), pbcopy (macOS).
    Raises ClipboardUnavailable if no backend works.
    """
    try:
        import pyperclip  # type: ignore

        pyperclip.copy(text)
        return
    except ImportError:
        pass
    except Exception:
        pass

    backends: list[list[str]] = []
    if sys.platform == "darwin":
        backends.append(["pbcopy"])
    else:
        backends.append(["wl-copy"])
        backends.append(["xclip", "-selection", "clipboard"])

    for cmd in backends:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            subprocess.run(cmd, input=text.encode(), check=True)
            return
        except subprocess.CalledProcessError:
            continue

    raise ClipboardUnavailable(
        "no clipboard backend found (install pyperclip, wl-copy, xclip, or pbcopy)"
    )
