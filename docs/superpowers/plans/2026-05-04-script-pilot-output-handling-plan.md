# ScriptPilot — Output Handling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add output handling features to ScriptPilot — save/copy bindings (`o`/`y`), separated stderr with chronological storage and red styling, JSON viewer (`J`), and a `SCRIPTPILOT_OUTPUT_DIR` env var convention.

**Architecture:** A new `OutputLine` NamedTuple flows from the executor (where stdout and stderr are read concurrently and tagged) through `RunRecord.lines` (chronological storage replaces flat `output: str`) to the `MainPanel` (which styles stderr red, tracks a "currently displayed run", and exposes three bindings that operate on it). Two new modal screens (`SavePromptScreen`, `JsonViewScreen`) and a new `clipboard.py` helper module support the bindings. Auto-showing the last run on script selection makes the bindings useful without a fresh run.

**Tech Stack:** Python 3.10+, Textual (TUI), Pydantic v2 models, pytest with asyncio, optional `pyperclip` extra.

**Spec:** `docs/superpowers/specs/2026-05-04-script-pilot-output-handling-design.md`

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `src/scriptpilot/models.py` | Modify | Add `OutputLine` NamedTuple; reshape `RunRecord` (drop `output: str`, add `lines: list[OutputLine]` + helpers) |
| `src/scriptpilot/executor.py` | Modify | Read stdout and stderr separately, tag each line, set `SCRIPTPILOT_OUTPUT_DIR` env var |
| `src/scriptpilot/clipboard.py` | Create | Cross-platform clipboard `copy()` with pyperclip → wl-copy → xclip → pbcopy fallback chain |
| `src/scriptpilot/screens/save_prompt.py` | Create | `SavePromptScreen` modal: prompt for save path, return `Path | None` |
| `src/scriptpilot/screens/json_view.py` | Create | `JsonViewScreen` modal: render parsed JSON via `rich.json.JSON` |
| `src/scriptpilot/widgets/main_panel.py` | Modify | Pure parse helpers, stderr red styling, run-state tracking (`_displayed_run`, `_is_running`), three bindings (`o`/`y`/`J`) and their actions |
| `src/scriptpilot/screens/main.py` | Modify | Auto-show last run on script selection; collect `OutputLine`s during run; build `RunRecord(lines=...)` |
| `pyproject.toml` | Modify | Add `[project.optional-dependencies] clipboard = ["pyperclip>=1.8"]` |
| `tests/test_models.py` | Modify | Cover `OutputLine` and `RunRecord.lines` round-trip + helpers |
| `tests/test_history.py` | Modify | Migrate `output=` fixtures to `lines=`; add round-trip-through-disk test |
| `tests/test_executor.py` | Modify | Migrate string-callback tests to `OutputLine`; add stderr split + env var tests |
| `tests/test_clipboard.py` | Create | Cover pyperclip + shell-fallback paths via mocks |
| `tests/test_main_panel.py` | Create | Cover pure helpers (`_try_parse_json`, `_last_nonempty_line`, `_safe_name`) |

---

## Working directory

All commands assume working directory `/home/kc/repos/script-pilot`. Tests use `uv run pytest`.

---

## Task 1: Add `OutputLine` and reshape `RunRecord`

**Files:**
- Modify: `src/scriptpilot/models.py`
- Modify: `tests/test_models.py`
- Modify: `tests/test_history.py`

This task replaces `RunRecord.output: str` with `RunRecord.lines: list[OutputLine]`. The HistoryStore tests use `output=` in their fixtures — they break in lockstep and are migrated here. Other call sites (executor, MainScreen) still reference `output=`, which we will fix in subsequent tasks; the project will not be in a fully working state between Task 1 and Task 3 (executor uses `output` is no longer assigned; MainScreen builds `RunRecord(output=...)` which will now fail validation). To stay green between tasks, this task's commit also adds shim usage in MainScreen — addressed at Step 6.

- [ ] **Step 1: Write failing tests for `OutputLine` and reshaped `RunRecord`**

Append to `tests/test_models.py`:

```python
from scriptpilot.models import OutputLine, RunRecord


class TestOutputLine:
    def test_namedtuple_shape(self):
        ol = OutputLine("stdout", "hello")
        assert ol.stream == "stdout"
        assert ol.line == "hello"
        assert ol[0] == "stdout"
        assert ol[1] == "hello"

    def test_stderr_value(self):
        ol = OutputLine("stderr", "warn")
        assert ol.stream == "stderr"


class TestRunRecordLines:
    def _record(self, lines):
        return RunRecord(
            script_id="x",
            script_name="x",
            timestamp="2026-05-04T00:00:00",
            exit_code=0,
            timed_out=False,
            duration=1.0,
            lines=lines,
        )

    def test_default_lines_empty(self):
        r = RunRecord(
            script_id="x",
            script_name="x",
            timestamp="2026-05-04T00:00:00",
            exit_code=0,
            timed_out=False,
            duration=1.0,
        )
        assert r.lines == []

    def test_combined_text_chronological(self):
        r = self._record([
            OutputLine("stdout", "a"),
            OutputLine("stderr", "warn"),
            OutputLine("stdout", "b"),
        ])
        assert r.combined_text() == "a\nwarn\nb"

    def test_stdout_text_filters(self):
        r = self._record([
            OutputLine("stdout", "a"),
            OutputLine("stderr", "warn"),
            OutputLine("stdout", "b"),
        ])
        assert r.stdout_text() == "a\nb"

    def test_combined_text_empty(self):
        r = self._record([])
        assert r.combined_text() == ""

    def test_round_trip_json(self):
        r = self._record([
            OutputLine("stdout", "a"),
            OutputLine("stderr", "b"),
        ])
        dumped = r.model_dump_json()
        restored = RunRecord.model_validate_json(dumped)
        assert restored.lines == r.lines
        assert isinstance(restored.lines[0], OutputLine)
```

