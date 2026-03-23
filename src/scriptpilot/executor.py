from __future__ import annotations

import asyncio
import os
import signal
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from scriptpilot.models import Script

INTERPRETERS = {
    "bash": "bash",
    "python": "python3",
    "js": "node",
}

EXTENSIONS = {
    "bash": ".sh",
    "python": ".py",
    "js": ".js",
}


class InterpreterNotFoundError(Exception):
    """Raised when the required interpreter is not on PATH."""


@dataclass
class ExecutionResult:
    exit_code: int
    timed_out: bool
    duration: float


def _get_interpreter(script_type: str) -> str | None:
    """Return the interpreter path if found on PATH, else None."""
    cmd = INTERPRETERS[script_type]
    return shutil.which(cmd)


async def execute_script(
    script: Script,
    arg_values: list[str] | None = None,
    on_output: Callable[[str], None] | None = None,
) -> ExecutionResult:
    """Execute a script and stream output."""
    interpreter = _get_interpreter(script.type)
    if interpreter is None:
        raise InterpreterNotFoundError(
            f"{INTERPRETERS[script.type]} not found on PATH"
        )

    ext = EXTENSIONS[script.type]
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=ext)
    try:
        with os.fdopen(tmp_fd, "w") as f:
            f.write(script.content)

        if script.type == "bash":
            os.chmod(tmp_path, 0o755)

        cmd = [interpreter, tmp_path]
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
    finally:
        Path(tmp_path).unlink(missing_ok=True)
