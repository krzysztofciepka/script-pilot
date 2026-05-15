from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import signal
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from scriptpilot.models import OutputLine, Script
from scriptpilot.secrets import load_secrets

INTERPRETERS = {
    "bash": "bash",
    "js": "node",
    # "python" resolved dynamically from python_command.
}


class InterpreterNotFoundError(Exception):
    """Raised when the required interpreter is not on PATH."""


class ScriptCwdError(Exception):
    """Raised when a Script's configured cwd is missing or invalid."""


@dataclass
class ExecutionResult:
    exit_code: int
    timed_out: bool
    duration: float
    cancelled: bool = False


def _resolve_cwd(script_cwd: str | None) -> Path:
    """Resolve the cwd to use for a script run.

    ``None``, empty, or whitespace-only → ``Path.home()``.
    Otherwise expand ``~`` and verify the path exists and is a directory;
    raise ``ScriptCwdError`` if not.
    """
    if not script_cwd or not script_cwd.strip():
        return Path.home()
    expanded = Path(script_cwd).expanduser()
    if not expanded.exists():
        raise ScriptCwdError(f"cwd does not exist: {expanded}")
    if not expanded.is_dir():
        raise ScriptCwdError(f"cwd is not a directory: {expanded}")
    return expanded


def _resolve_command(script_type: str, python_command: str) -> list[str]:
    """Return the argv prefix (interpreter + flags) for a script type."""
    if script_type == "python":
        cmd = python_command.strip() or "python3"
        parts = shlex.split(cmd)
    else:
        parts = [INTERPRETERS[script_type]]
    exe = shutil.which(parts[0])
    if exe is None:
        raise InterpreterNotFoundError(f"{parts[0]} not found on PATH")
    return [exe, *parts[1:]]


def _ts_dir() -> str:
    """Filesystem-safe UTC timestamp for SCRIPTPILOT_OUTPUT_DIR (no colons)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")


async def execute_script(
    script: Script,
    arg_values: list[str] | None = None,
    on_output: Callable[[OutputLine], None] | None = None,
    *,
    script_path: Path,
    python_command: str = "python3",
    cancel_event: asyncio.Event | None = None,
) -> ExecutionResult:
    """Execute a script (read from ``script_path``) and stream output."""
    cmd_prefix = _resolve_command(script.type, python_command)
    cwd = _resolve_cwd(script.cwd)
    secrets = load_secrets()

    output_dir = (
        Path.home() / ".scriptpilot" / "outputs" / script.id / _ts_dir()
    )
    env = {
        **os.environ,
        **secrets,
        "SCRIPTPILOT_OUTPUT_DIR": str(output_dir),
        **script.env,
    }

    cmd = [*cmd_prefix, str(script_path)]
    if arg_values:
        cmd.extend(arg_values)

    start = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd),
        env=env,
        start_new_session=True,
    )

    timed_out = False
    cancelled = False

    async def _read(stream, label: Literal["stdout", "stderr"]):
        if stream is None:
            return
        while True:
            raw = await stream.readline()
            if not raw:
                break
            text = raw.decode(errors="replace").rstrip("\n")
            if on_output:
                on_output(OutputLine(label, text))

    read_tasks = [
        asyncio.create_task(_read(proc.stdout, "stdout")),
        asyncio.create_task(_read(proc.stderr, "stderr")),
    ]

    if cancel_event is None:
        try:
            await asyncio.wait_for(proc.wait(), timeout=script.timeout)
        except asyncio.TimeoutError:
            timed_out = True
    else:
        wait_task = asyncio.create_task(proc.wait())
        cancel_task = asyncio.create_task(cancel_event.wait())
        done, pending = await asyncio.wait(
            [wait_task, cancel_task],
            timeout=script.timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
        if not done:
            timed_out = True
        elif cancel_task in done and cancel_event.is_set():
            cancelled = True

    if timed_out or cancelled:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()

    await asyncio.gather(*read_tasks)

    duration = time.monotonic() - start
    return ExecutionResult(
        exit_code=proc.returncode if proc.returncode is not None else -1,
        timed_out=timed_out,
        cancelled=cancelled,
        duration=duration,
    )
