# Scripts on Disk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor ScriptPilot's persistence so each script lives as `<id>.<ext>` + `<id>.meta.json` in `~/.scriptpilot/scripts/`, and have the executor run the on-disk body file directly instead of writing a per-run tempfile.

**Architecture:** `ScriptStore` is rewritten around a directory layout (one body file + one meta JSON per script, paired by UUID stem). `Script.content` stays as an in-memory model field but is no longer in `meta.json` — the store reads/writes the body file separately. Executor accepts a `script_path` argument and invokes the interpreter directly on the on-disk file. A new `paths.py` module holds the shared `type → extension` mapping. No migration: the legacy `~/.scriptpilot/scripts.json` blob is left untouched and ignored.

**Tech Stack:** Python 3.10+, Pydantic 2, Textual, pytest + pytest-asyncio, `uv` for env/test runner.

**Spec:** `docs/superpowers/specs/2026-04-30-scripts-on-disk-design.md`

## File Structure

**New:**
- `src/scriptpilot/paths.py` — `EXTENSIONS: dict[str, str]` mapping `"bash" → ".sh"`, `"python" → ".py"`, `"js" → ".js"`. Imported by `storage.py` and `executor.py`.

**Modified:**
- `src/scriptpilot/storage.py` — full rewrite. Constructor takes a directory. Per-script atomic body + meta writes. `path_for(id)` helper. Type-change rename in `update()`. Robust loader (skips orphans and corrupt metas).
- `src/scriptpilot/executor.py` — drop `tempfile.mkstemp` body write and `os.chmod(0o755)`. Add required keyword arg `script_path: Path`. Drop `EXTENSIONS` (moved to `paths.py`).
- `src/scriptpilot/screens/main.py` — `MainScreen._execute` passes `script_path=self._store.path_for(script.id)` to `execute_script`.
- `tests/test_storage.py` — full rewrite around new contract.
- `tests/test_executor.py` — pass `script_path` (via small fixture).

**Unchanged:**
- `src/scriptpilot/models.py`, `src/scriptpilot/history.py`, `src/scriptpilot/app.py`, all other screens, `src/scriptpilot/openrouter.py`, `src/scriptpilot/widgets/*`.

---

## Task 1: Add `paths.py` with `EXTENSIONS` mapping

**Files:**
- Create: `src/scriptpilot/paths.py`

This task creates a tiny module owning the single source of truth for script-type-to-file-extension mapping. No tests — it's a single constant; importing it implicitly verifies it.

- [ ] **Step 1: Create `paths.py`**

Write `/home/kc/repos/script-pilot/src/scriptpilot/paths.py`:

```python
from __future__ import annotations

EXTENSIONS: dict[str, str] = {
    "bash": ".sh",
    "python": ".py",
    "js": ".js",
}
```

- [ ] **Step 2: Verify the import works**

Run: `uv run python -c "from scriptpilot.paths import EXTENSIONS; print(EXTENSIONS)"`
Expected: `{'bash': '.sh', 'python': '.py', 'js': '.js'}`

- [ ] **Step 3: Commit**

```bash
git add src/scriptpilot/paths.py
git commit -m "feat: add paths module with type→extension mapping"
```

---

## Task 2: Rewrite `storage.py` — basic CRUD over per-file layout

**Files:**
- Modify (rewrite): `src/scriptpilot/storage.py`
- Modify (rewrite): `tests/test_storage.py`

This task lays down the new storage contract and the core CRUD tests. We do TDD: write the tests, watch them fail against the old implementation, then replace `storage.py`. We **do not** yet add loader edge-case coverage (orphans, corrupt metas) — that's Task 3.

The new `ScriptStore` constructor takes a **directory** (default `~/.scriptpilot/scripts/`) instead of a JSON file. The directory is created on demand. Each `add()`/`update()` writes a `<id>.<ext>` body and a `<id>.meta.json` (the `Script` model dumped without `content`). On `update()`, if the script's type changed, the old body file with the previous extension is unlinked. `_load()` walks the directory for `*.meta.json`, locates the sibling body via the `EXTENSIONS` mapping, and reconstructs `Script` with `content=body_text`.

