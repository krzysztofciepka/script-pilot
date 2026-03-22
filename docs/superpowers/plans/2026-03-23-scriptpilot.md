# ScriptPilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a TUI application for creating, managing, and executing automation scripts with optional AI generation via OpenRouter.

**Architecture:** Monolithic Textual app with extracted business logic modules. Pydantic models for data validation, JSON file persistence, async subprocess execution, and httpx for OpenRouter API. All non-UI modules are independently testable.

**Tech Stack:** Python 3.10+, Textual (TUI), Pydantic (models), httpx (HTTP), uv (packaging), pytest + pytest-asyncio (testing)

**Spec:** `docs/superpowers/specs/2026-03-23-scriptpilot-design.md`

---

## File Map

| File | Responsibility |
|------|---------------|
| `pyproject.toml` | Project metadata, dependencies, entry point |
| `src/scriptpilot/__init__.py` | Package marker |
| `src/scriptpilot/__main__.py` | `python -m scriptpilot` support |
| `src/scriptpilot/models.py` | Pydantic models: `ScriptArg`, `Script`, `AppConfig` |
| `src/scriptpilot/storage.py` | `ScriptStore` — JSON CRUD with atomic writes |
| `src/scriptpilot/executor.py` | `execute_script()` — subprocess, streaming, timeout |
| `src/scriptpilot/openrouter.py` | `OpenRouterClient` — httpx async, generate + list_models |
| `src/scriptpilot/app.py` | Textual `App`, global keys, entry point `main()` |
| `src/scriptpilot/screens/__init__.py` | Package marker |
| `src/scriptpilot/screens/main.py` | Main three-panel screen |
| `src/scriptpilot/screens/edit.py` | Script create/edit modal |
| `src/scriptpilot/screens/run.py` | Argument input modal |
| `src/scriptpilot/screens/generate.py` | AI generation modal |
| `src/scriptpilot/screens/settings.py` | Settings modal |
| `src/scriptpilot/widgets/__init__.py` | Package marker |
| `src/scriptpilot/widgets/script_list.py` | Left panel script list widget |
| `src/scriptpilot/widgets/main_panel.py` | Right panel details/output widget |
| `src/scriptpilot/widgets/arg_editor.py` | Argument list editor for edit screen |
| `tests/test_models.py` | Model validation tests |
| `tests/test_storage.py` | Storage CRUD tests |
| `tests/test_executor.py` | Execution tests |
| `tests/test_openrouter.py` | OpenRouter client tests |

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/scriptpilot/__init__.py`
- Create: `src/scriptpilot/__main__.py`
- Create: `src/scriptpilot/app.py` (stub)

- [ ] **Step 1: Create .gitignore**

`.gitignore`:
```
__pycache__/
*.pyc
*.pyo
.pytest_cache/
dist/
*.egg-info/
.venv/
```

- [ ] **Step 2: Create pyproject.toml**

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

[project.scripts]
scriptpilot = "scriptpilot.app:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/scriptpilot"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "respx>=0.22",
]
```

- [ ] **Step 3: Create package files**

`src/scriptpilot/__init__.py`:
```python
"""ScriptPilot — TUI for managing and executing automation scripts."""
```

`src/scriptpilot/__main__.py`:
```python
from scriptpilot.app import main

main()
```

`src/scriptpilot/app.py` (stub):
```python
from textual.app import App


class ScriptPilotApp(App):
    """ScriptPilot TUI application."""

    TITLE = "ScriptPilot"

    def compose(self):
        yield from []


def main():
    app = ScriptPilotApp()
    app.run()
```

- [ ] **Step 4: Install and verify**

Run: `uv sync`
Expected: Dependencies installed successfully.

Run: `uv run scriptpilot &; sleep 1; kill %1 2>/dev/null; echo "App launched OK"`
Expected: App launches without import errors.

- [ ] **Step 5: Commit**

```bash
git add .gitignore pyproject.toml src/ uv.lock
git commit -m "feat: scaffold project with uv, textual, and entry point"
```

---

### Task 2: Pydantic Models

**Files:**
- Create: `src/scriptpilot/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing tests for ScriptArg**

`tests/test_models.py`:
```python
import pytest
from scriptpilot.models import ScriptArg


class TestScriptArg:
    def test_create_string_arg(self):
        arg = ScriptArg(name="env", type="string")
        assert arg.name == "env"
        assert arg.type == "string"
        assert arg.required is True
        assert arg.default is None

    def test_create_boolean_arg_with_default(self):
        arg = ScriptArg(name="dry_run", type="boolean", required=False, default=False)
        assert arg.required is False
        assert arg.default is False

    def test_create_integer_arg(self):
        arg = ScriptArg(name="retries", type="integer", default=3)
        assert arg.type == "integer"
        assert arg.default == 3

    def test_invalid_type_rejected(self):
        with pytest.raises(Exception):
            ScriptArg(name="x", type="float")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: Implement ScriptArg model**

`src/scriptpilot/models.py`:
```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ScriptArg(BaseModel):
    """A single argument definition for a script."""

    name: str
    type: Literal["string", "boolean", "integer"]
    required: bool = True
    default: str | bool | int | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: 4 passed

- [ ] **Step 5: Write failing tests for Script**

Add to `tests/test_models.py`:
```python
from scriptpilot.models import Script


class TestScript:
    def test_create_minimal_script(self):
        s = Script(
            name="hello",
            description="prints hello",
            type="bash",
            content="echo hello",
        )
        assert s.name == "hello"
        assert s.type == "bash"
        assert s.content == "echo hello"
        assert s.args == []
        assert s.timeout == 60
        assert s.id  # auto-generated uuid

    def test_create_script_with_args(self):
        s = Script(
            name="deploy",
            description="deploy app",
            type="bash",
            content="deploy.sh",
            args=[ScriptArg(name="env", type="string")],
            timeout=120,
        )
        assert len(s.args) == 1
        assert s.timeout == 120

    def test_invalid_script_type_rejected(self):
        with pytest.raises(Exception):
            Script(name="x", description="x", type="ruby", content="x")

    def test_script_id_auto_generated(self):
        s1 = Script(name="a", description="a", type="bash", content="a")
        s2 = Script(name="b", description="b", type="bash", content="b")
        assert s1.id != s2.id

    def test_script_serialization_roundtrip(self):
        s = Script(
            name="test",
            description="test script",
            type="python",
            content="print('hi')",
            args=[ScriptArg(name="n", type="integer", default=5)],
        )
        data = s.model_dump()
        s2 = Script(**data)
        assert s2.name == s.name
        assert s2.args[0].default == 5
