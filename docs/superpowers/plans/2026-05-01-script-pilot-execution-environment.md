# ScriptPilot — Execution Environment & Reproducibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make scripts reproducible — give each script its own working directory, support PEP 723 Python deps via `uv run --script`, and merge per-script env vars with a global secrets file.

**Architecture:** Three small additive features on the existing module layout. New `secrets.py` module for the dotenv parser. New `EnvEditor` widget mirroring `ArgEditor`. Executor gains `_resolve_command` (multi-token interpreter), `_resolve_cwd` (with new `ScriptCwdError`), and env merging. Pydantic defaults on every new field — existing on-disk meta JSON loads without migration.

**Tech Stack:** Python 3.10+, Textual, Pydantic v2, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-05-01-script-pilot-execution-environment-design.md`

---

## File Map

| File | Responsibility | Change |
|------|---------------|--------|
| `src/scriptpilot/models.py` | Pydantic models | Add `Script.cwd`, `Script.env`, `AppConfig.python_command` |
| `src/scriptpilot/secrets.py` | Dotenv parser | **NEW** — `SECRETS_PATH`, `load_secrets()` |
| `src/scriptpilot/executor.py` | Subprocess execution | Replace `_get_interpreter` → `_resolve_command`; add `_resolve_cwd`, `ScriptCwdError`; merge env; `python_command` kwarg |
| `src/scriptpilot/widgets/env_editor.py` | Env-var editor widget | **NEW** — `EnvRow`, `EnvEditor` |
| `src/scriptpilot/screens/edit.py` | Script edit modal | Add `cwd` Input + mount `EnvEditor`; collect on save |
| `src/scriptpilot/screens/settings.py` | Settings modal | Add `python_command` Input + secrets status label |
| `src/scriptpilot/screens/main.py` | Main screen | Pass `python_command`, catch `ScriptCwdError`, copy `cwd`/`env` on clone |
| `tests/test_models.py` | Model tests | Add `cwd` / `env` / `python_command` cases |
| `tests/test_secrets.py` | Secrets parser tests | **NEW** |
| `tests/test_executor.py` | Executor tests | Add cwd / env / `python_command` tests; update existing python tests to pass `python_command="python3"` |
| `README.md` | Docs | One paragraph on cwd, env, secrets file, python_command |

---

### Task 1: Data Model — `Script.cwd`, `Script.env`, `AppConfig.python_command`

**Files:**
- Modify: `src/scriptpilot/models.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_models.py`:

```python
class TestScriptCwdEnv:
    def test_cwd_default_none(self):
        s = Script(name="x", description="x", type="bash", content="x")
        assert s.cwd is None

    def test_cwd_set(self):
        s = Script(name="x", description="x", type="bash", content="x", cwd="~/work")
        assert s.cwd == "~/work"

    def test_env_default_empty(self):
        s = Script(name="x", description="x", type="bash", content="x")
        assert s.env == {}

    def test_env_set(self):
        s = Script(
            name="x", description="x", type="bash", content="x",
            env={"FOO": "bar", "BAZ": "qux"},
        )
        assert s.env == {"FOO": "bar", "BAZ": "qux"}

    def test_roundtrip_with_cwd_and_env(self):
        s = Script(
            name="x", description="x", type="bash", content="x",
            cwd="/tmp", env={"K": "V"},
        )
        data = s.model_dump()
        s2 = Script(**data)
        assert s2.cwd == "/tmp"
        assert s2.env == {"K": "V"}

    def test_backward_compat_no_cwd_no_env(self):
        """Existing meta files without cwd/env load with defaults."""
        data = {
            "name": "x", "description": "x", "type": "bash",
            "content": "x", "id": "abc",
        }
        s = Script(**data)
        assert s.cwd is None
        assert s.env == {}


class TestAppConfigPythonCommand:
    def test_python_command_default(self):
        config = AppConfig()
        assert config.python_command == "uv run --script"

    def test_python_command_custom(self):
        config = AppConfig(python_command="python3")
        assert config.python_command == "python3"

    def test_backward_compat_no_python_command(self):
        config = AppConfig(**{"default_model": "openai/gpt-4o"})
        assert config.python_command == "uv run --script"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL — `cwd`/`env` not defined on `Script`; `python_command` not on `AppConfig`.

- [ ] **Step 3: Add the fields**

In `src/scriptpilot/models.py`, modify the `Script` and `AppConfig` classes:

```python
class Script(BaseModel):
    """A saved automation script."""

    id: str = ""
    name: str
    description: str
    type: Literal["bash", "python", "js"]
    content: str
    args: list[ScriptArg] = []
    timeout: int = 60
    favorite: bool = False
    cwd: str | None = None
    env: dict[str, str] = {}

    def model_post_init(self, __context):
        if not self.id:
            self.id = str(uuid.uuid4())


class AppConfig(BaseModel):
    """Application configuration."""

    default_model: str = "openai/gpt-4o"
    python_command: str = "uv run --script"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS — all model tests, including the new `TestScriptCwdEnv` and `TestAppConfigPythonCommand`.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/models.py tests/test_models.py
git commit -m "feat: add Script.cwd, Script.env, AppConfig.python_command"
```

---

### Task 2: Secrets Module — Dotenv Parser

**Files:**
- Create: `src/scriptpilot/secrets.py`
- Create: `tests/test_secrets.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_secrets.py`:

```python
from pathlib import Path

import pytest

from scriptpilot.secrets import load_secrets, SECRETS_PATH


class TestSecretsPath:
    def test_default_path(self):
        assert SECRETS_PATH == Path.home() / ".scriptpilot" / ".env"


class TestLoadSecrets:
    def test_missing_file_returns_empty(self, tmp_path):
        assert load_secrets(tmp_path / "nope.env") == {}

    def test_empty_file_returns_empty(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text("")
        assert load_secrets(p) == {}

    def test_simple_key_value(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text("KEY=value\n")
        assert load_secrets(p) == {"KEY": "value"}

    def test_whitespace_around_equals(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text("KEY = value with spaces\n")
        assert load_secrets(p) == {"KEY": "value with spaces"}

    def test_comments_and_blank_lines_ignored(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text("# comment\n\nKEY=v\n# another\n")
        assert load_secrets(p) == {"KEY": "v"}

    def test_double_quoted_value_strips_quotes(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text('KEY="hello world"\n')
        assert load_secrets(p) == {"KEY": "hello world"}

    def test_single_quoted_value_strips_quotes(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text("KEY='hello world'\n")
        assert load_secrets(p) == {"KEY": "hello world"}

    def test_mismatched_quotes_left_alone(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text("KEY=\"hello'\n")
        assert load_secrets(p) == {"KEY": "\"hello'"}

    def test_malformed_line_skipped(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text("noequals\nKEY=v\n")
        assert load_secrets(p) == {"KEY": "v"}

    def test_empty_key_skipped(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text("=novalue\nKEY=v\n")
        assert load_secrets(p) == {"KEY": "v"}

    def test_duplicate_keys_last_wins(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text("K=first\nK=second\n")
        assert load_secrets(p) == {"K": "second"}

    def test_unreadable_file_returns_empty(self, tmp_path):
        p = tmp_path / ".env"
        p.write_text("K=v\n")
        p.chmod(0o000)
        try:
            assert load_secrets(p) == {}
        finally:
            p.chmod(0o644)  # so pytest can clean it up

    def test_value_with_equals_sign(self, tmp_path):
        """A=B=C should parse as A=`B=C` (only first `=` is the separator)."""
        p = tmp_path / ".env"
        p.write_text("A=B=C\n")
        assert load_secrets(p) == {"A": "B=C"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_secrets.py -v`
Expected: FAIL — `scriptpilot.secrets` does not exist.

- [ ] **Step 3: Implement the secrets module**

Create `src/scriptpilot/secrets.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_secrets.py -v`
Expected: PASS — all 13 tests.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/secrets.py tests/test_secrets.py
git commit -m "feat: add secrets module with tiny dotenv parser"
```

---

### Task 3: Executor — Multi-Token Interpreter Command

**Files:**
- Modify: `src/scriptpilot/executor.py`
- Modify: `tests/test_executor.py`

This task replaces `_get_interpreter` with `_resolve_command` so the Python interpreter can be a multi-token command like `"uv run --script"`. Bash and JS stay single-token. `execute_script` gains a `python_command` keyword arg.

- [ ] **Step 1: Add failing tests**

Append to `tests/test_executor.py`:

```python
class TestResolveCommand:
    def test_bash_unchanged(self):
        from scriptpilot.executor import _resolve_command
        cmd = _resolve_command("bash", "uv run --script")
        assert cmd[0].endswith("/bash") or cmd[0] == "bash"
        assert len(cmd) == 1

    def test_python_single_token(self):
        from scriptpilot.executor import _resolve_command
        cmd = _resolve_command("python", "python3")
        assert len(cmd) == 1
        assert cmd[0].endswith("/python3") or cmd[0] == "python3"

    def test_python_multi_token_splits(self, monkeypatch):
        import shutil
        from scriptpilot.executor import _resolve_command
        # Pretend `uv` is on PATH at /usr/bin/uv.
        monkeypatch.setattr(shutil, "which", lambda c: f"/usr/bin/{c}" if c == "uv" else None)
        cmd = _resolve_command("python", "uv run --script")
        assert cmd == ["/usr/bin/uv", "run", "--script"]

    def test_python_empty_falls_back_to_python3(self, monkeypatch):
        import shutil
        from scriptpilot.executor import _resolve_command
        monkeypatch.setattr(shutil, "which", lambda c: f"/usr/bin/{c}" if c == "python3" else None)
        cmd = _resolve_command("python", "")
        assert cmd == ["/usr/bin/python3"]

    def test_python_whitespace_falls_back_to_python3(self, monkeypatch):
        import shutil
        from scriptpilot.executor import _resolve_command
        monkeypatch.setattr(shutil, "which", lambda c: f"/usr/bin/{c}" if c == "python3" else None)
        cmd = _resolve_command("python", "   ")
        assert cmd == ["/usr/bin/python3"]

    def test_python_first_token_validated(self, monkeypatch):
        import shutil
        from scriptpilot.executor import _resolve_command, InterpreterNotFoundError
        monkeypatch.setattr(shutil, "which", lambda c: None)
        with pytest.raises(InterpreterNotFoundError, match="definitely-not-real"):
            _resolve_command("python", "definitely-not-real --flag")