- [ ] **Step 2: Run new tests to verify they fail**

Run: `uv run pytest tests/test_models.py::TestOutputLine tests/test_models.py::TestRunRecordLines -v`
Expected: FAIL — `ImportError: cannot import name 'OutputLine'` (then attribute / validation errors).

- [ ] **Step 3: Add `OutputLine` and reshape `RunRecord` in `src/scriptpilot/models.py`**

Replace the import block at the top:

```python
from __future__ import annotations

import uuid
from typing import Literal, NamedTuple

from pydantic import BaseModel, model_validator
```

Add `OutputLine` (place it just before `RunRecord`):

```python
class OutputLine(NamedTuple):
    """One line of subprocess output, tagged with its source stream."""

    stream: Literal["stdout", "stderr"]
    line: str
```

Replace the `RunRecord` class:

```python
class RunRecord(BaseModel):
    """A single script execution record."""

    script_id: str
    script_name: str
    timestamp: str
    exit_code: int
    timed_out: bool
    duration: float
    lines: list[OutputLine] = []

    def combined_text(self) -> str:
        """All lines in chronological order, no stream marker."""
        return "\n".join(line for _, line in self.lines)

    def stdout_text(self) -> str:
        """Stdout-only lines for the JSON viewer's parse attempts."""
        return "\n".join(line for stream, line in self.lines if stream == "stdout")
```

- [ ] **Step 4: Run new tests to verify they pass**

Run: `uv run pytest tests/test_models.py::TestOutputLine tests/test_models.py::TestRunRecordLines -v`
Expected: PASS for all six tests.

- [ ] **Step 5: Migrate `tests/test_history.py` to use `lines=`**

The existing fixtures pass `output=` which no longer exists. Open `tests/test_history.py`.

Replace the `sample_record` fixture:

```python
@pytest.fixture
def sample_record():
    return RunRecord(
        script_id="abc",
        script_name="test script",
        timestamp="2026-04-15T10:30:00",
        exit_code=0,
        timed_out=False,
        duration=1.5,
        lines=[OutputLine("stdout", "hello world")],
    )
```

Add to the imports at the top:

```python
from scriptpilot.models import RunRecord, OutputLine
```

In `test_add_and_list_all`, replace:

```python
        assert records[0].output == "hello world\n"
```

with:

```python
        assert records[0].lines == [OutputLine("stdout", "hello world")]
```

In `test_list_all_newest_first`, replace `output="first\n"` and `output="second\n"` with `lines=[OutputLine("stdout", "first")]` and `lines=[OutputLine("stdout", "second")]`.

In `test_list_for_script`, replace `output="a\n"` and `output="b\n"` with `lines=[OutputLine("stdout", "a")]` and `lines=[OutputLine("stdout", "b")]`.

In `test_persists_to_disk`, replace:

```python
        assert store2.list_all()[0].output == "hello world\n"
```

with:

```python
        assert store2.list_all()[0].lines == [OutputLine("stdout", "hello world")]
```

In `test_evicts_oldest_at_cap`, replace `output=f"run {i}\n"` with `lines=[OutputLine("stdout", f"run {i}")]`.

In `test_creates_parent_directory`, replace `output="x\n"` with `lines=[OutputLine("stdout", "x")]`.

- [ ] **Step 6: Patch `src/scriptpilot/screens/main.py` so the app still imports**

Open `src/scriptpilot/screens/main.py`. The `_execute` method builds a `RunRecord(... output=...)` that no longer validates. To keep imports green between tasks, replace just that constructor with a stub that uses `lines=[]`. Find the `record = RunRecord(...)` block in the `run()` inner function and replace it with:

```python
                from datetime import datetime, timezone
                record = RunRecord(
                    script_id=script.id,
                    script_name=script.name,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    exit_code=result.exit_code,
                    timed_out=result.timed_out,
                    duration=result.duration,
                    lines=[],  # populated in Task 8
                )
```

Also delete the now-unused `output_lines: list[str] = []` and the `def collect_output(line: str)` body's `output_lines.append(line)` line. Replace `collect_output` with the simpler:

```python
            def collect_output(line: str):
                panel.append_output(line)
```

This keeps the existing string-based `panel.append_output` callable; it will be re-typed in Task 7.

- [ ] **Step 7: Run the full test suite to verify nothing else broke**

Run: `uv run pytest -v`
Expected: PASS for all tests except the existing executor tests (those still pass — `on_output=lines.append` with strings continues to work since `append_output` and `execute_script` still pass `str`).

- [ ] **Step 8: Commit**

```bash
git add src/scriptpilot/models.py src/scriptpilot/screens/main.py tests/test_models.py tests/test_history.py
git commit -m "feat: OutputLine NamedTuple; RunRecord stores chronological lines"
```

---

## Task 2: Executor — separate stderr, set `SCRIPTPILOT_OUTPUT_DIR`

**Files:**
- Modify: `src/scriptpilot/executor.py`
- Modify: `tests/test_executor.py`

`execute_script`'s `on_output` callback type changes from `Callable[[str], None]` to `Callable[[OutputLine], None]`. Both stdout and stderr are read concurrently. The `SCRIPTPILOT_OUTPUT_DIR` env var is set (but the dir is not created).

- [ ] **Step 1: Update existing executor tests' callback shape**

The existing tests use `lines = []; on_output=lines.append` with assertions like `any("hello world" in line for line in lines)`. After this task, callbacks receive `OutputLine` tuples — those assertions need to read `.line`. Open `tests/test_executor.py`.

Add to imports:

```python
from scriptpilot.models import OutputLine
```

For each existing test that uses `lines = []` and `on_output=lines.append`, change the assertion pattern from:

```python
assert any("hello world" in line for line in lines)
```

to:

```python
assert any("hello world" in ol.line for ol in lines)
```