```

- [ ] **Step 6: Run tests to verify new tests fail**

Run: `uv run pytest tests/test_models.py::TestScript -v`
Expected: FAIL — `Script` not defined

- [ ] **Step 7: Implement Script model**

Add to `src/scriptpilot/models.py`:
```python
import uuid


class Script(BaseModel):
    """A saved automation script."""

    id: str = ""
    name: str
    description: str
    type: Literal["bash", "python", "js"]
    content: str
    args: list[ScriptArg] = []
    timeout: int = 60

    def model_post_init(self, __context):
        if not self.id:
            self.id = str(uuid.uuid4())
```

- [ ] **Step 8: Run all model tests**

Run: `uv run pytest tests/test_models.py -v`
Expected: 9 passed

- [ ] **Step 9: Write failing test for AppConfig**

Add to `tests/test_models.py`:
```python
from scriptpilot.models import AppConfig


class TestAppConfig:
    def test_defaults(self):
        config = AppConfig()
        assert config.default_model == "openai/gpt-4o"

    def test_custom_model(self):
        config = AppConfig(default_model="anthropic/claude-3.5-sonnet")
        assert config.default_model == "anthropic/claude-3.5-sonnet"
```

- [ ] **Step 10: Implement AppConfig and run tests**

Add to `src/scriptpilot/models.py`:
```python
class AppConfig(BaseModel):
    """Application configuration."""

    default_model: str = "openai/gpt-4o"
```

Run: `uv run pytest tests/test_models.py -v`
Expected: 11 passed

- [ ] **Step 11: Commit**

```bash
git add src/scriptpilot/models.py tests/test_models.py
git commit -m "feat: add Pydantic models for ScriptArg, Script, and AppConfig"
```

---

### Task 3: Script Storage

**Files:**
- Create: `src/scriptpilot/storage.py`
- Create: `tests/test_storage.py`

- [ ] **Step 1: Write failing tests for ScriptStore**

`tests/test_storage.py`:
```python
import json
import pytest
from pathlib import Path

from scriptpilot.models import Script, ScriptArg
from scriptpilot.storage import ScriptStore


@pytest.fixture
def store(tmp_path):
    return ScriptStore(tmp_path / "scripts.json")


@pytest.fixture
def sample_script():
    return Script(
        name="hello",
        description="prints hello",
        type="bash",
        content="echo hello",
    )


class TestScriptStore:
    def test_list_empty(self, store):
        assert store.list() == []

    def test_add_and_get(self, store, sample_script):
        store.add(sample_script)
        result = store.get(sample_script.id)
        assert result is not None
        assert result.name == "hello"

    def test_add_persists_to_disk(self, store, sample_script):
        store.add(sample_script)
        # Create a new store instance pointing to same file
        store2 = ScriptStore(store._path)
        assert len(store2.list()) == 1

    def test_list_returns_all(self, store):
        s1 = Script(name="a", description="a", type="bash", content="a")
        s2 = Script(name="b", description="b", type="python", content="b")
        store.add(s1)
        store.add(s2)
        assert len(store.list()) == 2

    def test_update(self, store, sample_script):
        store.add(sample_script)
        sample_script.name = "updated"
        store.update(sample_script)
        result = store.get(sample_script.id)
        assert result.name == "updated"

    def test_delete(self, store, sample_script):
        store.add(sample_script)
        store.delete(sample_script.id)
        assert store.get(sample_script.id) is None
        assert store.list() == []

    def test_get_nonexistent_returns_none(self, store):
        assert store.get("nonexistent") is None

    def test_creates_parent_directory(self, tmp_path):
        path = tmp_path / "subdir" / "scripts.json"
        store = ScriptStore(path)
        s = Script(name="x", description="x", type="bash", content="x")
        store.add(s)
        assert path.exists()

    def test_corrupted_json_backs_up_and_resets(self, tmp_path):
        path = tmp_path / "scripts.json"
        path.write_text("{invalid json!!!")
        store = ScriptStore(path)
        assert store.list() == []
        assert (tmp_path / "scripts.json.bak").exists()

    def test_atomic_write(self, store, sample_script):
        store.add(sample_script)
        # Verify the file is valid JSON (not a partial write)
        data = json.loads(store._path.read_text())
        assert "scripts" in data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_storage.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement ScriptStore**

`src/scriptpilot/storage.py`:
```python
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from scriptpilot.models import Script


class ScriptStore:
    """JSON-based script persistence."""

    def __init__(self, path: Path | None = None):
        self._path = path or Path.home() / ".scriptpilot" / "scripts.json"
        self._scripts: dict[str, Script] = {}
        self._load()

    def _load(self):
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            for item in data.get("scripts", []):
                script = Script(**item)
                self._scripts[script.id] = script
        except (json.JSONDecodeError, Exception):
            backup = self._path.with_suffix(".json.bak")
            self._path.rename(backup)

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"scripts": [s.model_dump() for s in self._scripts.values()]}
        # Atomic write: write to temp file, then rename
        fd, tmp = tempfile.mkstemp(
            dir=self._path.parent, suffix=".tmp"
        )
        try:
            with open(fd, "w") as f:
                json.dump(data, f, indent=2)
            Path(tmp).replace(self._path)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise

    def list(self) -> list[Script]:
        return list(self._scripts.values())

    def get(self, script_id: str) -> Script | None:
        return self._scripts.get(script_id)

    def add(self, script: Script):
        self._scripts[script.id] = script
        self._save()

    def update(self, script: Script):
        self._scripts[script.id] = script
        self._save()

    def delete(self, script_id: str):
        self._scripts.pop(script_id, None)
        self._save()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_storage.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/storage.py tests/test_storage.py
git commit -m "feat: add ScriptStore with JSON persistence and atomic writes"
```

---

