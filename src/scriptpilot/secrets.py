from __future__ import annotations

from pathlib import Path

SECRETS_PATH = Path.home() / ".scriptpilot" / ".env"


def load_secrets(path: Path = SECRETS_PATH) -> dict[str, str]:
    """Parse a tiny dotenv file. Returns {} if missing or unreadable.

    Supports: ``KEY=VALUE`` per line, whitespace around ``=``, ``#`` comments,
    blank lines, and matching surrounding quotes (``"..."`` or ``'...'``)
    around values. No interpolation, no ``export`` prefix, no multiline values.
    """
    if not path.exists():
        return {}
    try:
        text = path.read_text()
    except OSError:
        return {}

    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        out[key] = value
    return out