- [ ] **Step 1: Replace `tests/test_storage.py` with the new test suite**

Replace the entire contents of `/home/kc/repos/script-pilot/tests/test_storage.py` with:

```python
import json
import pytest
from pathlib import Path

from scriptpilot.models import Script, ScriptArg
from scriptpilot.storage import ScriptStore


@pytest.fixture
def store(tmp_path):
    return ScriptStore(tmp_path / "scripts")


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
        assert result.content == "echo hello"

    def test_add_persists_to_disk(self, tmp_path, sample_script):
        s1 = ScriptStore(tmp_path / "scripts")
        s1.add(sample_script)
        s2 = ScriptStore(tmp_path / "scripts")
        loaded = s2.get(sample_script.id)
        assert loaded is not None
        assert loaded.name == "hello"
        assert loaded.content == "echo hello"

    def test_list_returns_all(self, store):
        s1 = Script(name="a", description="a", type="bash", content="echo a")
        s2 = Script(name="b", description="b", type="python", content="print('b')")
        s3 = Script(name="c", description="c", type="js", content="console.log('c')")
        store.add(s1)
        store.add(s2)
        store.add(s3)
        assert len(store.list()) == 3

    def test_update_changes_name(self, store, sample_script):
        store.add(sample_script)
        sample_script.name = "updated"
        store.update(sample_script)
        result = store.get(sample_script.id)
        assert result.name == "updated"

    def test_update_changes_content(self, store, sample_script):
        store.add(sample_script)
        sample_script.content = "echo NEW"
        store.update(sample_script)

        # Reload from disk and verify content was written.
        store2 = ScriptStore(store._dir)
        assert store2.get(sample_script.id).content == "echo NEW"

    def test_update_changes_type_renames_body_file(self, store, sample_script):
        # Start as bash → file lands at <id>.sh
        store.add(sample_script)
        old_path = store._dir / f"{sample_script.id}.sh"
        assert old_path.exists()

        # Change type to python; old .sh must be gone, new .py must exist.
        sample_script.type = "python"
        sample_script.content = "print('hi')"
        store.update(sample_script)

        new_path = store._dir / f"{sample_script.id}.py"
        assert new_path.exists()
        assert not old_path.exists()
        assert new_path.read_text() == "print('hi')"

    def test_delete(self, store, sample_script):
        store.add(sample_script)
        body_path = store._dir / f"{sample_script.id}.sh"
        meta_path = store._dir / f"{sample_script.id}.meta.json"
        assert body_path.exists() and meta_path.exists()

        store.delete(sample_script.id)

        assert store.get(sample_script.id) is None
        assert store.list() == []
        assert not body_path.exists()
        assert not meta_path.exists()

    def test_get_nonexistent_returns_none(self, store):
        assert store.get("nonexistent") is None

    def test_creates_directory_on_init(self, tmp_path):
        target = tmp_path / "deeply" / "nested" / "scripts"
        ScriptStore(target)
        assert target.exists()

    def test_add_writes_body_and_meta_files(self, store, sample_script):
        store.add(sample_script)
        body = store._dir / f"{sample_script.id}.sh"
        meta = store._dir / f"{sample_script.id}.meta.json"
        assert body.exists()
        assert meta.exists()
        assert body.read_text() == "echo hello"

    def test_meta_json_excludes_content(self, store, sample_script):
        store.add(sample_script)
        meta = store._dir / f"{sample_script.id}.meta.json"
        data = json.loads(meta.read_text())
        assert "content" not in data
        assert data["name"] == "hello"
        assert data["type"] == "bash"
        assert data["id"] == sample_script.id

    def test_path_for_returns_body_path(self, store, sample_script):
        store.add(sample_script)
        path = store.path_for(sample_script.id)
        assert path == store._dir / f"{sample_script.id}.sh"
        assert path.exists()

    def test_path_for_unknown_id_raises(self, store):
        with pytest.raises(KeyError):
            store.path_for("does-not-exist")

    def test_meta_with_args_round_trips(self, tmp_path):
        store = ScriptStore(tmp_path / "scripts")
        script = Script(
            name="args",
            description="has args",
            type="python",
            content="import sys; print(sys.argv)",
            args=[
                ScriptArg(name="x", type="string", required=True),
                ScriptArg(name="y", type="integer", required=False, default=7),
            ],
            timeout=30,
            favorite=True,
        )
        store.add(script)

        store2 = ScriptStore(tmp_path / "scripts")
        loaded = store2.get(script.id)
        assert loaded is not None
        assert loaded.timeout == 30
        assert loaded.favorite is True
        assert len(loaded.args) == 2
        assert loaded.args[0].name == "x"
        assert loaded.args[1].default == 7
```