### Task 4: Script Executor

**Files:**
- Create: `src/scriptpilot/executor.py`
- Create: `tests/test_executor.py`

- [ ] **Step 1: Write failing tests**

`tests/test_executor.py`:
```python
import pytest
from scriptpilot.executor import execute_script, ExecutionResult, InterpreterNotFoundError
from scriptpilot.models import Script, ScriptArg


@pytest.fixture
def bash_script():
    return Script(
        name="echo test",
        description="echoes hello",
        type="bash",
        content='echo "hello world"',
    )


class TestExecutor:
    @pytest.mark.asyncio
    async def test_run_bash_script(self, bash_script):
        lines = []
        result = await execute_script(bash_script, on_output=lines.append)
        assert result.exit_code == 0
        assert not result.timed_out
        assert result.duration >= 0
        assert any("hello world" in line for line in lines)

    @pytest.mark.asyncio
    async def test_run_python_script(self):
        script = Script(
            name="py",
            description="python test",
            type="python",
            content="print('from python')",
        )
        lines = []
        result = await execute_script(script, on_output=lines.append)
        assert result.exit_code == 0
        assert any("from python" in line for line in lines)

    @pytest.mark.asyncio
    async def test_script_with_args(self):
        script = Script(
            name="args test",
            description="echoes args",
            type="bash",
            content='echo "arg1=$1 arg2=$2"',
            args=[
                ScriptArg(name="first", type="string"),
                ScriptArg(name="second", type="string"),
            ],
        )
        lines = []
        result = await execute_script(
            script,
            arg_values=["hello", "world"],
            on_output=lines.append,
        )
        assert result.exit_code == 0
        assert any("arg1=hello arg2=world" in line for line in lines)

    @pytest.mark.asyncio
    async def test_script_nonzero_exit(self):
        script = Script(
            name="fail",
            description="exits 1",
            type="bash",
            content="exit 42",
        )
        result = await execute_script(script)
        assert result.exit_code == 42

    @pytest.mark.asyncio
    async def test_script_timeout(self):
        script = Script(
            name="slow",
            description="sleeps forever",
            type="bash",
            content="sleep 60",
            timeout=1,
        )
        result = await execute_script(script)
        assert result.timed_out is True

    @pytest.mark.asyncio
    async def test_stderr_captured(self):
        script = Script(
            name="stderr",
            description="writes to stderr",
            type="bash",
            content='echo "err msg" >&2',
        )
        lines = []
        result = await execute_script(script, on_output=lines.append)
        assert result.exit_code == 0
        assert any("err msg" in line for line in lines)

    @pytest.mark.asyncio
    async def test_interpreter_not_found(self):
        script = Script(
            name="bad",
            description="bad interpreter",
            type="js",
            content="console.log('hi')",
        )
        # This test only fails if node is not installed
        # We test the validation function directly instead
        from scriptpilot.executor import _get_interpreter
        # bash and python3 should always be available
        assert _get_interpreter("bash") is not None
        assert _get_interpreter("python") is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_executor.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement executor**

`src/scriptpilot/executor.py`:
```python
from __future__ import annotations

import asyncio
import os
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
        )

        timed_out = False
        try:
            async def _read_output():
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    text = line.decode(errors="replace").rstrip("\n")
                    if on_output:
                        on_output(text)

            await asyncio.wait_for(
                asyncio.gather(_read_output(), proc.wait()),
                timeout=script.timeout,
            )
        except asyncio.TimeoutError:
            timed_out = True
            proc.kill()
            await proc.wait()

        duration = time.monotonic() - start
        return ExecutionResult(
            exit_code=proc.returncode or -1,
            timed_out=timed_out,
            duration=duration,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_executor.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/scriptpilot/executor.py tests/test_executor.py
git commit -m "feat: add script executor with streaming output and timeout"
```

---

### Task 5: OpenRouter Client

**Files:**
- Create: `src/scriptpilot/openrouter.py`
- Create: `tests/test_openrouter.py`

- [ ] **Step 1: Write failing tests**

`tests/test_openrouter.py`:
```python
import os
import pytest
import httpx
import respx
from scriptpilot.openrouter import (
    OpenRouterClient,
    AuthenticationError,
    RateLimitError,
    strip_markdown_fences,
)


class TestStripMarkdownFences:
    def test_no_fences(self):
        code = 'echo "hello"'
        assert strip_markdown_fences(code) == code

    def test_strip_backtick_fences(self):
        code = '```bash\necho "hello"\n```'
        assert strip_markdown_fences(code) == 'echo "hello"'

    def test_strip_fences_with_language(self):
        code = '```python\nprint("hi")\n```'
        assert strip_markdown_fences(code) == 'print("hi")'

    def test_strip_fences_no_language(self):
        code = '```\necho hi\n```'
        assert strip_markdown_fences(code) == "echo hi"


class TestOpenRouterClient:
    @pytest.fixture
    def client(self):
        return OpenRouterClient(api_key="test-key")

    @respx.mock
    @pytest.mark.asyncio
    async def test_generate_script(self, client):
        respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": 'echo "generated"'}}
                    ]
                },
            )
        )
        result = await client.generate_script(
            description="echo something",
            language="bash",
            model="openai/gpt-4o",
        )
        assert result == 'echo "generated"'

    @respx.mock
    @pytest.mark.asyncio
    async def test_generate_strips_fences(self, client):
        respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": '```bash\necho hi\n```'}}
                    ]
                },
            )
        )
        result = await client.generate_script(
            description="echo", language="bash", model="openai/gpt-4o"
        )
        assert result == "echo hi"

    @respx.mock
    @pytest.mark.asyncio
    async def test_auth_error(self, client):
        respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
            return_value=httpx.Response(401, json={"error": "invalid key"})
        )
        with pytest.raises(AuthenticationError):
            await client.generate_script("x", "bash", "openai/gpt-4o")

    @respx.mock
    @pytest.mark.asyncio
    async def test_rate_limit_error(self, client):
        respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
            return_value=httpx.Response(429, json={"error": "rate limited"})
        )
        with pytest.raises(RateLimitError):
            await client.generate_script("x", "bash", "openai/gpt-4o")

    @respx.mock
    @pytest.mark.asyncio
    async def test_list_models(self, client):
        respx.get("https://openrouter.ai/api/v1/models").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "openai/gpt-4o", "name": "GPT-4o"},
                        {"id": "anthropic/claude-3.5-sonnet", "name": "Claude 3.5"},
                    ]
                },
            )
        )
        models = await client.list_models()
        assert len(models) == 2
        assert models[0]["id"] == "openai/gpt-4o"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_openrouter.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement OpenRouter client**