class TestExecuteScriptPythonCommand:
    @pytest.mark.asyncio
    async def test_python_command_python3(self, tmp_path):
        """Default 'python3' path runs without uv."""
        script = Script(
            name="py",
            description="python test",
            type="python",
            content="print('hi from py')",
        )
        path = _materialize(script, tmp_path)
        lines = []
        result = await execute_script(
            script,
            on_output=lines.append,
            script_path=path,
            python_command="python3",
        )
        assert result.exit_code == 0
        assert any("hi from py" in line for line in lines)

    @pytest.mark.asyncio
    async def test_python_command_unknown_raises(self, tmp_path):
        from scriptpilot.executor import InterpreterNotFoundError
        script = Script(
            name="py",
            description="python test",
            type="python",
            content="print('hi')",
        )
        path = _materialize(script, tmp_path)
        with pytest.raises(InterpreterNotFoundError, match="definitely-not-real"):
            await execute_script(
                script,
                script_path=path,
                python_command="definitely-not-real --flag",
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_executor.py::TestResolveCommand tests/test_executor.py::TestExecuteScriptPythonCommand -v`
Expected: FAIL — `_resolve_command` not defined; `python_command` keyword not accepted.

- [ ] **Step 3: Replace `_get_interpreter` with `_resolve_command`; add `python_command` kwarg**

In `src/scriptpilot/executor.py`:

```python
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
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()

    await read_task

    duration = time.monotonic() - start
    return ExecutionResult(
        exit_code=proc.returncode if proc.returncode is not None else -1,
        timed_out=timed_out,
        duration=duration,
    )
```

Note: `_get_interpreter` is removed. Existing test `test_interpreter_present_on_path` references it directly — fix it in the next step.

- [ ] **Step 4: Update existing tests that reference `_get_interpreter`**

In `tests/test_executor.py`, replace the `test_interpreter_present_on_path` and `test_interpreter_not_found_raises` tests:

```python
    @pytest.mark.asyncio
    async def test_interpreter_present_on_path(self):
        from scriptpilot.executor import _resolve_command
        # bash and js are static lookups; python uses python_command.
        assert _resolve_command("bash", "python3")[0]
        assert _resolve_command("python", "python3")[0]

    @pytest.mark.asyncio
    async def test_interpreter_not_found_raises(self, tmp_path, monkeypatch):
        import shutil
        monkeypatch.setattr(shutil, "which", lambda cmd: None)
        script = Script(
            name="missing",
            description="missing interpreter",
            type="bash",
            content="echo hi",
        )
        path = _materialize(script, tmp_path)
        with pytest.raises(InterpreterNotFoundError, match="bash not found"):
            await execute_script(script, script_path=path)
```

- [ ] **Step 5: Run executor tests**

Run: `uv run pytest tests/test_executor.py -v`
Expected: PASS — all existing tests plus the new `TestResolveCommand` and `TestExecuteScriptPythonCommand` classes.

- [ ] **Step 6: Commit**

```bash
git add src/scriptpilot/executor.py tests/test_executor.py
git commit -m "feat: configurable python interpreter via python_command"
```

---

### Task 4: Executor — `cwd` Resolution + `ScriptCwdError`

**Files:**
- Modify: `src/scriptpilot/executor.py`
- Modify: `tests/test_executor.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_executor.py`:

```python
class TestResolveCwd:
    def test_none_returns_home(self):
        from scriptpilot.executor import _resolve_cwd
        assert _resolve_cwd(None) == Path.home()

    def test_empty_returns_home(self):
        from scriptpilot.executor import _resolve_cwd
        assert _resolve_cwd("") == Path.home()
        assert _resolve_cwd("   ") == Path.home()

    def test_existing_dir(self, tmp_path):
        from scriptpilot.executor import _resolve_cwd
        assert _resolve_cwd(str(tmp_path)) == tmp_path

    def test_tilde_expansion(self):
        from scriptpilot.executor import _resolve_cwd
        assert _resolve_cwd("~") == Path.home()

    def test_missing_dir_raises(self):
        from scriptpilot.executor import _resolve_cwd, ScriptCwdError
        with pytest.raises(ScriptCwdError, match="cwd does not exist"):
            _resolve_cwd("/nonexistent/path/that/cannot/be/real")

    def test_file_not_directory_raises(self, tmp_path):
        from scriptpilot.executor import _resolve_cwd, ScriptCwdError
        f = tmp_path / "afile"
        f.write_text("hi")
        with pytest.raises(ScriptCwdError, match="not a directory"):
            _resolve_cwd(str(f))


class TestExecuteScriptCwd:
    @pytest.mark.asyncio
    async def test_cwd_applied(self, tmp_path):
        script = Script(
            name="pwd",
            description="prints pwd",
            type="bash",
            content="pwd",
            cwd=str(tmp_path),
        )
        path = _materialize(script, tmp_path)
        lines = []
        result = await execute_script(
            script, on_output=lines.append, script_path=path,
        )
        assert result.exit_code == 0
        # Resolve to handle macOS /private/var symlink quirks.
        assert any(str(tmp_path.resolve()) in line for line in lines)

    @pytest.mark.asyncio
    async def test_cwd_default_is_home(self, tmp_path):
        script = Script(
            name="pwd",
            description="prints pwd",
            type="bash",
            content="pwd",
        )
        path = _materialize(script, tmp_path)
        lines = []
        result = await execute_script(
            script, on_output=lines.append, script_path=path,
        )
        assert result.exit_code == 0
        assert any(str(Path.home()) in line for line in lines)

    @pytest.mark.asyncio
    async def test_cwd_missing_raises(self, tmp_path):
        from scriptpilot.executor import ScriptCwdError
        script = Script(
            name="pwd",
            description="prints pwd",
            type="bash",
            content="pwd",
            cwd="/nonexistent/path/that/cannot/be/real",
        )
        path = _materialize(script, tmp_path)
        with pytest.raises(ScriptCwdError, match="cwd does not exist"):
            await execute_script(script, script_path=path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_executor.py::TestResolveCwd tests/test_executor.py::TestExecuteScriptCwd -v`
Expected: FAIL — `_resolve_cwd` and `ScriptCwdError` don't exist; subprocess doesn't honour cwd.

- [ ] **Step 3: Add `_resolve_cwd`, `ScriptCwdError`, wire into `execute_script`**

In `src/scriptpilot/executor.py`, add the new exception and helper near the top (after `InterpreterNotFoundError`):

```python
class ScriptCwdError(Exception):
    """Raised when a Script's configured cwd is missing or invalid."""


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
```

Then update `execute_script` to call it and pass `cwd=` to the subprocess. Replace the body up to `proc = await asyncio.create_subprocess_exec(...)`:

```python
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
    cwd = _resolve_cwd(script.cwd)

    cmd = [*cmd_prefix, str(script_path)]
    if arg_values:
        cmd.extend(arg_values)

    start = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(cwd),
        start_new_session=True,
    )
    # ... rest unchanged ...
```

(Don't touch the read_task / wait_for / kill block below.)

- [ ] **Step 4: Run executor tests**

Run: `uv run pytest tests/test_executor.py -v`
Expected: PASS — all tests including the new `TestResolveCwd` and `TestExecuteScriptCwd`.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/executor.py tests/test_executor.py
git commit -m "feat: per-script cwd with ScriptCwdError"
```

---

### Task 5: Executor — Env Merging With Secrets

**Files:**
- Modify: `src/scriptpilot/executor.py`
- Modify: `tests/test_executor.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_executor.py`:

```python
class TestExecuteScriptEnv:
    @pytest.mark.asyncio
    async def test_per_script_env_applied(self, tmp_path):
        script = Script(
            name="env",
            description="echoes FOO",
            type="bash",
            content='echo "FOO=$FOO"',
            env={"FOO": "bar"},
        )
        path = _materialize(script, tmp_path)
        lines = []
        result = await execute_script(
            script, on_output=lines.append, script_path=path,
        )
        assert result.exit_code == 0
        assert any("FOO=bar" in line for line in lines)

    @pytest.mark.asyncio
    async def test_secrets_loaded_into_env(self, tmp_path, monkeypatch):
        from scriptpilot import executor as executor_mod
        monkeypatch.setattr(
            executor_mod, "load_secrets",
            lambda: {"JIRA_TOKEN": "secret123"},
        )
        script = Script(
            name="secrets",
            description="echoes JIRA_TOKEN",
            type="bash",
            content='echo "JIRA_TOKEN=$JIRA_TOKEN"',
        )
        path = _materialize(script, tmp_path)
        lines = []
        result = await execute_script(
            script, on_output=lines.append, script_path=path,
        )
        assert result.exit_code == 0
        assert any("JIRA_TOKEN=secret123" in line for line in lines)

    @pytest.mark.asyncio
    async def test_env_precedence_script_overrides_secrets_overrides_os(
        self, tmp_path, monkeypatch
    ):
        """script.env > secrets > os.environ."""
        from scriptpilot import executor as executor_mod
        monkeypatch.setenv("X", "from_env")
        monkeypatch.setenv("Y", "y_from_env")
        monkeypatch.setattr(
            executor_mod, "load_secrets",
            lambda: {"X": "from_secrets", "Y": "y_from_secrets", "Z": "z_secret"},
        )
        script = Script(
            name="prec",
            description="prints precedence",
            type="bash",
            content='echo "X=$X"; echo "Y=$Y"; echo "Z=$Z"',
            env={"X": "from_script"},
        )
        path = _materialize(script, tmp_path)
        lines = []
        result = await execute_script(
            script, on_output=lines.append, script_path=path,
        )
        assert result.exit_code == 0
        assert any("X=from_script" in line for line in lines)
        assert any("Y=y_from_secrets" in line for line in lines)
        assert any("Z=z_secret" in line for line in lines)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_executor.py::TestExecuteScriptEnv -v`
Expected: FAIL — `load_secrets` not imported in executor; `env=` not passed to subprocess.

- [ ] **Step 3: Wire secrets + env merging into the executor**

In `src/scriptpilot/executor.py`:

Add to the imports at the top:

```python
from scriptpilot.models import Script
from scriptpilot.secrets import load_secrets
```

Update `execute_script` to merge env and pass it to the subprocess:

```python
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
    cwd = _resolve_cwd(script.cwd)
    secrets = load_secrets()
    env = {**os.environ, **secrets, **script.env}

    cmd = [*cmd_prefix, str(script_path)]
    if arg_values:
        cmd.extend(arg_values)

    start = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(cwd),
        env=env,
        start_new_session=True,
    )
    # ... rest unchanged ...
```

- [ ] **Step 4: Run executor tests**

Run: `uv run pytest tests/test_executor.py -v`
Expected: PASS — full suite including the three new env tests.

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/executor.py tests/test_executor.py
git commit -m "feat: merge per-script env vars with global secrets file"
```

---

### Task 6: `EnvEditor` Widget

**Files:**
- Create: `src/scriptpilot/widgets/env_editor.py`

No tests — widgets aren't covered today (matches `arg_editor.py`). Smoke-tested manually via EditScreen in Task 11.

- [ ] **Step 1: Create the widget file**

Create `src/scriptpilot/widgets/env_editor.py`:

```python
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Button, Input, Label


class EnvRow(Widget):
    """A single environment-variable row: KEY + VALUE + remove button."""

    DEFAULT_CSS = """
    EnvRow {
        layout: horizontal;
        height: 3;
        margin-bottom: 1;
    }
    EnvRow Input {
        width: 1fr;
        margin-right: 1;
    }
    EnvRow Button {
        width: 8;
    }
    """

    def __init__(self, key: str = "", value: str = ""):
        super().__init__()
        self._key = key
        self._value = value

    def compose(self) -> ComposeResult:
        yield Input(value=self._key, placeholder="KEY", id="env-key")
        yield Input(value=self._value, placeholder="VALUE", id="env-value")
        yield Button("X", variant="error", id="env-remove")

    def to_pair(self) -> tuple[str, str] | None:
        """Return (key, value), or None if the key is empty."""
        key = self.query_one("#env-key", Input).value.strip()
        if not key:
            return None
        value = self.query_one("#env-value", Input).value
        return key, value


class EnvEditor(Widget):
    """Editor for a dict of script environment variables."""

    DEFAULT_CSS = """
    EnvEditor {
        height: auto;
        padding: 1;
        border: solid $primary;
        margin-top: 1;
    }
    EnvEditor #env-list {
        height: auto;
    }
    EnvEditor #add-env-btn {
        margin-top: 1;
    }
    """

    def __init__(self, env: dict[str, str] | None = None):
        super().__init__()
        self._initial = list((env or {}).items())

    def compose(self) -> ComposeResult:
        yield Label("[bold]Environment Variables[/bold]")
        yield Label(
            "[dim]Non-secret per-script overrides. "
            "Real secrets belong in ~/.scriptpilot/.env[/dim]"
        )
        with Vertical(id="env-list"):
            for k, v in self._initial:
                yield EnvRow(k, v)
        yield Button("+ Add Env Var", id="add-env-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "add-env-btn":
            self.query_one("#env-list", Vertical).mount(EnvRow())
        elif event.button.id == "env-remove":
            event.button.parent.remove()

    def get_env(self) -> dict[str, str]:
        """Collect all rows with a non-empty key into a dict."""
        out: dict[str, str] = {}
        for row in self.query(EnvRow):
            pair = row.to_pair()
            if pair:
                out[pair[0]] = pair[1]
        return out
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `uv run python -c "from scriptpilot.widgets.env_editor import EnvEditor, EnvRow; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Run the full test suite (sanity check)**

Run: `uv run pytest -v`
Expected: PASS (no regressions; widgets aren't tested but the import shouldn't break anything).

- [ ] **Step 4: Commit**

```bash
git add src/scriptpilot/widgets/env_editor.py
git commit -m "feat: add EnvEditor widget for per-script env vars"
```

---

### Task 7: `EditScreen` — `cwd` Input + `EnvEditor` Wiring

**Files:**
- Modify: `src/scriptpilot/screens/edit.py`

- [ ] **Step 1: Add the cwd Input and mount EnvEditor**

In `src/scriptpilot/screens/edit.py`:

Add the import alongside `ArgEditor`:

```python
from scriptpilot.widgets.arg_editor import ArgEditor
from scriptpilot.widgets.env_editor import EnvEditor
```

Update `compose` — add a "Working Directory" Input above `ArgEditor`, and mount `EnvEditor` after it. Replace the `ArgEditor` line block:

```python
                yield Label("Script Content:")
                lang = TEXTUAL_LANGUAGES.get(s.type, "python") if s else "bash"
                yield TextArea(
                    s.content if s else "",
                    id="content-area",
                    language=lang,
                )
                yield Label("Working Directory:")
                yield Input(
                    value=s.cwd if (s and s.cwd) else "",
                    placeholder="~ (default: home)",
                    id="cwd-input",
                )
                yield ArgEditor(s.args if s else [])
                yield EnvEditor(s.env if s else {})
            with Horizontal(id="button-bar"):
```

- [ ] **Step 2: Collect cwd and env on save**

Update `_save` in `EditScreen` to read the new fields and apply them to both the existing-script and new-script branches:

```python
    def _save(self):
        name = self.query_one("#name-input", Input).value.strip()
        desc = self.query_one("#desc-input", Input).value.strip()
        script_type = self.query_one("#type-select", Select).value
        content = self.query_one("#content-area", TextArea).text
        timeout_str = self.query_one("#timeout-input", Input).value.strip()
        args = self.query_one(ArgEditor).get_args()
        cwd_str = self.query_one("#cwd-input", Input).value.strip() or None
        env = self.query_one(EnvEditor).get_env()

        if not name:
            self.notify("Script name is required", severity="error")
            return
        if not content.strip():
            self.notify("Script content is required", severity="error")
            return

        try:
            timeout = int(timeout_str)
        except ValueError:
            timeout = 60

        if self._script:
            self._script.name = name
            self._script.description = desc
            self._script.type = script_type
            self._script.content = content
            self._script.timeout = timeout
            self._script.args = args
            self._script.cwd = cwd_str
            self._script.env = env
            self.dismiss(self._script)
        else:
            script = Script(
                name=name,
                description=desc,
                type=script_type,
                content=content,
                timeout=timeout,
                args=args,
                cwd=cwd_str,
                env=env,
            )
            self.dismiss(script)
```

- [ ] **Step 3: Verify the module imports cleanly**

Run: `uv run python -c "from scriptpilot.screens.edit import EditScreen; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Run the full test suite (no regressions)**

Run: `uv run pytest -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/screens/edit.py
git commit -m "feat: surface cwd and env fields in EditScreen"
```

---

### Task 8: `SettingsScreen` — `python_command` + Secrets Status

**Files:**
- Modify: `src/scriptpilot/screens/settings.py`

- [ ] **Step 1: Add the python_command Input + secrets status**

Replace `src/scriptpilot/screens/settings.py` with:

```python
from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label

from scriptpilot.models import AppConfig
from scriptpilot.secrets import SECRETS_PATH, load_secrets


class SettingsScreen(ModalScreen[AppConfig | None]):
    """Modal screen for app settings."""

    DEFAULT_CSS = """
    SettingsScreen {
        align: center middle;
    }
    SettingsScreen #settings-container {
        width: 60%;
        max-width: 80;
        height: auto;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    SettingsScreen Input {
        margin-bottom: 1;
    }
    SettingsScreen #button-bar {
        height: 3;
        align: right middle;
        margin-top: 1;
    }
    SettingsScreen #button-bar Button {
        margin-left: 1;
    }
    """

    def __init__(self, config: AppConfig):
        super().__init__()
        self._config = config

    def compose(self) -> ComposeResult:
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        key_status = "[green]Set[/green]" if api_key else "[red]Not set[/red]"

        if SECRETS_PATH.exists():
            n = len(load_secrets())
            secrets_status = f"[green]{n} keys loaded[/green]"
        else:
            secrets_status = "[dim]not present[/dim]"

        with Vertical(id="settings-container"):
            yield Label("[bold]Settings[/bold]")
            yield Label("")
            yield Label(f"OpenRouter API Key: {key_status}")
            yield Label("[dim]Set via OPENROUTER_API_KEY environment variable[/dim]")
            yield Label("")
            yield Label("Default Model:")
            yield Input(
                value=self._config.default_model,
                id="model-input",
            )
            yield Label("Python command:")
            yield Input(
                value=self._config.python_command,
                placeholder="uv run --script",
                id="python-cmd-input",
            )
            yield Label(f"Secrets file: {SECRETS_PATH} [{secrets_status}]")
            yield Label(
                "[dim]One KEY=VALUE per line. Edit with your editor.[/dim]"
            )
            with Horizontal(id="button-bar"):
                yield Button("Cancel", id="cancel-btn")
                yield Button("Save", id="save-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "save-btn":
            model = self.query_one("#model-input", Input).value.strip()
            python_cmd = self.query_one("#python-cmd-input", Input).value.strip()
            if not python_cmd:
                python_cmd = "uv run --script"
            config = AppConfig(
                default_model=model or "openai/gpt-4o",
                python_command=python_cmd,
            )
            self.dismiss(config)
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `uv run python -c "from scriptpilot.screens.settings import SettingsScreen; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Run the full test suite**

Run: `uv run pytest -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/scriptpilot/screens/settings.py
git commit -m "feat: configure python_command and show secrets file status"
```

---

### Task 9: `MainScreen` — Pass `python_command`, Catch `ScriptCwdError`, Clone `cwd`/`env`

**Files:**
- Modify: `src/scriptpilot/screens/main.py`

- [ ] **Step 1: Update the import**

In `src/scriptpilot/screens/main.py`, expand the executor import:

```python
from scriptpilot.executor import execute_script, InterpreterNotFoundError, ScriptCwdError
```

- [ ] **Step 2: Pass `python_command` and catch `ScriptCwdError` in `_execute`**

Replace the `_execute` body (the `try` block portion only):

```python
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
                    output="\n".join(output_lines),
                )
                self._history.add(record)
            except (InterpreterNotFoundError, ScriptCwdError) as e:
                panel.show_error(str(e))
                self.notify(str(e), severity="error")
            except Exception as e:
                panel.show_error(f"Error: {e}")
                self.notify(str(e), severity="error")
```

- [ ] **Step 3: Copy `cwd` and `env` on clone**

Replace `action_clone_script` so the clone carries cwd and env:

```python
    def action_clone_script(self):
        if not self._selected_script:
            self.notify("No script selected", severity="warning")
            return

        original = self._selected_script
        clone = Script(
            name=f"{original.name} (copy)",
            description=original.description,
            type=original.type,
            content=original.content,
            args=[ScriptArg(**a.model_dump()) for a in original.args],
            timeout=original.timeout,
            favorite=False,
            cwd=original.cwd,
            env=dict(original.env),
        )
        self._store.add(clone)
        self._refresh_list()
        self.notify(f"Cloned '{original.name}'")
```

Also update `action_toggle_favorite` so the rebuilt `Script` keeps `cwd`/`env` (the current code constructs a fresh `Script` from selected fields and would otherwise drop them):

```python
    def action_toggle_favorite(self):
        if not self._selected_script:
            self.notify("No script selected", severity="warning")
            return

        script = self._selected_script
        updated = Script(
            id=script.id,
            name=script.name,
            description=script.description,
            type=script.type,
            content=script.content,
            args=script.args,
            timeout=script.timeout,
            favorite=not script.favorite,
            cwd=script.cwd,
            env=script.env,
        )
        self._store.update(updated)
        self._selected_script = updated
        self._refresh_list()
        last_run = self._get_last_run(updated.id)
        self.query_one(MainPanel).show_script_details(updated, last_run)
        label = "Favorited" if updated.favorite else "Unfavorited"
        self.notify(f"{label} '{updated.name}'")
```

- [ ] **Step 4: Verify the module imports cleanly**

Run: `uv run python -c "from scriptpilot.screens.main import MainScreen; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -v`
Expected: PASS — full suite green.

- [ ] **Step 6: Commit**

```bash
git add src/scriptpilot/screens/main.py
git commit -m "feat: wire python_command, ScriptCwdError, and clone cwd/env in MainScreen"
```

---

### Task 10: README Update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a "Reproducible Execution" section before "Keyboard Shortcuts"**

In `README.md`, insert this section after the "AI Generation (Optional)" section and before "Keyboard Shortcuts":

```markdown
## Reproducible Execution

Each script can pin its **working directory** and **environment variables** in the edit screen, so relative paths and per-script overrides Just Work.

### Per-script `cwd`

Set `Working Directory` in the edit screen to e.g. `~/work/data`. The script runs from that directory; `~` is expanded at run time. Leave blank to use your home directory. A missing or non-directory path fails the run with a clear error.

### Per-script `env`

Add `KEY=VALUE` pairs in the edit screen's Environment Variables section for non-secret overrides like `ENVIRONMENT=staging`. These are merged on top of `os.environ` and the global secrets file (next section).

### Global secrets file

ScriptPilot reads `~/.scriptpilot/.env` on every run. One `KEY=VALUE` per line; `#` comments and blank lines are ignored; surrounding `"..."` or `'...'` are stripped. No interpolation, no `export`, no multiline values.

```
# ~/.scriptpilot/.env
JIRA_TOKEN=eyJhbGciOi...
OPENAI_API_KEY="sk-..."
```

Don't paste tokens into per-script `env` — they live with the script body and would be cloned/shared. Use this file instead.

Precedence (low → high): `os.environ` < `~/.scriptpilot/.env` < per-script `env`.

### Python deps via `uv run --script` (PEP 723)

By default ScriptPilot runs Python scripts with `uv run --script`, so a script with a [PEP 723](https://peps.python.org/pep-0723/) header pulls its deps automatically:

```python
# /// script
# dependencies = ["pandas", "openpyxl"]
# ///
import pandas as pd
print(pd.read_csv("input.csv").shape)
```

Change `Python command` in Settings to `python3` if you don't have [`uv`](https://docs.astral.sh/uv/) installed; PEP 723 won't be honoured in that mode. Bash and JS interpreters (`bash`, `node`) are not configurable.
```

- [ ] **Step 2: Verify the README renders sensibly**

Run: `head -60 README.md`
Expected: Existing structure intact, with the new section visible.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document cwd, env, secrets file, and python_command"
```

---

### Task 11: Manual Smoke Test

**Files:** none (manual run).

This validates the three acceptance criteria from the spec end-to-end. The user runs these by hand; if any fail, file a follow-up.

- [ ] **Step 1: Acceptance — PEP 723 Python script via `uv run --script`**

Pre-req: `uv` on PATH (`which uv` should return a path).

Launch: `uv run scriptpilot`

In the TUI: press `n`, create a Python script with content:

```python
# /// script
# dependencies = ["requests"]
# ///
import requests
print("requests version:", requests.__version__)
```

Save and run (`r`). Expected: output prints something like `requests version: 2.x.x`. If `uv` first-runs the venv, that's normal — re-runs are fast.

- [ ] **Step 2: Acceptance — cwd + relative path**

In a shell: `mkdir -p ~/work/data && echo "col1,col2" > ~/work/data/input.csv`

In the TUI: press `n`, create a Bash script:
- Working Directory: `~/work/data`
- Content: `cat input.csv`

Save and run. Expected: output shows `col1,col2`. If you remove the cwd (or set it to a missing path), the run should fail with a "cwd does not exist" error in the panel.

- [ ] **Step 3: Acceptance — global secrets**

In a shell: `mkdir -p ~/.scriptpilot && echo 'JIRA_TOKEN=hello-world' >> ~/.scriptpilot/.env`

In the TUI: press `s` (Settings) — confirm `Secrets file: ~/.scriptpilot/.env [1 keys loaded]` (count may differ if the file already had keys). Cancel.

Press `n`, create a Python script:

```python
import os
print("token:", os.environ.get("JIRA_TOKEN", "<unset>"))
```

Save and run. Expected: `token: hello-world`.

- [ ] **Step 4: Cleanup**

Remove the demo file/dir if you don't want to keep them:

```bash
rm ~/work/data/input.csv  # only if you created it just for this
# Edit ~/.scriptpilot/.env to remove the JIRA_TOKEN line if it was just for the test.
```

- [ ] **Step 5: No commit needed** — this task only validates that the implementation works end-to-end.

---

## Self-review notes

- **Spec coverage:** Each spec section maps to a task — data model (1), secrets module (2), executor: interpreter (3) / cwd (4) / env (5), EnvEditor (6), EditScreen (7), SettingsScreen (8), MainScreen wiring (9), README (10), acceptance (11). Nothing left over.
- **Type consistency:** `_resolve_command(script_type, python_command)`, `_resolve_cwd(script_cwd)`, `ScriptCwdError`, `load_secrets`, `SECRETS_PATH`, `EnvEditor.get_env()`, `EnvRow.to_pair()` — names match across tasks.
- **Frequent commits:** every task ends in a commit; tasks are 4–6 steps each.
- **No placeholders:** every step has the actual code or command.