- [ ] **Step 2: Run the new tests against the old `storage.py` and confirm they fail**

Run: `uv run pytest tests/test_storage.py -v`

Expected: A flood of failures. The exact error doesn't matter — what matters is that essentially every test fails because `ScriptStore` still expects a JSON file path, has no `path_for`, etc. If a few happen to pass by accident (e.g. `test_get_nonexistent_returns_none`), that's fine.

This step is the "Red" in TDD — establish that the spec is not yet met.

- [ ] **Step 3: Replace `src/scriptpilot/storage.py` with the new implementation (CRUD + path_for + type rename, no orphan handling yet)**

Replace the entire contents of `/home/kc/repos/script-pilot/src/scriptpilot/storage.py` with:

```python
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from scriptpilot.models import Script
from scriptpilot.paths import EXTENSIONS


class ScriptStore:
    """Per-file script persistence.

    Each script is stored as two files in ``self._dir``:
      - ``<id>.<ext>``       — the script body (extension determined by type)
      - ``<id>.meta.json``   — the Script model dumped without ``content``
    """

    def __init__(self, path: Path | None = None):
        self._dir = path or Path.home() / ".scriptpilot" / "scripts"
        self._scripts: dict[str, Script] = {}
        self._load()

    # ----- public API -----

    def list(self) -> list[Script]:
        return list(self._scripts.values())

    def get(self, script_id: str) -> Script | None:
        return self._scripts.get(script_id)

    def add(self, script: Script):
        self._write(script)
        self._scripts[script.id] = script

    def update(self, script: Script):
        existing = self._scripts.get(script.id)
        self._write(script)
        if existing is not None and existing.type != script.type:
            old_body = self._dir / f"{script.id}{EXTENSIONS[existing.type]}"
            old_body.unlink(missing_ok=True)
        self._scripts[script.id] = script

    def delete(self, script_id: str):
        # Try unlinking every possible body extension; only one will exist.
        for ext in EXTENSIONS.values():
            (self._dir / f"{script_id}{ext}").unlink(missing_ok=True)
        (self._dir / f"{script_id}.meta.json").unlink(missing_ok=True)
        self._scripts.pop(script_id, None)

    def path_for(self, script_id: str) -> Path:
        """On-disk path of the script body. Used by executor and editor."""
        script = self._scripts[script_id]  # raises KeyError if unknown
        return self._dir / f"{script_id}{EXTENSIONS[script.type]}"

    # ----- internals -----

    def _load(self):
        self._dir.mkdir(parents=True, exist_ok=True)
        for meta_path in sorted(self._dir.glob("*.meta.json")):
            stem = meta_path.name[: -len(".meta.json")]
            meta = json.loads(meta_path.read_text())
            ext = EXTENSIONS[meta["type"]]
            body_path = self._dir / f"{stem}{ext}"
            content = body_path.read_text()
            meta["id"] = stem  # filename is authoritative
            script = Script(**meta, content=content)
            self._scripts[script.id] = script

    def _write(self, script: Script):
        body_path = self._dir / f"{script.id}{EXTENSIONS[script.type]}"
        meta_path = self._dir / f"{script.id}.meta.json"

        # Body file: atomic write (tempfile in same dir + replace).
        self._atomic_write(body_path, script.content)

        # Meta file: dump model minus `content`.
        meta = script.model_dump(exclude={"content"})
        self._atomic_write(meta_path, json.dumps(meta, indent=2))

    def _atomic_write(self, target: Path, text: str):
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        try:
            with open(fd, "w") as f:
                f.write(text)
            Path(tmp).replace(target)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise
```