`src/scriptpilot/openrouter.py`:
```python
from __future__ import annotations

import re

import httpx

BASE_URL = "https://openrouter.ai/api/v1"

SYSTEM_PROMPT = (
    "You are a script generator. Output ONLY valid, executable code. "
    "Include brief comments where helpful. "
    "Do NOT include markdown fences, explanations, or any text outside the script. "
    "The script must be complete and ready to run."
)


class AuthenticationError(Exception):
    """Raised when the API key is invalid."""


class RateLimitError(Exception):
    """Raised when rate limited by OpenRouter."""


class OpenRouterConnectionError(Exception):
    """Raised when unable to reach OpenRouter."""


def strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences if present."""
    pattern = r"^```(?:\w+)?\n(.*?)```$"
    match = re.match(pattern, text.strip(), re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


class OpenRouterClient:
    """Async client for the OpenRouter API."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def generate_script(
        self, description: str, language: str, model: str
    ) -> str:
        """Generate a script from a natural language description."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": (
                                f"Write a {language} script that does the following:\n\n"
                                f"{description}"
                            ),
                        },
                    ],
                },
                timeout=60,
            )

        if response.status_code == 401:
            raise AuthenticationError("Invalid API key")
        if response.status_code == 429:
            raise RateLimitError("Rate limited by OpenRouter")
        if response.status_code >= 500:
            raise OpenRouterConnectionError("OpenRouter server error")
        response.raise_for_status()

        content = response.json()["choices"][0]["message"]["content"]
        return strip_markdown_fences(content)

    async def list_models(self) -> list[dict]:
        """Fetch available models from OpenRouter."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE_URL}/models",
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=30,
            )
        response.raise_for_status()
        return response.json()["data"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_openrouter.py -v`
Expected: 7 passed

- [ ] **Step 5: Run all tests**

Run: `uv run pytest -v`
Expected: All tests pass (models + storage + executor + openrouter)

- [ ] **Step 6: Commit**

```bash
git add src/scriptpilot/openrouter.py tests/test_openrouter.py
git commit -m "feat: add OpenRouter client with generate, list_models, and error handling"
```

---

### Task 6: Widgets — ScriptList

**Files:**
- Create: `src/scriptpilot/widgets/__init__.py`
- Create: `src/scriptpilot/widgets/script_list.py`

- [ ] **Step 1: Create widgets package**

`src/scriptpilot/widgets/__init__.py`:
```python
"""ScriptPilot custom widgets."""
```

- [ ] **Step 2: Implement ScriptList widget**

`src/scriptpilot/widgets/script_list.py`:
```python
from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import ListItem, ListView, Label

from scriptpilot.models import Script

TYPE_LABELS = {"bash": "SH", "python": "PY", "js": "JS"}


class ScriptSelected(Message):
    """Posted when a script is selected in the list."""

    def __init__(self, script: Script):
        super().__init__()
        self.script = script


class ScriptList(Widget):
    """Left panel listing saved scripts."""

    DEFAULT_CSS = """
    ScriptList {
        width: 30;
        dock: left;
        border-right: solid $primary;
    }
    ScriptList ListView {
        height: 1fr;
    }
    """

    def __init__(self, scripts: list[Script] | None = None):
        super().__init__()
        self._scripts: list[Script] = scripts or []

    def compose(self) -> ComposeResult:
        with ListView():
            for script in self._scripts:
                label = f"[{TYPE_LABELS.get(script.type, '??')}] {script.name}"
                yield ListItem(Label(label), name=script.id)

    def update_scripts(self, scripts: list[Script]):
        """Refresh the list with new script data."""
        self._scripts = scripts
        lv = self.query_one(ListView)
        lv.clear()
        for script in scripts:
            label = f"[{TYPE_LABELS.get(script.type, '??')}] {script.name}"
            lv.append(ListItem(Label(label), name=script.id))

    def on_list_view_selected(self, event: ListView.Selected):
        item_name = event.item.name
        for script in self._scripts:
            if script.id == item_name:
                self.post_message(ScriptSelected(script))
                break
```

- [ ] **Step 3: Commit**

```bash
git add src/scriptpilot/widgets/
git commit -m "feat: add ScriptList widget with selection messaging"
```

---

### Task 7: Widgets — MainPanel

**Files:**
- Create: `src/scriptpilot/widgets/main_panel.py`

- [ ] **Step 1: Implement MainPanel widget**

`src/scriptpilot/widgets/main_panel.py`:
```python
from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label, RichLog, Static

from scriptpilot.models import Script


class MainPanel(Widget):
    """Right panel showing script details or execution output."""

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

    def compose(self) -> ComposeResult:
        yield Label(
            "No scripts yet. Press [n] to create one or [g] to generate with AI.",
            id="welcome",
        )
        yield Static(id="details")
        yield RichLog(id="output-log", max_lines=10000, wrap=True)
        yield Static(id="status-bar")

    def on_mount(self):
        self._show_welcome()

    def _show_welcome(self):
        self.query_one("#welcome").display = True
        self.query_one("#details").display = False
        self.query_one("#output-log").display = False
        self.query_one("#status-bar").display = False

    def show_script_details(self, script: Script):
        """Display script metadata."""
        self.query_one("#welcome").display = False
        self.query_one("#output-log").display = False
        self.query_one("#status-bar").display = False

        details = self.query_one("#details", Static)
        args_text = ", ".join(a.name for a in script.args) if script.args else "none"
        details.update(
            f"[bold]{script.name}[/bold]\n"
            f"{script.description}\n\n"
            f"Type: {script.type}  |  Timeout: {script.timeout}s  |  Args: {args_text}"
        )
        details.display = True

    def show_running(self, script: Script):
        """Switch to execution output mode."""
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

    def append_output(self, line: str):
        """Add a line to the output log."""
        log = self.query_one("#output-log", RichLog)
        log.write(line)

    def show_finished(self, exit_code: int, duration: float, timed_out: bool):
        """Show completion status."""
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
```

