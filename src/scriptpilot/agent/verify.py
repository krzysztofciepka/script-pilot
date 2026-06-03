from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from scriptpilot.paths import EXTENSIONS

# Interpreter used to syntax-check each script type.
_SYNTAX_CHECK = {
    "bash": ["bash", "-n"],
    "python": ["python3", "-m", "py_compile"],
    "js": ["node", "--check"],
}

_INTERPRETERS = {"bash": "bash", "python": "python3", "js": "node"}

# Matches an interpreter invoking a script file, e.g. ``node foo.js`` or
# ``python3 /app/run.py``. Group 1 is the referenced path.
_REF_RE = re.compile(
    r"\b(?:node|python3?|bash|sh)\s+([^\s;|&'\"]+\.(?:js|mjs|cjs|py|sh))"
)


@dataclass
class LayerResult:
    name: str  # "syntax" | "resolve" | "run"
    passed: bool
    detail: str


@dataclass
class VerifyResult:
    ok: bool
    layers: list[LayerResult] = field(default_factory=list)

    def summary(self) -> str:
        head = "VERIFY PASSED" if self.ok else "VERIFY FAILED"
        body = "\n".join(
            f"  [{'ok' if l.passed else 'FAIL'}] {l.name}: {l.detail}"
            for l in self.layers
        )
        return f"{head}\n{body}"


def find_missing_references(script_type: str, content: str, base_dir: Path) -> list[str]:
    """Return referenced script paths that do not exist on disk.

    Catches the classic bug where the body is e.g. ``node
    /app/cloud-build-trigger.js`` but no such file was written. A referenced
    path is resolved relative to ``base_dir`` (absolute paths used as-is) and
    reported when it is missing and is not the draft file itself.
    """
    missing: list[str] = []
    draft_name = f"script{EXTENSIONS.get(script_type, '')}"
    for raw in _REF_RE.findall(content):
        ref = Path(raw)
        resolved = ref if ref.is_absolute() else (base_dir / ref)
        if resolved.name == draft_name:
            continue
        if not resolved.exists():
            missing.append(raw)
    return missing


def _run_check(argv: list[str], timeout: int = 20) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except FileNotFoundError as e:
        return False, str(e)
    detail = (proc.stderr or proc.stdout or "").strip()[:500]
    return proc.returncode == 0, detail or f"exit {proc.returncode}"


def verify_draft(
    script_type: str,
    draft_path: Path,
    *,
    safe_run: list[str] | None = None,
) -> VerifyResult:
    """Verify a draft in side-effect-free layers.

    L1 syntax: ``bash -n`` / ``python -m py_compile`` / ``node --check``.
    L2 resolve: interpreter on PATH; entrypoint exists; no missing references.
    L3 run: only when ``safe_run`` argv is provided (e.g. ``["--help"]``).
    """
    layers: list[LayerResult] = []
    content = draft_path.read_text() if draft_path.exists() else ""

    # L1 — syntax
    check = _SYNTAX_CHECK.get(script_type)
    if check is None:
        layers.append(LayerResult("syntax", False, f"unknown type {script_type!r}"))
        return VerifyResult(ok=False, layers=layers)
    ok, detail = _run_check([*check, str(draft_path)])
    layers.append(LayerResult("syntax", ok, "valid syntax" if ok else detail))
    if not ok:
        return VerifyResult(ok=False, layers=layers)

    # L2 — resolve
    interp = _INTERPRETERS[script_type]
    problems: list[str] = []
    if shutil.which(interp) is None:
        problems.append(f"interpreter {interp!r} not on PATH")
    if not draft_path.exists():
        problems.append("entrypoint file missing")
    missing = find_missing_references(script_type, content, draft_path.parent)
    if missing:
        problems.append("references missing files: " + ", ".join(missing))
    resolve_ok = not problems
    layers.append(
        LayerResult("resolve", resolve_ok, "resolved" if resolve_ok else "; ".join(problems))
    )
    if not resolve_ok:
        return VerifyResult(ok=False, layers=layers)

    # L3 — safe run (opt-in)
    if safe_run is not None:
        argv = [interp, str(draft_path), *safe_run]
        ok, detail = _run_check(argv)
        layers.append(LayerResult("run", ok, detail))
        if not ok:
            return VerifyResult(ok=False, layers=layers)

    return VerifyResult(ok=True, layers=layers)