- [ ] **Step 4: Run the storage tests and verify they pass**

Run: `uv run pytest tests/test_storage.py -v`

Expected: All tests in `tests/test_storage.py` PASS. (Loader-edge-case tests are not in this file yet — they're added in Task 3.)

If any test fails: read the failure, fix the implementation (do **not** weaken the test), re-run.

- [ ] **Step 5: Sanity-check: run the full test suite to make sure nothing else regressed**

Run: `uv run pytest -v`

Expected: All tests pass except possibly `tests/test_executor.py` (if you happen to be on a machine where the executor's tempfile path collides with the new storage layout — should not be the case, but worth a glance). At this point all 70+ tests minus the rewritten storage suite should still pass; storage tests pass too.

If executor tests now fail because of the changes, **stop** — that's unexpected; investigate before continuing.

- [ ] **Step 6: Commit**

```bash
git add src/scriptpilot/storage.py tests/test_storage.py
git commit -m "feat: store scripts as per-file body+meta on disk"
```

---

## Task 3: Add loader edge-case handling (orphans + corrupt metas)

**Files:**
- Modify: `src/scriptpilot/storage.py:_load`
- Modify: `tests/test_storage.py` (append three new tests to `TestScriptStore`)

The current `_load` will explode on any orphan meta (missing body), orphan body (no meta — silently ignored already, since we only walk `*.meta.json`), or unparseable JSON. The spec says: skip silently, never crash other scripts. This task adds that resilience and tests it.

- [ ] **Step 1: Append edge-case tests to `tests/test_storage.py`**

Add these methods to the `TestScriptStore` class in `/home/kc/repos/script-pilot/tests/test_storage.py` (after `test_meta_with_args_round_trips`):

```python
    def test_orphan_meta_skipped(self, tmp_path, sample_script):
        # Create a meta file with no matching body.
        store = ScriptStore(tmp_path / "scripts")
        store.add(sample_script)
        body = store._dir / f"{sample_script.id}.sh"
        body.unlink()  # leave only the meta

        # New instance must not raise and must skip the orphan.
        store2 = ScriptStore(tmp_path / "scripts")
        assert store2.list() == []

    def test_orphan_body_skipped(self, tmp_path):
        # Body file with no meta sibling — never even considered.
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "stray.sh").write_text("echo stray")

        store = ScriptStore(scripts_dir)
        assert store.list() == []

    def test_corrupt_meta_skipped(self, tmp_path, sample_script):
        # One good script + one broken meta. Good one must still load.
        store = ScriptStore(tmp_path / "scripts")
        store.add(sample_script)
        (store._dir / "broken.meta.json").write_text("{not valid json")

        store2 = ScriptStore(tmp_path / "scripts")
        loaded = store2.list()
        assert len(loaded) == 1
        assert loaded[0].id == sample_script.id
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run: `uv run pytest tests/test_storage.py::TestScriptStore::test_orphan_meta_skipped tests/test_storage.py::TestScriptStore::test_corrupt_meta_skipped -v`

Expected: both fail with exceptions raised from `_load` — `FileNotFoundError` for the orphan meta case, `json.JSONDecodeError` for the corrupt meta case.

`test_orphan_body_skipped` will already pass because `_load` only iterates `*.meta.json`, but include it in the run as a regression guard:

Run: `uv run pytest tests/test_storage.py::TestScriptStore::test_orphan_body_skipped -v`
Expected: PASS.

- [ ] **Step 3: Update `_load` in `storage.py` to skip on errors**

Replace the `_load` method in `/home/kc/repos/script-pilot/src/scriptpilot/storage.py` with:

```python
    def _load(self):
        self._dir.mkdir(parents=True, exist_ok=True)
        for meta_path in sorted(self._dir.glob("*.meta.json")):
            stem = meta_path.name[: -len(".meta.json")]
            try:
                meta = json.loads(meta_path.read_text())
                ext = EXTENSIONS[meta["type"]]
                body_path = self._dir / f"{stem}{ext}"
                if not body_path.exists():
                    continue  # orphan meta → skip
                content = body_path.read_text()
                meta["id"] = stem
                script = Script(**meta, content=content)
            except Exception:
                continue  # corrupt meta, missing/invalid type, model error → skip
            self._scripts[script.id] = script
```

The `try/except Exception: continue` swallows everything (`json.JSONDecodeError`, `KeyError` on missing/unknown `type`, Pydantic `ValidationError`, file IO errors). This is intentional: the spec says the loader must never crash one script's load on account of another. If the user wants visibility into skipped entries, that's a future logging task.

- [ ] **Step 4: Run the edge-case tests and verify they now pass**

Run: `uv run pytest tests/test_storage.py -v`

Expected: All storage tests pass, including the three new edge-case tests.

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -v`

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/scriptpilot/storage.py tests/test_storage.py
git commit -m "feat: skip orphan and corrupt entries in script loader"
```

---

## Task 4: Refactor executor to run on-disk file directly

**Files:**
- Modify: `src/scriptpilot/executor.py`
- Modify: `tests/test_executor.py`

The executor currently writes `script.content` to a `tempfile.mkstemp` and runs the interpreter on the tempfile. We change it to:
1. Drop the `EXTENSIONS` constant (now in `paths.py`).
2. Remove the tempfile create/cleanup block and the `chmod 0o755` for bash (the file is invoked as `bash <path>`, never `./<path>`).
3. Add a required keyword arg `script_path: Path`.

Test changes: every existing test must now pass `script_path=`. We add a small fixture that writes the script body to `tmp_path` and yields the `(script, path)` pair, so each test stays compact.

- [ ] **Step 1: Rewrite `tests/test_executor.py` with the new fixture and `script_path=` calls**

Replace the entire contents of `/home/kc/repos/script-pilot/tests/test_executor.py` with:

```python
import pytest
from pathlib import Path

from scriptpilot.executor import execute_script, ExecutionResult, InterpreterNotFoundError
from scriptpilot.models import Script, ScriptArg
from scriptpilot.paths import EXTENSIONS


def _materialize(script: Script, tmp_path: Path) -> Path:
    """Write the script body to tmp_path and return its path."""
    body = tmp_path / f"{script.id}{EXTENSIONS[script.type]}"
    body.write_text(script.content)
    return body


@pytest.fixture
def bash_script(tmp_path):
    script = Script(
        name="echo test",
        description="echoes hello",
        type="bash",
        content='echo "hello world"',
    )
    return script, _materialize(script, tmp_path)


class TestExecutor:
    @pytest.mark.asyncio
    async def test_run_bash_script(self, bash_script):
        script, path = bash_script
        lines = []
        result = await execute_script(script, on_output=lines.append, script_path=path)
        assert result.exit_code == 0
        assert not result.timed_out
        assert result.duration >= 0
        assert any("hello world" in line for line in lines)

    @pytest.mark.asyncio
    async def test_run_python_script(self, tmp_path):
        script = Script(
            name="py",
            description="python test",
            type="python",
            content="print('from python')",
        )
        path = _materialize(script, tmp_path)
        lines = []
        result = await execute_script(script, on_output=lines.append, script_path=path)
        assert result.exit_code == 0
        assert any("from python" in line for line in lines)

    @pytest.mark.asyncio
    async def test_script_with_args(self, tmp_path):
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
        path = _materialize(script, tmp_path)
        lines = []
        result = await execute_script(
            script,
            arg_values=["hello", "world"],
            on_output=lines.append,
            script_path=path,
        )
        assert result.exit_code == 0
        assert any("arg1=hello arg2=world" in line for line in lines)

    @pytest.mark.asyncio
    async def test_script_nonzero_exit(self, tmp_path):
        script = Script(
            name="fail",
            description="exits 1",
            type="bash",
            content="exit 42",
        )
        path = _materialize(script, tmp_path)
        result = await execute_script(script, script_path=path)
        assert result.exit_code == 42

    @pytest.mark.asyncio
    async def test_script_timeout(self, tmp_path):
        script = Script(
            name="slow",
            description="sleeps forever",
            type="bash",
            content="sleep 60",
            timeout=1,
        )
        path = _materialize(script, tmp_path)
        result = await execute_script(script, script_path=path)
        assert result.timed_out is True

    @pytest.mark.asyncio
    async def test_stderr_captured(self, tmp_path):
        script = Script(
            name="stderr",
            description="writes to stderr",
            type="bash",
            content='echo "err msg" >&2',
        )
        path = _materialize(script, tmp_path)
        lines = []
        result = await execute_script(script, on_output=lines.append, script_path=path)
        assert result.exit_code == 0
        assert any("err msg" in line for line in lines)

    @pytest.mark.asyncio
    async def test_interpreter_present_on_path(self):
        from scriptpilot.executor import _get_interpreter
        assert _get_interpreter("bash") is not None
        assert _get_interpreter("python") is not None

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

- [ ] **Step 2: Run the executor tests and verify they fail**

Run: `uv run pytest tests/test_executor.py -v`

Expected: All `execute_script(...)` calls fail with `TypeError: execute_script() got an unexpected keyword argument 'script_path'` (or the equivalent for the current signature). This confirms the tests are driving the new contract.

- [ ] **Step 3: Rewrite `executor.py`**

Replace the entire contents of `/home/kc/repos/script-pilot/src/scriptpilot/executor.py` with:

```python
from __future__ import annotations

import asyncio
import os
import signal
import shutil
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
    *,
    script_path: Path,
) -> ExecutionResult:
    """Execute a script (read from ``script_path``) and stream output."""
    interpreter = _get_interpreter(script.type)
    if interpreter is None:
        raise InterpreterNotFoundError(
            f"{INTERPRETERS[script.type]} not found on PATH"
        )

    cmd = [interpreter, str(script_path)]
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
```

Key changes vs. the previous implementation:
- `tempfile`, `EXTENSIONS` imports gone.
- No tempfile create / `os.fdopen` write / `os.chmod` / `try/finally` cleanup block.
- New required keyword arg `script_path: Path`. Caller passes the on-disk body path.
- `cmd = [interpreter, str(script_path)]`.

- [ ] **Step 4: Run the executor tests and verify they pass**

Run: `uv run pytest tests/test_executor.py -v`

Expected: All executor tests PASS.

- [ ] **Step 5: Sanity-check: `screens/main.py` still calls `execute_script` with the old signature, so a full run will fail in `MainScreen._execute`. We don't fix that yet (Task 5). Verify the test suite is in a known state**

Run: `uv run pytest -v`

Expected: All test files pass — `test_executor.py` and `test_storage.py` are green; the other test files (`test_models`, `test_history`, `test_openrouter`) don't touch the executor signature so they're unaffected.

If anything else fails, stop and investigate.

- [ ] **Step 6: Commit**

```bash
git add src/scriptpilot/executor.py tests/test_executor.py
git commit -m "refactor: executor runs on-disk script body directly"
```

---

## Task 5: Wire `MainScreen._execute` to pass `script_path`

**Files:**
- Modify: `src/scriptpilot/screens/main.py:195-199` (the `execute_script(...)` call inside `_execute`)

This is a one-line change to the call site, plus the import is already there. After this task, the app boots and runs scripts end-to-end on the new storage.

- [ ] **Step 1: Edit `MainScreen._execute` to pass `script_path`**

In `/home/kc/repos/script-pilot/src/scriptpilot/screens/main.py`, find the body of `_execute` (around lines 183-220). Change the `execute_script` call from:

```python
                result = await execute_script(
                    script,
                    arg_values=arg_values,
                    on_output=collect_output,
                )
```

to:

```python
                result = await execute_script(
                    script,
                    arg_values=arg_values,
                    on_output=collect_output,
                    script_path=self._store.path_for(script.id),
                )
```

`self._store` is already a `ScriptStore` instance on `MainScreen` (set in `__init__` at line 40), so `path_for` resolves naturally.

- [ ] **Step 2: Run the full test suite**

Run: `uv run pytest -v`

Expected: All tests pass. (No tests cover `MainScreen._execute` directly — it's a Textual screen — so this step is just a regression check.)

- [ ] **Step 3: Manual smoke test — boot the app, create + run a script**

From the project root:

```bash
uv run scriptpilot
```

Inside the TUI:
1. Press `n` for New Script.
2. Fill in name `smoke-test`, description `smoke`, type `bash`, content `echo "live from disk"`.
3. Save.
4. Confirm `~/.scriptpilot/scripts/<uuid>.sh` and `~/.scriptpilot/scripts/<uuid>.meta.json` exist on disk:
   ```bash
   ls ~/.scriptpilot/scripts/
   ```
5. Back in the TUI, select the script and press `r` to run it. Expected: output panel shows `live from disk` with exit code 0.
6. Press `q` to quit. Re-launch `uv run scriptpilot` and confirm `smoke-test` is still present in the list.
7. Press `e` to edit, change type from `bash` to `python` and content to `print("from python now")`. Save. Re-list `~/.scriptpilot/scripts/` and confirm:
   - `<uuid>.py` exists
   - `<uuid>.sh` is gone
   - `<uuid>.meta.json` shows `"type": "python"`
8. Run again — expect `from python now`.
9. Press `d` to delete, confirm. Re-list — both files for that uuid are gone.

If any of those steps fails, stop and investigate before moving on.

- [ ] **Step 4: Commit**

```bash
git add src/scriptpilot/screens/main.py
git commit -m "feat: pass script_path from store to executor in MainScreen"
```

---

## Task 6: Final verification

**Files:**
- None modified — this task is verification only.

- [ ] **Step 1: Full test suite, fresh run**

Run: `uv run pytest -v`

Expected: All tests pass. Note the count — should be the original 70 minus whatever overlaps (the renamed/removed `test_corrupted_json_backs_up_and_resets` and `test_atomic_write`) plus the new tests added in Tasks 2 and 3.

- [ ] **Step 2: Confirm legacy blob is left alone (acceptance criterion)**

If `~/.scriptpilot/scripts.json` happens to exist on the dev machine:

```bash
ls -la ~/.scriptpilot/scripts.json 2>/dev/null && echo "legacy blob present"
```

Boot the app once (`uv run scriptpilot`, then quit with `q`), and confirm:

```bash
ls -la ~/.scriptpilot/scripts.json 2>/dev/null
```

The file's mtime/contents must be unchanged (the new store does not touch it).

If the file does not exist on the dev machine, this step is a no-op — the spec only requires that the legacy blob, *if present*, is not read or modified.

- [ ] **Step 3: Confirm no per-run tempfiles are created (acceptance criterion)**

In one terminal, watch `/tmp` for `*.sh` / `*.py` / `*.js`:

```bash
ls /tmp/tmp*.sh /tmp/tmp*.py /tmp/tmp*.js 2>/dev/null | wc -l
```

In the TUI, run a script. Re-check the same command. The count must be unchanged. (Previously every run added one file; the unlink in the old `finally` block removed it, but during a run it would briefly exist.) The simpler verification: `lsof` on the running script process during a long-running script (e.g. `sleep 5`) should show the interpreter has the on-disk script file open, not a `/tmp/tmpXXXX` path.

- [ ] **Step 4: Done — no further commit needed if all the above passed**

If a step revealed something that needed fixing, fix it as a small follow-up commit. Otherwise the work is complete.