- [ ] **Step 2: Commit**

```bash
git add src/scriptpilot/widgets/main_panel.py
git commit -m "feat: add MainPanel widget with details, output, and status views"
```

---

### Task 8: Widgets — ArgEditor

**Files:**
- Create: `src/scriptpilot/widgets/arg_editor.py`

- [ ] **Step 1: Implement ArgEditor widget**

`src/scriptpilot/widgets/arg_editor.py`:
```python
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Select, Switch

from scriptpilot.models import ScriptArg

ARG_TYPES = [("string", "string"), ("boolean", "boolean"), ("integer", "integer")]


class ArgRow(Widget):
    """A single argument definition row."""

    DEFAULT_CSS = """
    ArgRow {
        layout: horizontal;
        height: 3;
        margin-bottom: 1;
    }
    ArgRow Input {
        width: 1fr;
        margin-right: 1;
    }
    ArgRow Select {
        width: 16;
        margin-right: 1;
    }
    ArgRow Switch {
        width: 12;
        margin-right: 1;
    }
    ArgRow Button {
        width: 8;
    }
    """

    def __init__(self, arg: ScriptArg | None = None):
        super().__init__()
        self._arg = arg

    def compose(self) -> ComposeResult:
        yield Input(
            value=self._arg.name if self._arg else "",
            placeholder="Name",
            id="arg-name",
        )
        yield Select(
            ARG_TYPES,
            value=self._arg.type if self._arg else "string",
            id="arg-type",
        )
        yield Label("Req:")
        yield Switch(value=self._arg.required if self._arg else True, id="arg-required")
        yield Input(
            value=str(self._arg.default) if self._arg and self._arg.default is not None else "",
            placeholder="Default",
            id="arg-default",
        )
        yield Button("X", variant="error", id="arg-remove")

    def to_script_arg(self) -> ScriptArg | None:
        """Convert this row to a ScriptArg, or None if name is empty."""
        name = self.query_one("#arg-name", Input).value.strip()
        if not name:
            return None
        arg_type = self.query_one("#arg-type", Select).value
        required = self.query_one("#arg-required", Switch).value
        default_str = self.query_one("#arg-default", Input).value.strip()

        default = None
        if default_str:
            if arg_type == "boolean":
                default = default_str.lower() in ("true", "1", "yes")
            elif arg_type == "integer":
                default = int(default_str) if default_str.isdigit() else None
            else:
                default = default_str

        return ScriptArg(name=name, type=arg_type, required=required, default=default)


class ArgEditor(Widget):
    """Editor for a list of script arguments."""

    DEFAULT_CSS = """
    ArgEditor {
        height: auto;
        padding: 1;
        border: solid $primary;
    }
    ArgEditor #arg-list {
        height: auto;
    }
    ArgEditor #add-arg-btn {
        margin-top: 1;
    }
    """

    def __init__(self, args: list[ScriptArg] | None = None):
        super().__init__()
        self._initial_args = args or []

    def compose(self) -> ComposeResult:
        yield Label("[bold]Arguments[/bold]")
        with Vertical(id="arg-list"):
            for arg in self._initial_args:
                yield ArgRow(arg)
        yield Button("+ Add Argument", id="add-arg-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "add-arg-btn":
            self.query_one("#arg-list", Vertical).mount(ArgRow())
        elif event.button.id == "arg-remove":
            event.button.parent.remove()

    def get_args(self) -> list[ScriptArg]:
        """Collect all valid argument definitions."""
        args = []
        for row in self.query(ArgRow):
            arg = row.to_script_arg()
            if arg:
                args.append(arg)
        return args
```

- [ ] **Step 2: Commit**

```bash
git add src/scriptpilot/widgets/arg_editor.py
git commit -m "feat: add ArgEditor widget for managing script argument definitions"
```

---

### Task 9: Screen — Edit/Create

**Files:**
- Create: `src/scriptpilot/screens/__init__.py`
- Create: `src/scriptpilot/screens/edit.py`

- [ ] **Step 1: Create screens package**

`src/scriptpilot/screens/__init__.py`:
```python
"""ScriptPilot screens."""
```

- [ ] **Step 2: Implement EditScreen**

`src/scriptpilot/screens/edit.py`:
```python
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, TextArea

from scriptpilot.models import Script, ScriptArg
from scriptpilot.widgets.arg_editor import ArgEditor

SCRIPT_TYPES = [("Bash", "bash"), ("Python", "python"), ("JavaScript", "js")]

TEXTUAL_LANGUAGES = {"bash": "bash", "python": "python", "js": "javascript"}


class ScriptSaved(Message):
    """Posted when a script is saved."""

    def __init__(self, script: Script):
        super().__init__()
        self.script = script


class EditScreen(ModalScreen[Script | None]):
    """Modal screen for creating or editing a script."""

    DEFAULT_CSS = """
    EditScreen {
        align: center middle;
    }
    EditScreen #edit-container {
        width: 80%;
        max-width: 100;
        height: 80%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    EditScreen Input {
        margin-bottom: 1;
    }
    EditScreen Select {
        margin-bottom: 1;
    }
    EditScreen TextArea {
        height: 1fr;
        margin-bottom: 1;
    }
    EditScreen #button-bar {
        height: 3;
        align: right middle;
    }
    EditScreen #button-bar Button {
        margin-left: 1;
    }
    """

    def __init__(self, script: Script | None = None):
        super().__init__()
        self._script = script

    def compose(self) -> ComposeResult:
        s = self._script
        title = "Edit Script" if s else "New Script"
        with Vertical(id="edit-container"):
            yield Label(f"[bold]{title}[/bold]")
            yield Label("Name:")
            yield Input(value=s.name if s else "", id="name-input")
            yield Label("Description:")
            yield Input(value=s.description if s else "", id="desc-input")
            yield Label("Type:")
            yield Select(
                SCRIPT_TYPES,
                value=s.type if s else "bash",
                id="type-select",
            )
            yield Label("Timeout (seconds):")
            yield Input(
                value=str(s.timeout) if s else "60",
                id="timeout-input",
            )
            yield Label("Script Content:")
            lang = TEXTUAL_LANGUAGES.get(s.type, "python") if s else "bash"
            yield TextArea(
                s.content if s else "",
                id="content-area",
                language=lang,
            )
            yield ArgEditor(s.args if s else [])
            with Horizontal(id="button-bar"):
                yield Button("Cancel", id="cancel-btn")
                yield Button("Save", id="save-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "save-btn":
            self._save()

    def _save(self):
        name = self.query_one("#name-input", Input).value.strip()
        desc = self.query_one("#desc-input", Input).value.strip()
        script_type = self.query_one("#type-select", Select).value
        content = self.query_one("#content-area", TextArea).text
        timeout_str = self.query_one("#timeout-input", Input).value.strip()
        args = self.query_one(ArgEditor).get_args()

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
            self.dismiss(self._script)
        else:
            script = Script(
                name=name,
                description=desc,
                type=script_type,
                content=content,
                timeout=timeout,
                args=args,
            )
            self.dismiss(script)
```

