from __future__ import annotations

import re
import subprocess
from pathlib import Path

from scriptpilot.agent.verify import verify_draft

_MAX_OUTPUT = 10_000  # chars

_DENY_PATTERNS = [
    r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*\s+/",  # rm -rf / / -fr / -r (recursive rm of abs path)
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


TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": (
                "Run a read-oriented bash command (ls, cat, grep, …) in the "
                "session working directory. The draft is script.sh/.py/.js there."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "The bash command."}
                },
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_script",
            "description": (
                "Write new draft code and/or patch metadata (name, description, "
                "type, args, env, timeout, cwd, arg_style, tags)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Full new script body."},
                    "meta_patch": {
                        "type": "object",
                        "description": "Partial Script metadata to merge.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify",
            "description": (
                "Verify the current draft (syntax, file/interpreter resolution, "
                "and an optional safe run). Pass safe_run only for side-effect-free "
                "invocations like ['--help']."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "safe_run": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional safe argv to execute, e.g. ['--help'].",
                    }
                },
            },
        },
    },
]


def dispatch_tool(name: str, arguments: dict, session, *, bash_timeout: int) -> str:
    """Execute a tool call against ``session``; return the tool result text."""
    if name == "bash":
        return run_bash(arguments.get("cmd", ""), session.work_dir, bash_timeout)
    if name == "update_script":
        return session.apply_update(
            code=arguments.get("code"), meta_patch=arguments.get("meta_patch")
        )
    if name == "verify":
        result = verify_draft(
            session.draft.type, session.draft_path, safe_run=arguments.get("safe_run")
        )
        return result.summary()
    return f"unknown tool: {name}"
