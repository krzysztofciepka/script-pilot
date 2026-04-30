from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import signal
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from scriptpilot.models import Script

INTERPRETERS = {
    "bash": "bash",
    "js": "node",
    # "python" resolved dynamically from python_command.
}


class InterpreterNotFoundError(Exception):
    """Raised when the required interpreter is not on PATH."""


@dataclass
class ExecutionResult:
    exit_code: int
    timed_out: bool
    duration: float


def _resolve_command(script_type: str, python_command: str) -> list[str]:
    """Return the argv prefix (interpreter + flags) for a script type.

    For ``python``, ``python_command`` is shlex-split and the first token is
    looked up on PATH. Empty / whitespace-only ``python_command`` falls back
    to ``python3`` — a safety net for direct callers (tests, scripts) so they
    don't need ``uv`` installed. The production flow always passes the
    resolved ``AppConfig.python_command`` through.
    """
    if script_type == "python":
        cmd = python_command.strip() or "python3"
        parts = shlex.split(cmd)
    else:
        parts = [INTERPRETERS[script_type]]
    exe = shutil.which(parts[0])
    if exe is None:
        raise InterpreterNotFoundError(f"{parts[0]} not found on PATH")
    return [exe, *parts[1:]]


async def execute_script(
    script: Script,
    arg_values: list[str] | None = None,
    on_output: Callable[[str], None] | None = None,
    *,
    script_path: Path,
    python_command: str = "python3",
) -> ExecutionResult:
    """Execute a script (read from ``script_path``) and stream output."""
    cmd_prefix = _resolve_command(script.type, python_command)

    cmd = [*cmd_prefix, str(script_path)]
    if arg_values:
        cmd.extend(arg_values)

    start = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )

    timed_out = False

    async def _read_output():
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode(errors="replace").rstrip("\n")
            if on_output:
                on_output(text)

    read_task = asyncio.create_task(_read_output())

    try:
        await asyncio.wait_for(proc.wait(), timeout=script.timeout)
    except asyncio.TimeoutError:
        timed_out = True
        # Kill the entire process group so child processes (e.g. sleep)
        # also die and release the pipe.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()

    # Once the process group is dead, stdout closes and readline
    # returns b"", so read_task will finish promptly.
    await read_task

    duration = time.monotonic() - start
    return ExecutionResult(
        exit_code=proc.returncode if proc.returncode is not None else -1,
        timed_out=timed_out,
        duration=duration,
    )