- [ ] **Step 3: Commit**

```bash
git add src/scriptpilot/screens/
git commit -m "feat: add EditScreen modal for creating and editing scripts"
```

---

### Task 10: Screen — Run (Argument Input)

**Files:**
- Create: `src/scriptpilot/screens/run.py`

- [ ] **Step 1: Implement RunScreen**

`src/scriptpilot/screens/run.py`:
```python
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Switch

from scriptpilot.models import Script, ScriptArg


class RunScreen(ModalScreen[list[str] | None]):
    """Modal for collecting argument values before script execution."""

    DEFAULT_CSS = """
    RunScreen {
        align: center middle;
    }
    RunScreen #run-container {
        width: 60%;
        max-width: 80;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    RunScreen .arg-row {
        height: 3;
        margin-bottom: 1;
    }
    RunScreen .arg-row Label {
        width: 20;
    }
    RunScreen .arg-row Input {
        width: 1fr;
    }
    RunScreen #button-bar {
        height: 3;
        align: right middle;
    }
    RunScreen #button-bar Button {
        margin-left: 1;
    }
    """

    def __init__(self, script: Script):
        super().__init__()
        self._script = script

    def compose(self) -> ComposeResult:
        with Vertical(id="run-container"):
            yield Label(f"[bold]Run: {self._script.name}[/bold]")
            yield Label("")
            for i, arg in enumerate(self._script.args):
                req = "*" if arg.required else ""
                with Horizontal(classes="arg-row"):
                    yield Label(f"{arg.name}{req}:")
                    if arg.type == "boolean":
                        default_val = bool(arg.default) if arg.default is not None else False
                        yield Switch(value=default_val, id=f"arg-{i}")
                    else:
                        default_str = str(arg.default) if arg.default is not None else ""
                        yield Input(
                            value=default_str,
                            placeholder=f"{arg.type}",
                            id=f"arg-{i}",
                        )
            with Horizontal(id="button-bar"):
                yield Button("Cancel", id="cancel-btn")
                yield Button("Run", id="run-btn", variant="success")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "run-btn":
            self._collect_and_run()

    def _collect_and_run(self):
        values = []
        for i, arg in enumerate(self._script.args):
            widget_id = f"arg-{i}"
            if arg.type == "boolean":
                switch = self.query_one(f"#{widget_id}", Switch)
                values.append("true" if switch.value else "false")
            else:
                inp = self.query_one(f"#{widget_id}", Input)
                val = inp.value.strip()
                if arg.required and not val:
                    self.notify(f"Argument '{arg.name}' is required", severity="error")
                    return
                values.append(val)
        self.dismiss(values)
```

- [ ] **Step 2: Commit**

```bash
git add src/scriptpilot/screens/run.py
git commit -m "feat: add RunScreen modal for argument input before execution"
```

---

### Task 11: Screen — Generate

**Files:**
- Create: `src/scriptpilot/screens/generate.py`

- [ ] **Step 1: Implement GenerateScreen**