Apply this rename to **every** existing test in the file (`test_run_bash_script`, `test_run_python_script`, `test_script_with_args`, `test_script_nonzero_exit`, and any other test that iterates over `lines` looking for substrings). Save and verify by reading the file end-to-end.

- [ ] **Step 2: Add new failing tests for stderr split and env var**

Append to `tests/test_executor.py`:

```python
class TestExecutorStderrSplit:
    @pytest.mark.asyncio
    async def test_stdout_and_stderr_tagged_separately(self, tmp_path):
        script = Script(
            name="split",
            description="emits to both",
            type="bash",
            content='echo out1; echo err1 1>&2; echo out2',
        )
        path = _materialize(script, tmp_path)
        lines: list[OutputLine] = []
        result = await execute_script(script, on_output=lines.append, script_path=path)
        assert result.exit_code == 0
        # All lines come back as OutputLine
        assert all(isinstance(ol, OutputLine) for ol in lines)
        # Streams correctly tagged
        stdout_lines = [ol.line for ol in lines if ol.stream == "stdout"]
        stderr_lines = [ol.line for ol in lines if ol.stream == "stderr"]
        assert "out1" in stdout_lines
        assert "out2" in stdout_lines
        assert "err1" in stderr_lines

    @pytest.mark.asyncio
    async def test_only_stderr_does_not_block(self, tmp_path):
        # If stderr-only output failed to drain the stderr pipe, the script
        # would hang. This test must complete within the asyncio timeout.
        script = Script(
            name="stderr only",
            description="prints to stderr",
            type="bash",
            content='echo only-err 1>&2',
        )
        path = _materialize(script, tmp_path)
        lines: list[OutputLine] = []
        result = await execute_script(script, on_output=lines.append, script_path=path)
        assert result.exit_code == 0
        assert any(ol.stream == "stderr" and "only-err" in ol.line for ol in lines)


class TestExecutorOutputDir:
    @pytest.mark.asyncio
    async def test_env_var_set_and_dir_not_created(self, tmp_path, monkeypatch):
        # Move HOME to tmp_path to keep ~/.scriptpilot/outputs scoped to the test.
        monkeypatch.setenv("HOME", str(tmp_path))
        script = Script(
            name="env probe",
            description="prints SCRIPTPILOT_OUTPUT_DIR",
            type="bash",
            content='echo "$SCRIPTPILOT_OUTPUT_DIR"',
        )
        path = _materialize(script, tmp_path)
        lines: list[OutputLine] = []
        result = await execute_script(script, on_output=lines.append, script_path=path)
        assert result.exit_code == 0
        emitted = next(ol.line for ol in lines if ol.stream == "stdout")
        # Path shape: <home>/.scriptpilot/outputs/<id>/<timestamp>
        expected_prefix = str(tmp_path / ".scriptpilot" / "outputs" / script.id)
        assert emitted.startswith(expected_prefix)
        # Dir must NOT be created by the executor
        assert not Path(emitted).exists()

    @pytest.mark.asyncio
    async def test_per_script_env_overrides(self, tmp_path):
        script = Script(
            name="env override",
            description="checks override",
            type="bash",
            content='echo "$SCRIPTPILOT_OUTPUT_DIR"',
            env={"SCRIPTPILOT_OUTPUT_DIR": "/tmp/custom-output"},
        )
        path = _materialize(script, tmp_path)
        lines: list[OutputLine] = []
        result = await execute_script(script, on_output=lines.append, script_path=path)
        assert result.exit_code == 0
        emitted = next(ol.line for ol in lines if ol.stream == "stdout")
        assert emitted == "/tmp/custom-output"
```

- [ ] **Step 3: Run new tests to verify they fail**

Run: `uv run pytest tests/test_executor.py::TestExecutorStderrSplit tests/test_executor.py::TestExecutorOutputDir -v`
Expected: FAIL — `OutputLine` not in callbacks (still strings); env var not set.

- [ ] **Step 4: Update `src/scriptpilot/executor.py`**

Replace the entire file content with:

```python
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


def _resolve_cwd(script_cwd: str | None) -> Path:
    """Resolve the cwd to use for a script run."""
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

    try:
        await asyncio.wait_for(proc.wait(), timeout=script.timeout)
    except asyncio.TimeoutError:
        timed_out = True
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
        duration=duration,
    )
```

- [ ] **Step 5: Run new and migrated tests to verify they pass**

Run: `uv run pytest tests/test_executor.py -v`
Expected: PASS for all tests (existing migrated tests + new `TestExecutorStderrSplit` + `TestExecutorOutputDir`).

- [ ] **Step 6: Run full suite to verify no regressions**

Run: `uv run pytest -v`
Expected: PASS across the board. `test_main_panel.py` (still missing) and `test_clipboard.py` (still missing) are not yet present.

- [ ] **Step 7: Commit**

```bash
git add src/scriptpilot/executor.py tests/test_executor.py
git commit -m "feat: executor splits stderr and sets SCRIPTPILOT_OUTPUT_DIR"
```

---

## Task 3: Clipboard module + pyproject extra

**Files:**
- Create: `src/scriptpilot/clipboard.py`
- Create: `tests/test_clipboard.py`
- Modify: `pyproject.toml`

Cross-platform clipboard helper. Independent module — no dependency on other tasks.

- [ ] **Step 1: Write failing tests**

Create `tests/test_clipboard.py`:

```python
import sys
from unittest.mock import MagicMock, patch

import pytest

from scriptpilot.clipboard import ClipboardUnavailable, copy


class TestClipboardPyperclip:
    def test_uses_pyperclip_when_importable(self):
        fake_pyperclip = MagicMock()
        with patch.dict(sys.modules, {"pyperclip": fake_pyperclip}):
            copy("hello")
        fake_pyperclip.copy.assert_called_once_with("hello")

    def test_falls_through_when_pyperclip_raises(self):
        fake_pyperclip = MagicMock()
        fake_pyperclip.copy.side_effect = RuntimeError("boom")
        with patch.dict(sys.modules, {"pyperclip": fake_pyperclip}):
            with patch("scriptpilot.clipboard.shutil.which", return_value="/usr/bin/wl-copy"):
                with patch("scriptpilot.clipboard.subprocess.run") as run:
                    run.return_value = None
                    copy("hello")
                    run.assert_called_once()
                    assert run.call_args.args[0][0] == "wl-copy"


class TestClipboardShellLinux:
    @pytest.fixture(autouse=True)
    def _no_pyperclip(self):
        # Make pyperclip unimportable for these tests.
        with patch.dict(sys.modules, {"pyperclip": None}):
            yield

    @pytest.fixture(autouse=True)
    def _platform_linux(self):
        with patch("scriptpilot.clipboard.sys.platform", "linux"):
            yield

    def test_prefers_wl_copy_on_linux(self):
        def which(cmd):
            return "/usr/bin/wl-copy" if cmd == "wl-copy" else None

        with patch("scriptpilot.clipboard.shutil.which", side_effect=which):
            with patch("scriptpilot.clipboard.subprocess.run") as run:
                copy("text")
                assert run.call_args.args[0] == ["wl-copy"]
                assert run.call_args.kwargs["input"] == b"text"

    def test_falls_back_to_xclip(self):
        def which(cmd):
            return "/usr/bin/xclip" if cmd == "xclip" else None

        with patch("scriptpilot.clipboard.shutil.which", side_effect=which):
            with patch("scriptpilot.clipboard.subprocess.run") as run:
                copy("text")
                assert run.call_args.args[0] == ["xclip", "-selection", "clipboard"]

    def test_raises_when_no_backend(self):
        with patch("scriptpilot.clipboard.shutil.which", return_value=None):
            with pytest.raises(ClipboardUnavailable):
                copy("text")

    def test_falls_through_failed_backend(self):
        import subprocess
        # wl-copy and xclip both present; wl-copy fails, xclip succeeds.
        def which(cmd):
            return f"/usr/bin/{cmd}" if cmd in ("wl-copy", "xclip") else None

        run_calls = []

        def fake_run(cmd, **kwargs):
            run_calls.append(cmd)
            if cmd[0] == "wl-copy":
                raise subprocess.CalledProcessError(1, cmd)
            return None

        with patch("scriptpilot.clipboard.shutil.which", side_effect=which):
            with patch("scriptpilot.clipboard.subprocess.run", side_effect=fake_run):
                copy("text")
        assert run_calls[0][0] == "wl-copy"
        assert run_calls[1][0] == "xclip"


class TestClipboardShellMacos:
    @pytest.fixture(autouse=True)
    def _no_pyperclip(self):
        with patch.dict(sys.modules, {"pyperclip": None}):
            yield

    @pytest.fixture(autouse=True)
    def _platform_darwin(self):
        with patch("scriptpilot.clipboard.sys.platform", "darwin"):
            yield

    def test_uses_pbcopy_on_macos(self):
        def which(cmd):
            return "/usr/bin/pbcopy" if cmd == "pbcopy" else None

        with patch("scriptpilot.clipboard.shutil.which", side_effect=which):
            with patch("scriptpilot.clipboard.subprocess.run") as run:
                copy("text")
                assert run.call_args.args[0] == ["pbcopy"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_clipboard.py -v`
Expected: FAIL — `ImportError: No module named 'scriptpilot.clipboard'`.

- [ ] **Step 3: Create `src/scriptpilot/clipboard.py`**

```python
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
        # pyperclip raises pyperclip.PyperclipException on misconfigured env;
        # fall through to shell backends.
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_clipboard.py -v`
Expected: PASS for all 8 tests.

- [ ] **Step 5: Add `pyperclip` optional extra to `pyproject.toml`**

Open `pyproject.toml`. After the `dependencies = [...]` block (and before `[project.scripts]`), insert:

```toml
[project.optional-dependencies]
clipboard = ["pyperclip>=1.8"]
```

The final `[project]` section will look like (showing just the relevant ordering):

```toml
[project]
name = "scriptpilot"
version = "0.1.0"
description = "TUI for managing and executing automation scripts with AI generation"
requires-python = ">=3.10"
dependencies = [
    "textual>=0.80",
    "httpx>=0.27",
    "pydantic>=2.0",
]

[project.optional-dependencies]
clipboard = ["pyperclip>=1.8"]

[project.scripts]
scriptpilot = "scriptpilot.app:main"
```

- [ ] **Step 6: Run full test suite to confirm no regressions**

Run: `uv run pytest -v`
Expected: PASS for all tests so far.

- [ ] **Step 7: Commit**

```bash
git add src/scriptpilot/clipboard.py tests/test_clipboard.py pyproject.toml
git commit -m "feat: clipboard module with pyperclip/wl-copy/xclip/pbcopy fallback"
```

---

## Task 4: JSON parse helpers + tests

**Files:**
- Modify: `src/scriptpilot/widgets/main_panel.py`
- Create: `tests/test_main_panel.py`

Pure helper functions live at module level so they can be unit-tested without instantiating Textual.

- [ ] **Step 1: Write failing tests**

Create `tests/test_main_panel.py`:

```python
from scriptpilot.widgets.main_panel import (
    _last_nonempty_line,
    _safe_name,
    _try_parse_json,
)


class TestTryParseJson:
    def test_single_line_object(self):
        assert _try_parse_json('{"x": 1}') == {"x": 1}

    def test_single_line_array(self):
        assert _try_parse_json("[1, 2, 3]") == [1, 2, 3]

    def test_multi_line_pretty_printed(self):
        assert _try_parse_json('{\n  "x": 1,\n  "y": 2\n}') == {"x": 1, "y": 2}

    def test_status_line_then_json(self):
        assert _try_parse_json('fetching...\n{"ok": true}') == {"ok": True}

    def test_not_json(self):
        assert _try_parse_json("hello world") is None

    def test_empty(self):
        assert _try_parse_json("") is None

    def test_whitespace_only(self):
        assert _try_parse_json("   \n  ") is None


class TestLastNonemptyLine:
    def test_strips_trailing_blanks(self):
        assert _last_nonempty_line("a\n\n") == "a"

    def test_no_lines(self):
        assert _last_nonempty_line("") == ""

    def test_only_blanks(self):
        assert _last_nonempty_line("\n\n  \n") == ""

    def test_single_line_no_newline(self):
        assert _last_nonempty_line("only") == "only"


class TestSafeName:
    def test_strips_unsafe_chars(self):
        assert _safe_name("My Script!!") == "My-Script"

    def test_keeps_safe_chars(self):
        assert _safe_name("foo_bar.baz-1") == "foo_bar.baz-1"

    def test_empty_returns_default(self):
        assert _safe_name("") == "output"

    def test_all_unsafe_returns_default(self):
        assert _safe_name("!!!") == "output"

    def test_collapses_runs(self):
        assert _safe_name("a   b") == "a-b"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_main_panel.py -v`
Expected: FAIL — `ImportError: cannot import name '_try_parse_json'`.

- [ ] **Step 3: Add helpers to `src/scriptpilot/widgets/main_panel.py`**

Open the file. Add these imports to the top of the file (next to existing imports):

```python
import json
import re
```

Add these module-level functions just below the `from scriptpilot.models import ...` line and above `class MainPanel`:

```python
def _try_parse_json(stdout: str) -> object | None:
    """Try to parse stdout as JSON.

    First attempt: the whole string (handles pretty-printed multi-line).
    Second attempt: the last non-empty line (handles status-line-then-JSON).
    Returns the parsed value or None.
    """
    if not stdout.strip():
        return None
    candidates = [stdout]
    last = _last_nonempty_line(stdout)
    if last and last != stdout:
        candidates.append(last)
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _last_nonempty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line
    return ""


def _safe_name(name: str) -> str:
    """Filesystem-safe filename stem; falls back to 'output' if empty."""
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip("-")
    return cleaned or "output"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_main_panel.py -v`
Expected: PASS for all 14 tests.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/widgets/main_panel.py tests/test_main_panel.py
git commit -m "feat: pure JSON parse and filename helpers in main_panel"
```

---

## Task 5: `SavePromptScreen` modal

**Files:**
- Create: `src/scriptpilot/screens/save_prompt.py`

A simple modal: pre-fills a default path, returns `Path | None` on dismiss. Existing screens in the codebase have no test files — follow that convention; behavior is exercised in the manual acceptance walkthrough.

- [ ] **Step 1: Create `src/scriptpilot/screens/save_prompt.py`**

```python
from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


class SavePromptScreen(ModalScreen[Path | None]):
    """Prompt for a save path. Returns Path on submit, None on cancel."""

    DEFAULT_CSS = """
    SavePromptScreen {
        align: center middle;
    }
    SavePromptScreen #save-container {
        width: 80;
        height: auto;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    SavePromptScreen #save-buttons {
        height: 3;
        align: right middle;
        margin-top: 1;
    }
    SavePromptScreen #save-buttons Button {
        margin-left: 1;
    }
    """

    def __init__(self, default_path: Path):
        super().__init__()
        self._default = default_path

    def compose(self) -> ComposeResult:
        with Vertical(id="save-container"):
            yield Label("[bold]Save output to:[/bold]")
            yield Input(value=str(self._default), id="save-path")
            with Horizontal(id="save-buttons"):
                yield Button("Cancel", id="cancel-btn")
                yield Button("Save", id="save-btn", variant="success")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "save-btn":
            self._submit()

    def on_input_submitted(self, event: Input.Submitted):
        # Enter key in the input also submits.
        self._submit()

    def _submit(self):
        raw = self.query_one("#save-path", Input).value.strip()
        if not raw:
            self.notify("Path is required", severity="error")
            return
        self.dismiss(Path(raw).expanduser())
```

- [ ] **Step 2: Smoke-test the import**

Run: `uv run python -c "from scriptpilot.screens.save_prompt import SavePromptScreen; print('ok')"`
Expected: prints `ok` with no errors.

- [ ] **Step 3: Run full test suite to confirm no regressions**

Run: `uv run pytest -v`
Expected: PASS for all existing tests.

- [ ] **Step 4: Commit**

```bash
git add src/scriptpilot/screens/save_prompt.py
git commit -m "feat: SavePromptScreen modal for output save path"
```

---

## Task 6: `JsonViewScreen` modal

**Files:**
- Create: `src/scriptpilot/screens/json_view.py`

Renders parsed JSON via `rich.json.JSON`. Closes on `escape` or `q`.

- [ ] **Step 1: Create `src/scriptpilot/screens/json_view.py`**

```python
from __future__ import annotations

from rich.json import JSON

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Static


