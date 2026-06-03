from __future__ import annotations

import re
import subprocess
from pathlib import Path

_MAX_OUTPUT = 10_000  # chars

_DENY_PATTERNS = [
    r"\brm\s+-[a-z]*r[a-z]*f?\s+/",  # rm -rf /
    r"\bsudo\b",
    r"\bmkfs\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bdd\s+if=",
    r":\(\)\s*\{",  # fork bomb
]
_DENY_RE = [re.compile(p) for p in _DENY_PATTERNS]


def is_denied(cmd: str) -> bool:
    """True when the command matches an obviously destructive pattern."""
    return any(r.search(cmd) for r in _DENY_RE)


def run_bash(cmd: str, cwd: Path, timeout: int) -> str:
    """Run a shell command in ``cwd``; return ``exit <code>\\n<output>``."""
    if is_denied(cmd):
        return "blocked: command matches a destructive-operation denylist"
    try:
        proc = subprocess.run(
            ["bash", "-c", cmd],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"exit -1\nbash command timed out after {timeout}s"
    output = (proc.stdout or "") + (proc.stderr or "")
    if len(output) > _MAX_OUTPUT:
        output = output[:_MAX_OUTPUT] + "\n…[output truncated]"
    return f"exit {proc.returncode}\n{output}".rstrip()