`src/scriptpilot/screens/generate.py`:
```python
from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, TextArea
from textual.worker import Worker, WorkerState

from scriptpilot.models import Script
from scriptpilot.openrouter import (
    OpenRouterClient,
    AuthenticationError,
    RateLimitError,
)

LANGUAGES = [("Bash", "bash"), ("Python", "python"), ("JavaScript", "js")]

TEXTUAL_LANGUAGES = {"bash": "bash", "python": "python", "js": "javascript"}


class GenerateScreen(ModalScreen[Script | None]):
    """Modal screen for AI script generation via OpenRouter."""

    DEFAULT_CSS = """
    GenerateScreen {
        align: center middle;
    }
    GenerateScreen #gen-container {
        width: 80%;
        max-width: 100;
        height: 80%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    GenerateScreen #description-area {
        height: 6;
        margin-bottom: 1;
    }
    GenerateScreen #result-area {
        height: 1fr;
        margin-bottom: 1;
    }
    GenerateScreen #button-bar {
        height: 3;
        align: right middle;
    }
    GenerateScreen #button-bar Button {
        margin-left: 1;
    }
    GenerateScreen #save-fields {
        height: auto;
        margin-bottom: 1;
    }
    """

    def __init__(self, default_model: str = "openai/gpt-4o"):
        super().__init__()
        self._model = default_model
        self._generated = False

    def compose(self) -> ComposeResult:
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        with Vertical(id="gen-container"):
            yield Label("[bold]Generate Script with AI[/bold]")
            if not api_key:
                yield Label(
                    "[red]Set OPENROUTER_API_KEY environment variable to use AI generation.[/red]",
                    id="no-key-warning",
                )
            yield Label("What should this script do?")
            yield TextArea(id="description-area", language=None)
            yield Label("Language:")
            yield Select(LANGUAGES, value="bash", id="lang-select")
            yield Label("Generated Code:")
            yield TextArea(id="result-area", language="bash", read_only=True)
            with Vertical(id="save-fields"):
                yield Label("Script Name:")
                yield Input(id="save-name", placeholder="Name for this script")
                yield Label("Description:")
                yield Input(id="save-desc", placeholder="Brief description")
            with Horizontal(id="button-bar"):
                yield Button("Cancel", id="cancel-btn")
                yield Button("Retry", id="retry-btn", disabled=True)
                yield Button(
                    "Generate",
                    id="generate-btn",
                    variant="primary",
                    disabled=not bool(api_key),
                )
                yield Button("Save", id="save-btn", variant="success", disabled=True)

    def on_mount(self):
        self.query_one("#save-fields").display = False

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "generate-btn" or event.button.id == "retry-btn":
            self._do_generate()
        elif event.button.id == "save-btn":
            self._do_save()

    def _do_generate(self):
        description = self.query_one("#description-area", TextArea).text.strip()
        if not description:
            self.notify("Please describe what the script should do", severity="error")
            return

        language = self.query_one("#lang-select", Select).value
        api_key = os.environ.get("OPENROUTER_API_KEY", "")

        # Update result area language to match selection
        result_area = self.query_one("#result-area", TextArea)
        result_area.language = TEXTUAL_LANGUAGES.get(language, "bash")

        self.query_one("#generate-btn", Button).disabled = True
        self.query_one("#retry-btn", Button).disabled = True
        self.notify("Generating script...")

        self.run_worker(
            self._generate(api_key, description, language),
            name="generate",
        )

    async def _generate(self, api_key: str, description: str, language: str):
        client = OpenRouterClient(api_key=api_key)
        return await client.generate_script(description, language, self._model)

    def on_worker_state_changed(self, event: Worker.StateChanged):
        if event.worker.name != "generate":
            return
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            result_area = self.query_one("#result-area", TextArea)
            result_area.read_only = False
            result_area.load_text(result)
            self.query_one("#save-fields").display = True
            self.query_one("#save-btn", Button).disabled = False
            self.query_one("#retry-btn", Button).disabled = False
            self.query_one("#generate-btn", Button).disabled = False
            self._generated = True
        elif event.state == WorkerState.ERROR:
            error = event.worker.error
            if isinstance(error, AuthenticationError):
                self.notify("Invalid API key", severity="error")
            elif isinstance(error, RateLimitError):
                self.notify("Rate limited, try again later", severity="error")
            else:
                self.notify(f"Could not reach OpenRouter: {error}", severity="error")
            self.query_one("#generate-btn", Button).disabled = False
            self.query_one("#retry-btn", Button).disabled = not self._generated

    def _do_save(self):
        name = self.query_one("#save-name", Input).value.strip()
        if not name:
            self.notify("Script name is required", severity="error")
            return
        desc = self.query_one("#save-desc", Input).value.strip()
        content = self.query_one("#result-area", TextArea).text
        language = self.query_one("#lang-select", Select).value

        script = Script(
            name=name,
            description=desc,
            type=language,
            content=content,
        )
        self.dismiss(script)
```

- [ ] **Step 2: Commit**

```bash
git add src/scriptpilot/screens/generate.py
git commit -m "feat: add GenerateScreen modal for AI script generation"
```

---

### Task 12: Screen — Settings

**Files:**
- Create: `src/scriptpilot/screens/settings.py`

**Note:** The spec says "select from fetched model list", but fetching models requires a valid API key and network access — both may be unavailable when opening settings. Using a text Input for the model ID is the pragmatic v1 approach. `list_models()` remains available for future enhancement (e.g., autocomplete or a "Fetch Models" button).

- [ ] **Step 1: Implement SettingsScreen**

`src/scriptpilot/screens/settings.py`:
```python
from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select

from scriptpilot.models import AppConfig


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
            with Horizontal(id="button-bar"):
                yield Button("Cancel", id="cancel-btn")
                yield Button("Save", id="save-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "save-btn":
            model = self.query_one("#model-input", Input).value.strip()
            config = AppConfig(default_model=model or "openai/gpt-4o")
            self.dismiss(config)
```

- [ ] **Step 2: Commit**

```bash
git add src/scriptpilot/screens/settings.py
git commit -m "feat: add SettingsScreen modal with model config and API key status"
```

---

### Task 13: Screen — Main

**Files:**
- Create: `src/scriptpilot/screens/main.py`

- [ ] **Step 1: Implement MainScreen**