class JsonViewScreen(ModalScreen[None]):
    """Display parsed JSON via rich.json.JSON."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
    ]

    DEFAULT_CSS = """
    JsonViewScreen {
        align: center middle;
    }
    JsonViewScreen #jv-container {
        width: 80%;
        max-width: 120;
        height: 80%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    JsonViewScreen #jv-content {
        height: 1fr;
    }
    """

    def __init__(self, parsed: object):
        super().__init__()
        self._parsed = parsed

    def compose(self) -> ComposeResult:
        with Vertical(id="jv-container"):
            yield Label("[bold]JSON output[/bold] ([dim]q to close[/dim])")
            yield Static(JSON.from_data(self._parsed), id="jv-content")

    def action_close(self):
        self.dismiss(None)
```

- [ ] **Step 2: Smoke-test the import**

Run: `uv run python -c "from scriptpilot.screens.json_view import JsonViewScreen; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Run full test suite to confirm no regressions**

Run: `uv run pytest -v`
Expected: PASS for all existing tests.

- [ ] **Step 4: Commit**

```bash
git add src/scriptpilot/screens/json_view.py
git commit -m "feat: JsonViewScreen modal for rich JSON rendering"
```

---

## Task 7: MainPanel — bindings, stderr styling, run-state, action wiring

**Files:**
- Modify: `src/scriptpilot/widgets/main_panel.py`

Add three bindings (`o`/`y`/`J`), style stderr lines red, track the currently-displayed run, expose a new `show_finished_run(run: RunRecord)` method, and re-type `append_output` to take an `OutputLine`.

- [ ] **Step 1: Replace the entire content of `src/scriptpilot/widgets/main_panel.py`**

Open the file. The new full content is below — note that the helper functions (`_try_parse_json`, `_last_nonempty_line`, `_safe_name`) added in Task 4 are preserved verbatim.

```python
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from rich.markup import escape
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label, RichLog, Static

from scriptpilot import clipboard
from scriptpilot.clipboard import ClipboardUnavailable
from scriptpilot.models import OutputLine, RunRecord, Script
from scriptpilot.screens.json_view import JsonViewScreen
from scriptpilot.screens.save_prompt import SavePromptScreen


def _try_parse_json(stdout: str) -> object | None:
    """Try to parse stdout as JSON.

    First attempt: the whole string (handles pretty-printed multi-line).
    Second attempt: the last non-empty line (handles status-line-then-JSON).
    Returns the parsed value or None.
    """
    if not stdout.strip():
        return None
    candidates = [stdout]
    last = _last_nonempty_line(stdout)
    if last and last != stdout:
        candidates.append(last)
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _last_nonempty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line
    return ""


def _safe_name(name: str) -> str:
    """Filesystem-safe filename stem; falls back to 'output' if empty."""
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip("-")
    return cleaned or "output"


def _ts_filename() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")


class MainPanel(Widget):
    """Right panel showing script details or execution output."""

    BINDINGS = [
        ("o", "save_output", "Save"),
        ("y", "copy_output", "Copy"),
        ("J", "view_json", "JSON"),
    ]

    DEFAULT_CSS = """
    MainPanel {
        height: 1fr;
        padding: 1 2;
    }
    MainPanel #welcome {
        content-align: center middle;
        height: 1fr;
    }
    MainPanel #details {
        height: auto;
    }
    MainPanel #output-log {
        height: 1fr;
        border: solid $primary;
        margin-top: 1;
    }
    MainPanel #status-bar {
        height: 1;
        dock: bottom;
    }
    """

    def __init__(self):
        super().__init__()
        self._displayed_run: RunRecord | None = None
        self._is_running: bool = False

    def compose(self) -> ComposeResult:
        yield Label(
            "No scripts yet. Press \\[n] to create one or \\[g] to generate with AI.",
            id="welcome",
        )
        yield Static(id="details")
        yield RichLog(id="output-log", max_lines=10000, wrap=True, markup=True)
        yield Static(id="status-bar")

    def on_mount(self):
        self._show_welcome()

    def _show_welcome(self):
        self.query_one("#welcome").display = True
        self.query_one("#details").display = False
        self.query_one("#output-log").display = False
        self.query_one("#status-bar").display = False

    def show_script_details(self, script: Script, last_run: RunRecord | None = None):
        """Display script metadata (header). Called on selection."""
        self.query_one("#welcome").display = False
        # Hide output and status until show_finished_run / show_running is called.
        self.query_one("#output-log").display = False
        self.query_one("#status-bar").display = False
        self._displayed_run = None
        self._is_running = False

        details = self.query_one("#details", Static)
        args_text = ", ".join(a.name for a in script.args) if script.args else "none"
        text = (
            f"[bold]{script.name}[/bold]\n"
            f"{script.description}\n\n"
            f"Type: {script.type}  |  Timeout: {script.timeout}s  |  Args: {args_text}"
        )
        if last_run:
            text += (
                f"\n\n[dim]Last run: {last_run.timestamp}  |  "
                f"Exit: {last_run.exit_code}  |  "
                f"Duration: {last_run.duration:.1f}s[/dim]"
            )
        details.update(text)
        details.display = True

    def show_running(self, script: Script):
        """Switch to live execution output mode."""
        self.query_one("#welcome").display = False
        details = self.query_one("#details", Static)
        details.update(f"[bold]Running:[/bold] {script.name}")
        details.display = True

        log = self.query_one("#output-log", RichLog)
        log.clear()
        log.display = True

        status = self.query_one("#status-bar", Static)
        status.update("[yellow]Running...[/yellow]")
        status.display = True

        self._displayed_run = None
        self._is_running = True

    def append_output(self, line: OutputLine):
        """Add a single line to the output log, styled by stream."""
        log = self.query_one("#output-log", RichLog)
        text = escape(line.line)
        if line.stream == "stderr":
            log.write(f"[red]{text}[/red]")
        else:
            log.write(text)

    def show_finished_run(self, run: RunRecord):
        """Render a finished run (just-finished or selected from history)."""
        self.query_one("#welcome").display = False
        self._displayed_run = run
        self._is_running = False

        log = self.query_one("#output-log", RichLog)
        log.clear()
        for line in run.lines:
            self.append_output(line)
        log.display = True

        status = self.query_one("#status-bar", Static)
        if run.timed_out:
            status.update(f"[red]Timed out after {run.duration:.1f}s[/red]")
        elif run.exit_code == 0:
            status.update(
                f"[green]Exit code: {run.exit_code}[/green]  "
                f"Duration: {run.duration:.1f}s"
            )
        else:
            status.update(
                f"[red]Exit code: {run.exit_code}[/red]  "
                f"Duration: {run.duration:.1f}s"
            )
        status.display = True

    def show_finished(self, exit_code: int, duration: float, timed_out: bool):
        """Update status bar after a live run completes (legacy entry-point)."""
        status = self.query_one("#status-bar", Static)
        if timed_out:
            status.update(f"[red]Timed out after {duration:.1f}s[/red]")
        elif exit_code == 0:
            status.update(
                f"[green]Exit code: {exit_code}[/green]  Duration: {duration:.1f}s"
            )
        else:
            status.update(
                f"[red]Exit code: {exit_code}[/red]  Duration: {duration:.1f}s"
            )

    def show_error(self, message: str):
        """Show an error in the output area."""
        self.query_one("#welcome").display = False
        details = self.query_one("#details", Static)
        details.update(f"[red]{message}[/red]")
        details.display = True

    # -------- bindings --------

    def action_save_output(self):
        if self._displayed_run is None or self._is_running:
            return
        run = self._displayed_run
        default_path = (
            Path.home() / ".scriptpilot" / "outputs"
            / f"{_safe_name(run.script_name)}-{_ts_filename()}.txt"
        )

        def on_path(path: Path | None):
            if path is None:
                return
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(run.combined_text())
            except OSError as e:
                self.notify(str(e), severity="error")
                return
            self.notify(f"Saved to {path}")

        self.app.push_screen(SavePromptScreen(default_path), callback=on_path)

    def action_copy_output(self):
        if self._displayed_run is None or self._is_running:
            return
        try:
            clipboard.copy(self._displayed_run.combined_text())
            self.notify("Copied")
        except ClipboardUnavailable as e:
            self.notify(str(e), severity="warning")

    def action_view_json(self):
        if self._displayed_run is None or self._is_running:
            return
        text = self._displayed_run.stdout_text().strip()
        if not text:
            self.notify("No stdout to parse", severity="warning")
            return
        parsed = _try_parse_json(text)
        if parsed is None:
            self.notify("Output is not JSON", severity="warning")
            return
        self.app.push_screen(JsonViewScreen(parsed))
```

Notes:
- `RichLog(... markup=True)` is critical — without it, the `[red]...[/red]` / `[bold]...[/bold]` markup we write won't be interpreted. The original `RichLog` had `markup` defaulting to off; this enables it. Because we `escape()` user content before applying our own markup, this is safe against script-output markup injection.
- `show_finished` is kept (legacy entry-point) so any other caller doesn't break, but `show_finished_run` is the preferred new entry-point that also captures the displayed run.

- [ ] **Step 2: Run helper tests to confirm they still pass**

Run: `uv run pytest tests/test_main_panel.py -v`
Expected: PASS for all 14 helper tests (helpers were preserved verbatim).

- [ ] **Step 3: Run full test suite to confirm no regressions**

Run: `uv run pytest -v`
Expected: PASS for everything so far.

- [ ] **Step 4: Smoke-test the imports**

Run: `uv run python -c "from scriptpilot.widgets.main_panel import MainPanel; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/widgets/main_panel.py
git commit -m "feat: MainPanel bindings (o/y/J), stderr styling, run-state tracking"
```

---

## Task 8: MainScreen integration — collect `OutputLine`s, build `RunRecord`, auto-show last run

**Files:**
- Modify: `src/scriptpilot/screens/main.py`

Three changes: (1) `_execute` collects `OutputLine` events into a list and uses them for both `panel.append_output(line)` and `RunRecord(lines=...)`; (2) on completion, call `panel.show_finished_run(record)` so the just-finished run is the displayed run; (3) `on_script_selected` calls `panel.show_finished_run(last_run)` if there's a prior run.

- [ ] **Step 1: Update `on_script_selected` in `src/scriptpilot/screens/main.py`**

Find the existing method:

```python
    def on_script_selected(self, event: ScriptSelected):
        self._selected_script = event.script
        last_run = self._get_last_run(event.script.id)
        self.query_one(MainPanel).show_script_details(event.script, last_run)
```

Replace it with:

```python
    def on_script_selected(self, event: ScriptSelected):
        self._selected_script = event.script
        last_run = self._get_last_run(event.script.id)
        panel = self.query_one(MainPanel)
        panel.show_script_details(event.script, last_run)
        if last_run:
            panel.show_finished_run(last_run)
```

- [ ] **Step 2: Update `_execute` to collect `OutputLine`s and call `show_finished_run`**

Find the existing method (the `def run()` inner function inside `_execute`):

```python
        async def run():
            output_lines: list[str] = []  # may have been removed in Task 1; either way replace this whole block

            def collect_output(line: str):
                panel.append_output(line)

            try:
                result = await execute_script(
                    script,
                    arg_values=arg_values,
                    on_output=collect_output,
                    script_path=self._store.path_for(script.id),
                    python_command=self.app._config.python_command,
                )
                panel.show_finished(result.exit_code, result.duration, result.timed_out)

                from datetime import datetime, timezone
                record = RunRecord(
                    script_id=script.id,
                    script_name=script.name,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    exit_code=result.exit_code,
                    timed_out=result.timed_out,
                    duration=result.duration,
                    lines=[],  # populated in Task 8
                )
                self._history.add(record)
            except (InterpreterNotFoundError, ScriptCwdError) as e:
                panel.show_error(str(e))
                self.notify(str(e), severity="error")
            except Exception as e:
                panel.show_error(f"Error: {e}")
                self.notify(str(e), severity="error")
```

Replace the `async def run():` block with:

```python
        async def run():
            collected: list[OutputLine] = []

            def collect_output(line: OutputLine):
                collected.append(line)
                panel.append_output(line)

            try:
                result = await execute_script(
                    script,
                    arg_values=arg_values,
                    on_output=collect_output,
                    script_path=self._store.path_for(script.id),
                    python_command=self.app._config.python_command,
                )

                from datetime import datetime, timezone
                record = RunRecord(
                    script_id=script.id,
                    script_name=script.name,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    exit_code=result.exit_code,
                    timed_out=result.timed_out,
                    duration=result.duration,
                    lines=collected,
                )
                self._history.add(record)
                panel.show_finished_run(record)
            except (InterpreterNotFoundError, ScriptCwdError) as e:
                panel.show_error(str(e))
                self.notify(str(e), severity="error")
            except Exception as e:
                panel.show_error(f"Error: {e}")
                self.notify(str(e), severity="error")
```

Note: `panel.show_finished(result.exit_code, ...)` is replaced by `panel.show_finished_run(record)` since the latter handles status bar AND captures the displayed run for bindings.

- [ ] **Step 3: Add `OutputLine` to imports**

At the top of `src/scriptpilot/screens/main.py`, find:

```python
from scriptpilot.models import Script, ScriptArg, RunRecord
```

Replace with:

```python
from scriptpilot.models import OutputLine, RunRecord, Script, ScriptArg
```

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest -v`
Expected: PASS for everything.

- [ ] **Step 5: Smoke-test the app boot**

Run: `uv run python -c "from scriptpilot.app import ScriptPilotApp; ScriptPilotApp(); print('ok')"`
Expected: prints `ok`. (Just instantiates; does not call `.run()`.)

- [ ] **Step 6: Commit**

```bash
git add src/scriptpilot/screens/main.py
git commit -m "feat: MainScreen builds RunRecord with lines and auto-shows last run"
```

---

## Manual acceptance walkthrough

After Task 8, run the app and verify:

```bash
cd /home/kc/repos/script-pilot
uv run scriptpilot
```

Each item below corresponds to an acceptance criterion in the spec. Walk through them in order.

1. **JSON viewer.** Create a bash script with content `echo '{"ok": true, "rows": 42}'`. Run it (`r`). After it finishes, press `J` → modal opens with rendered JSON; `q` closes it.

2. **Copy.** Same run, press `y` → notify "Copied". Paste in another app — content matches the displayed output line.

3. **Save.** Press `o` → modal pre-fills `~/.scriptpilot/outputs/<safe-name>-<ts>.txt`. Press Save → notify "Saved to ...". Verify the file exists and contains the combined output.

4. **Stderr styling + chronology.** Create a bash script: `echo hi; echo oops 1>&2; echo bye`. Run it. Lines appear in arrival order; the `oops` line is red, others plain.

5. **`SCRIPTPILOT_OUTPUT_DIR` default.** Create a bash script: `echo "$SCRIPTPILOT_OUTPUT_DIR"`. Run it. Output should be `~/.scriptpilot/outputs/<script-id>/<utc-timestamp>`. The directory does NOT exist on disk.

6. **Per-script env override.** Edit the script, add env entry `SCRIPTPILOT_OUTPUT_DIR=/tmp/custom`, save. Run again. Output is `/tmp/custom`.

7. **Auto-show last run.** Create a second script and run it. Click the first script → its last-run output reappears in the panel. Press `y` → copies *that* script's last output, not the second one.

8. **Live-run inertness.** Create a long-running bash script: `sleep 5; echo done`. Run it; while it is running, press `y` / `o` / `J`. None should fire.

9. **No clipboard backend.** Temporarily install neither pyperclip nor any of `wl-copy`/`xclip`/`pbcopy` (or test on a machine that has none). Press `y` → notify with install hint.

10. **Markup escape.** Create a bash script: `echo '[bold]hi[/bold]'`. Run it. Output displays the literal text (including the brackets), not bolded.

11. **JSON parse fallback.** Create a bash script: `echo fetching...; echo '{"x": 1}'`. Run it. Press `J` → modal opens with `{"x": 1}` (last-line fallback worked).

12. **Multi-line JSON.** Create a python script: `import json; print(json.dumps({"x": 1, "y": [2,3]}, indent=2))`. Run it. Press `J` → modal opens with the parsed structure.

If any of the above fails, the failure indicates a bug in the relevant task — go back to that task's tests, add a regression test, fix, and re-verify.

---

## Self-Review Checklist

**Spec coverage:**
- ✅ §3 Save/copy bindings → Task 7 (action_save_output, action_copy_output) + Task 5 (SavePromptScreen)
- ✅ §3 Stderr separation + red styling → Task 2 (executor) + Task 7 (append_output styling)
- ✅ §3 JSON viewer → Task 4 (parse helpers) + Task 6 (modal) + Task 7 (action_view_json)
- ✅ §3 SCRIPTPILOT_OUTPUT_DIR → Task 2
- ✅ §3 Auto-show last run → Task 8 (on_script_selected)
- ✅ §3 RunRecord.lines → Task 1
- ✅ §3 OutputLine NamedTuple → Task 1
- ✅ Clipboard module → Task 3
- ✅ pyperclip optional extra → Task 3
- ✅ Live-run inertness → Task 7 (`_is_running` guards)
- ✅ Markup injection escape → Task 7 (`rich.markup.escape`)
- ✅ Per-script env override → Task 2 (covered by `_execute` env spread order; tested in TestExecutorOutputDir)

**Type consistency:**
- `OutputLine(stream, line)` named tuple is consistent across models, executor, MainPanel, MainScreen.
- `on_output: Callable[[OutputLine], None]` consistent in executor signature and call sites.
- `RunRecord.lines: list[OutputLine]` consistent across creation, persistence, helpers.
- `_displayed_run` is `RunRecord | None`, set in `show_finished_run`, cleared in `show_running` and `show_script_details`.

**No placeholders:** Each step contains complete code. No "similar to Task N" / "TBD" / "implement later".