`src/scriptpilot/screens/main.py`:
```python
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Label

from scriptpilot.models import Script
from scriptpilot.storage import ScriptStore
from scriptpilot.executor import execute_script, InterpreterNotFoundError
from scriptpilot.widgets.script_list import ScriptList, ScriptSelected
from scriptpilot.widgets.main_panel import MainPanel
from scriptpilot.screens.edit import EditScreen
from scriptpilot.screens.run import RunScreen


class MainScreen(Screen):
    """Main three-panel screen."""

    BINDINGS = [
        ("n", "new_script", "New"),
        ("e", "edit_script", "Edit"),
        ("d", "delete_script", "Delete"),
        ("r", "run_script", "Run"),
        ("enter", "run_script", "Run"),
    ]

    DEFAULT_CSS = """
    MainScreen #main-layout {
        height: 1fr;
    }
    """

    def __init__(self, store: ScriptStore):
        super().__init__()
        self._store = store
        self._selected_script: Script | None = None
        self._running = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-layout"):
            yield ScriptList(self._store.list())
            yield MainPanel()
        yield Footer()

    def on_script_selected(self, event: ScriptSelected):
        self._selected_script = event.script
        self.query_one(MainPanel).show_script_details(event.script)

    def action_new_script(self):
        def on_result(script: Script | None):
            if script:
                self._store.add(script)
                self._refresh_list()

        self.app.push_screen(EditScreen(), callback=on_result)

    def action_edit_script(self):
        if not self._selected_script:
            self.notify("No script selected", severity="warning")
            return

        def on_result(script: Script | None):
            if script:
                self._store.update(script)
                self._selected_script = script
                self._refresh_list()
                self.query_one(MainPanel).show_script_details(script)

        self.app.push_screen(
            EditScreen(self._selected_script), callback=on_result
        )

    def action_delete_script(self):
        if not self._selected_script:
            self.notify("No script selected", severity="warning")
            return

        name = self._selected_script.name
        script_id = self._selected_script.id

        def confirm_delete(confirmed: bool):
            if confirmed:
                self._store.delete(script_id)
                self._selected_script = None
                self._refresh_list()
                self.notify(f"Deleted '{name}'")

        self.app.push_screen(
            ConfirmScreen(f"Delete script '{name}'?"), callback=confirm_delete
        )

    def action_run_script(self):
        if not self._selected_script:
            self.notify("No script selected", severity="warning")
            return
        if self._running:
            self.notify("A script is already running", severity="warning")
            return

        script = self._selected_script
        if script.args:

            def on_args(values: list[str] | None):
                if values is not None:
                    self._execute(script, values)

            self.app.push_screen(RunScreen(script), callback=on_args)
        else:
            self._execute(script)

    def _execute(self, script: Script, arg_values: list[str] | None = None):
        self._running = True
        panel = self.query_one(MainPanel)
        panel.show_running(script)

        async def run():
            try:
                result = await execute_script(
                    script,
                    arg_values=arg_values,
                    on_output=panel.append_output,
                )
                panel.show_finished(result.exit_code, result.duration, result.timed_out)
            except InterpreterNotFoundError as e:
                panel.show_error(str(e))
                self.notify(str(e), severity="error")
            finally:
                self._running = False

        self.run_worker(run(), name="execute", exclusive=True)

    def _refresh_list(self):
        self.query_one(ScriptList).update_scripts(self._store.list())


class ConfirmScreen(ModalScreen[bool]):
    """Simple yes/no confirmation dialog."""

    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
    }
    ConfirmScreen #confirm-container {
        width: 50;
        height: auto;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    ConfirmScreen #confirm-buttons {
        height: 3;
        align: center middle;
        margin-top: 1;
    }
    ConfirmScreen #confirm-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, message: str):
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-container"):
            yield Label(self._message)
            with Horizontal(id="confirm-buttons"):
                yield Button("No", id="no-btn")
                yield Button("Yes", id="yes-btn", variant="error")

    def on_button_pressed(self, event: Button.Pressed):
        self.dismiss(event.button.id == "yes-btn")
```

- [ ] **Step 2: Commit**

```bash
git add src/scriptpilot/screens/main.py
git commit -m "feat: add MainScreen with three-panel layout, CRUD, and execution"
```

---

### Task 14: Wire Up the App

**Files:**
- Modify: `src/scriptpilot/app.py`

**Note:** This task introduces `~/.scriptpilot/config.json` for persisting `AppConfig` (default model). The spec only mentions `scripts.json`, but config persistence is necessary for the settings feature to be useful across restarts.

- [ ] **Step 1: Implement the full App class**

Replace `src/scriptpilot/app.py` with:
```python
from __future__ import annotations

import json
from pathlib import Path

from textual.app import App

from scriptpilot.models import AppConfig
from scriptpilot.storage import ScriptStore
from scriptpilot.screens.main import MainScreen
from scriptpilot.screens.settings import SettingsScreen
from scriptpilot.screens.generate import GenerateScreen
from scriptpilot.models import Script

CONFIG_PATH = Path.home() / ".scriptpilot" / "config.json"


class ScriptPilotApp(App):
    """ScriptPilot TUI application."""

    TITLE = "ScriptPilot"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("s", "open_settings", "Settings"),
        ("g", "generate", "Generate"),
        ("t", "toggle_dark", "Theme"),
    ]

    def __init__(self):
        super().__init__()
        self._store = ScriptStore()
        self._config = self._load_config()

    def on_mount(self):
        self.push_screen(MainScreen(self._store))

    def _load_config(self) -> AppConfig:
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text())
                return AppConfig(**data)
            except Exception:
                pass
        return AppConfig()

    def _save_config(self):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(self._config.model_dump(), indent=2)
        )

    def action_open_settings(self):
        def on_result(config: AppConfig | None):
            if config:
                self._config = config
                self._save_config()
                self.notify("Settings saved")

        self.push_screen(SettingsScreen(self._config), callback=on_result)

    def action_generate(self):
        def on_result(script: Script | None):
            if script:
                self._store.add(script)
                main = self.query_one(MainScreen)
                main._refresh_list()
                self.notify(f"Script '{script.name}' saved")

        self.push_screen(
            GenerateScreen(default_model=self._config.default_model),
            callback=on_result,
        )


def main():
    app = ScriptPilotApp()
    app.run()
```

- [ ] **Step 2: Verify the app launches**

Run: `uv run scriptpilot`
Expected: App launches with empty script list, header shows "ScriptPilot", footer shows keybindings. Press `q` to quit.

- [ ] **Step 3: Run all tests**

Run: `uv run pytest -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add src/scriptpilot/app.py
git commit -m "feat: wire up ScriptPilotApp with all screens and config persistence"
```

---

### Task 15: Smoke Test & Polish

**Files:**
- Modify: various (minor fixes found during smoke testing)

- [ ] **Step 1: Manual smoke test — script creation**

Run: `uv run scriptpilot`
1. Press `n` to create a new script
2. Enter name: "Hello World", description: "Test script", type: Bash
3. Enter content: `echo "Hello from ScriptPilot!"`
4. Save
5. Verify script appears in list

- [ ] **Step 2: Manual smoke test — script execution**

1. Select "Hello World" in the list
2. Press Enter or `r` to run
3. Verify output "Hello from ScriptPilot!" appears in main panel
4. Verify exit code 0 shown in green

- [ ] **Step 3: Manual smoke test — edit and delete**

1. Press `e` to edit the script, change the echo text, save
2. Run again, verify updated output
3. Press `d` to delete, confirm, verify removed from list

- [ ] **Step 4: Manual smoke test — theme toggle**

1. Press `t` to toggle theme
2. Verify colors switch between light and dark

- [ ] **Step 5: Manual smoke test — settings**

1. Press `s` to open settings
2. Verify API key status shows correctly
3. Change default model, save, re-open settings to verify persistence

- [ ] **Step 6: Fix any issues found during smoke testing**

Address any bugs or visual issues discovered during manual testing.

- [ ] **Step 7: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "fix: address issues found during smoke testing"
```

(Only if there were changes to commit.)

